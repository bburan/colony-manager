"""RQ-backed queue for sync / rematch jobs.

Two surfaces:

* **Enqueue helpers** (``enqueue_datatype_sync``,
  ``enqueue_datatype_rematch``) run inside the Flask request cycle.
  They insert a pending ``SyncJob`` row, push a job onto
  ``app.rq_queue``, stash the RQ id back on the row for the
  stale-job sweep, and return the SyncJob id.
* **Worker entry points** (``run_sync_job``, ``run_rematch_job``)
  execute on the RQ worker process (or inline, when the queue's
  ``is_async`` is False). They use ``current_app`` to reach the
  Flask app context that ``worker.py`` pushed at boot.

Concurrency: the worker is configured as a single process per
queue, so jobs run strictly in FIFO order. Two admins clicking
"sync" simultaneously queue two jobs; they execute serially.
The thread-spawning predecessor allowed parallel execution and
relied on DB unique constraints alone to prevent corruption.
"""
import json
import logging
from datetime import datetime

from flask import current_app
from sqlalchemy import select

from colony_manager.enums import SyncJobKind, SyncJobStatus
from colony_manager.models import SyncJob

from . import db
from .sync import sync_locations, rematch_datatype


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker entry points (run on the RQ worker, NOT in the web process)
# ---------------------------------------------------------------------------

def _execute_job(job_id, work):
    """Shared body: load SyncJob, run *work*, persist outcome.

    Caller must already have a Flask app context. The RQ worker pushes
    one in ``worker.py`` before entering its work loop; the forked
    child inherits it.

    *work* is a zero-arg callable returning a JSON-serializable dict.
    """
    job = db.session.get(SyncJob, job_id)
    if job is None:
        log.warning('SyncJob %s vanished before worker started.', job_id)
        return
    job.status = SyncJobStatus.RUNNING
    job.started_at = datetime.utcnow()
    db.session.commit()

    try:
        summary = work() or {}
        job.status = SyncJobStatus.SUCCESS
        job.summary = json.dumps(summary)
    except Exception as exc:  # noqa: BLE001 — defensive: persist + reraise
        log.exception('SyncJob %s failed', job_id)
        job.status = SyncJobStatus.FAILED
        job.error = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        job.finished_at = datetime.utcnow()
        db.session.commit()
    # Intentionally no ``db.session.remove()`` — under async RQ the
    # forked child exits immediately afterwards, and under sync RQ
    # (tests / dev fallback) this function runs inside the caller's
    # request scope and removing the session would yank it out from
    # under the still-pending Flask teardown.


def run_sync_job(job_id, datatype_id):
    """RQ entry point: scoped ``sync_locations`` run.

    Wrapped by ``_execute_job`` so the SyncJob row reflects the
    outcome; re-raises so RQ marks its own job row as failed and
    surfaces stack traces in the worker logs.
    """
    _execute_job(
        job_id,
        lambda: sync_locations(filter_datatype_id=datatype_id),
    )


def run_rematch_job(job_id, datatype_id, force=False):
    """RQ entry point: scoped ``rematch_datatype`` run."""
    _execute_job(
        job_id,
        lambda: rematch_datatype(datatype_id, force=force),
    )


# ---------------------------------------------------------------------------
# Enqueue helpers (run in the web request thread)
# ---------------------------------------------------------------------------

def _enqueue(kind, datatype_id, func, *args):
    """Insert SyncJob row, push onto RQ queue, write back RQ id, return SyncJob id.

    The two commits (one for ``status='pending'``, one to record
    ``rq_job_id``) keep the row queryable even if the second commit
    fails: a row with no rq_job_id is treated as stale at the next
    worker boot and re-failed cleanly.
    """
    queue = current_app.rq_queue
    job = SyncJob(kind=kind, datatype_id=datatype_id, status=SyncJobStatus.PENDING)
    db.session.add(job)
    db.session.commit()
    job_id = job.id

    rq_job = queue.enqueue(func, job_id, *args, job_timeout='1h')
    # In async mode ``job`` is still attached to this session; in sync
    # mode the worker function already ran in this same session and
    # committed status='success' (or 'failed'). Re-fetch defensively
    # so we write rq_job_id onto the live row in either path.
    job = db.session.get(SyncJob, job_id)
    if job is not None:
        job.rq_job_id = rq_job.id
        db.session.commit()
    return job_id


def enqueue_datatype_sync(datatype_id):
    """Queue a ``sync_locations`` run scoped to one DataType."""
    return _enqueue(SyncJobKind.SYNC, datatype_id, run_sync_job, datatype_id)


def enqueue_datatype_rematch(datatype_id, force=False):
    """Queue a ``rematch_datatype`` run for one DataType."""
    return _enqueue(
        SyncJobKind.FORCE_REMATCH if force else SyncJobKind.REMATCH,
        datatype_id,
        run_rematch_job, datatype_id, force,
    )


# ---------------------------------------------------------------------------
# Read helpers (used by the settings page recent-jobs panel)
# ---------------------------------------------------------------------------

def recent_jobs(limit=10):
    """Return the most recent jobs (any status) for display in the UI."""
    return db.session.scalars(
        select(SyncJob)
        .order_by(SyncJob.enqueued_at.desc())
        .limit(limit)
    ).all()


def parse_summary(job):
    """Decode ``SyncJob.summary`` for template display."""
    if not job.summary:
        return {}
    try:
        return json.loads(job.summary)
    except (TypeError, ValueError):
        return {}
