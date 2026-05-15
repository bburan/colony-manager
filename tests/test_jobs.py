"""Tests for the RQ-backed job queue in ``colony_manager_gui.jobs``.

The ``app`` fixture configures fakeredis + ``is_async=False`` (see
``_configure_rq`` in the app factory), so every ``queue.enqueue(...)``
call here executes the work function inline in the test process.
That gives us deterministic state transitions without spinning up a
real worker.

The four kinds of coverage here:

* **Enqueue happy path** — SyncJob row created, work runs to
  completion, row ends in ``success`` with the summary JSON-encoded
  and ``rq_job_id`` written back.
* **Enqueue failure path** — work raises → row ends in ``failed``
  with the error message captured.
* **Read helpers** — ``recent_jobs`` ordering and ``parse_summary``
  edge cases.
* **Routes** — POST /settings/datatype/<id>/sync and /rematch
  redirect cleanly and persist the right SyncJob kind.
"""
import json

import pytest
from sqlalchemy import select

from colony_manager.models import SyncJob
from colony_manager_gui import jobs

from .factories import (
    make_animal_event_data_type, make_data_location, make_procedure,
)


# ---------------------------------------------------------------------------
# Enqueue happy paths
# ---------------------------------------------------------------------------

def test_enqueue_datatype_sync_runs_to_completion(app, db_session, tmp_path):
    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)

    with app.app_context():
        job_id = jobs.enqueue_datatype_sync(dtype.id)

    db_session.expire_all()
    job = db_session.get(SyncJob, job_id)
    assert job.kind == 'sync'
    assert job.datatype_id == dtype.id
    assert job.status == 'success'
    assert job.started_at is not None
    assert job.finished_at is not None
    assert job.rq_job_id is not None
    # Summary is JSON-encoded; sync_locations returns counts dict.
    summary = json.loads(job.summary)
    assert 'added' in summary


def test_enqueue_datatype_rematch_runs_to_completion(app, db_session):
    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )

    with app.app_context():
        job_id = jobs.enqueue_datatype_rematch(dtype.id, force=False)

    db_session.expire_all()
    job = db_session.get(SyncJob, job_id)
    assert job.kind == 'rematch'
    assert job.status == 'success'
    assert job.rq_job_id is not None


def test_enqueue_datatype_force_rematch_sets_kind(app, db_session):
    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )

    with app.app_context():
        job_id = jobs.enqueue_datatype_rematch(dtype.id, force=True)

    db_session.expire_all()
    job = db_session.get(SyncJob, job_id)
    assert job.kind == 'force_rematch'


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------

def test_work_function_failure_records_error(app, db_session, monkeypatch):
    """When the work function raises, the SyncJob row is marked failed
    with the exception's class + message captured.

    Note: RQ's sync mode (``is_async=False``) captures the exception
    on its own Job row and does not re-raise. Our ``_execute_job``
    still flips the SyncJob row to ``failed`` *before* the re-raise
    inside ``_execute_job``, so the row reflects the failure even
    though ``enqueue_datatype_sync`` returns normally. In async (real
    worker) mode the exception propagates to RQ, which logs it and
    marks the RQ side failed too.
    """
    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )

    def explode(*args, **kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr('colony_manager_gui.jobs.sync_locations', explode)

    with app.app_context():
        job_id = jobs.enqueue_datatype_sync(dtype.id)

    db_session.expire_all()
    job = db_session.get(SyncJob, job_id)
    assert job.status == 'failed'
    assert job.error == 'RuntimeError: boom'
    assert job.finished_at is not None


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def test_recent_jobs_orders_newest_first(db_session, app):
    """``recent_jobs`` orders by enqueued_at descending."""
    from datetime import datetime, timedelta
    base = datetime(2025, 6, 1, 12, 0, 0)
    older = SyncJob(kind='sync', status='success', enqueued_at=base)
    newer = SyncJob(
        kind='sync', status='success', enqueued_at=base + timedelta(hours=1),
    )
    db_session.add_all([older, newer])
    db_session.commit()

    with app.app_context():
        rows = jobs.recent_jobs()
    assert [r.id for r in rows] == [newer.id, older.id]


def test_recent_jobs_respects_limit(db_session, app):
    for _ in range(5):
        db_session.add(SyncJob(kind='sync', status='success'))
    db_session.commit()
    with app.app_context():
        assert len(jobs.recent_jobs(limit=3)) == 3


def test_parse_summary_handles_empty(app):
    """Defensive: row with no summary returns {} rather than crashing."""
    job = SyncJob(kind='sync', status='pending')
    assert jobs.parse_summary(job) == {}


def test_parse_summary_decodes_json(app):
    job = SyncJob(kind='sync', status='success', summary='{"added": 3}')
    assert jobs.parse_summary(job) == {'added': 3}


def test_parse_summary_malformed_returns_empty(app):
    """Don't crash the dashboard on a corrupted summary."""
    job = SyncJob(kind='sync', status='success', summary='not-json')
    assert jobs.parse_summary(job) == {}


# ---------------------------------------------------------------------------
# Routes that enqueue
# ---------------------------------------------------------------------------

def test_sync_datatype_route_enqueues_job(logged_in_client, db_session):
    """POST /settings/datatype/<id>/sync redirects and enqueues a SyncJob.

    Route refuses the queue if the DataType has no description_class
    *or* no locations — provide both so the enqueue actually fires.
    """
    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event'  # the orchestration fakes registry
    make_data_location(db_session, datatype=dtype, base_path='/tmp')
    db_session.commit()

    # The route imports load_description_class indirectly via sync. We
    # need the registry env var set for the work function to run. The
    # orchestration test's autouse fixture isn't active here, so set
    # it explicitly via the existing _description_fakes module.
    import os
    prior = os.environ.get('COLONY_MANAGER_DESCRIPTION_REGISTRY')
    os.environ['COLONY_MANAGER_DESCRIPTION_REGISTRY'] = 'tests._description_fakes'
    from colony_manager.datatypes import reset_registry_cache
    reset_registry_cache()
    try:
        response = logged_in_client.post(
            f'/settings/datatype/{dtype.id}/sync', follow_redirects=False,
        )
    finally:
        if prior is None:
            os.environ.pop('COLONY_MANAGER_DESCRIPTION_REGISTRY', None)
        else:
            os.environ['COLONY_MANAGER_DESCRIPTION_REGISTRY'] = prior
        reset_registry_cache()

    assert response.status_code == 302
    db_session.expire_all()
    job = db_session.scalars(
        select(SyncJob).where(SyncJob.datatype_id == dtype.id)
    ).first()
    assert job is not None
    assert job.kind == 'sync'


def test_rematch_datatype_route_enqueues_job(logged_in_client, db_session):
    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )

    response = logged_in_client.post(
        f'/settings/datatype/{dtype.id}/rematch', follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    job = db_session.scalars(
        select(SyncJob).where(SyncJob.datatype_id == dtype.id)
    ).first()
    assert job is not None
    assert job.kind == 'rematch'


def test_rematch_force_query_param_sets_kind(logged_in_client, db_session):
    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )

    logged_in_client.post(
        f'/settings/datatype/{dtype.id}/rematch?force=1',
        follow_redirects=False,
    )
    db_session.expire_all()
    job = db_session.scalars(
        select(SyncJob).where(SyncJob.datatype_id == dtype.id)
    ).first()
    assert job.kind == 'force_rematch'
