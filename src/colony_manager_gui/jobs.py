"""Background-thread runner for sync / rematch jobs.

Each public ``enqueue_*`` function inserts a :class:`SyncJob` row, spins
up a daemon thread, and returns the job id so the caller can redirect
immediately. The thread re-establishes a Flask app context, runs the
real work via :mod:`colony_manager_gui.sync`, and updates the job row
with status + summary + error.

Concurrency note: there is intentionally no per-DataType lock. Two
admins clicking "rematch" at the same time will run two threads in
parallel against the same DataType. The relevant DB constraints
(``UniqueConstraint('location_id', 'relative_path')`` on ``Data``,
secondary-table PKs on the m2m target tables) make duplicates
impossible, so the worst case is wasted I/O — not corrupted state.
"""
import json
import logging
import threading
from datetime import datetime

from flask import current_app
from sqlalchemy import select

from colony_manager.models import SyncJob

from . import db
from .sync import sync_locations, rematch_datatype


log = logging.getLogger(__name__)


def _run_in_app_context(app, job_id, work):
    """Execute *work* with a fresh app context and persist the result.

    ``work`` is a zero-arg callable returning a dict that will be
    JSON-encoded into ``SyncJob.summary``.
    """
    with app.app_context():
        # ``db.session`` is a scoped session; calling it inside the
        # thread gets a fresh session bound to this thread's context.
        job = db.session.get(SyncJob, job_id)
        if job is None:
            log.warning('SyncJob %s vanished before the thread started.', job_id)
            return
        job.status = 'running'
        job.started_at = datetime.utcnow()
        db.session.commit()

        try:
            summary = work() or {}
            job.status = 'success'
            job.summary = json.dumps(summary)
        except Exception as exc:  # pragma: no cover — defensive
            log.exception('SyncJob %s failed', job_id)
            job.status = 'failed'
            job.error = f'{type(exc).__name__}: {exc}'
        finally:
            job.finished_at = datetime.utcnow()
            db.session.commit()
            db.session.remove()


def _enqueue(kind, datatype_id, work):
    """Insert a pending job row, start the worker thread, return the id."""
    app = current_app._get_current_object()
    job = SyncJob(kind=kind, datatype_id=datatype_id, status='pending')
    db.session.add(job)
    db.session.commit()
    job_id = job.id

    thread = threading.Thread(
        target=_run_in_app_context,
        args=(app, job_id, work),
        name=f'sync-job-{job_id}',
        daemon=True,
    )
    thread.start()
    return job_id


def enqueue_datatype_sync(datatype_id):
    """Queue a ``sync_locations`` run scoped to one DataType."""
    return _enqueue(
        kind='sync',
        datatype_id=datatype_id,
        work=lambda: sync_locations(filter_datatype_id=datatype_id),
    )


def enqueue_datatype_rematch(datatype_id, force=False):
    """Queue a ``rematch_datatype`` run for one DataType."""
    return _enqueue(
        kind='force_rematch' if force else 'rematch',
        datatype_id=datatype_id,
        work=lambda: rematch_datatype(datatype_id, force=force),
    )


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
