"""Tests for ``colony_manager_gui.worker._sweep_stale_jobs``.

The sweep runs once at worker boot to recover from the worker-killed-
mid-job scenario the thread-based predecessor couldn't handle. A
SyncJob row stays alive if its ``rq_job_id`` still resolves to a Job
in Redis; otherwise it's marked failed with a "worker restarted"
note. Rows in terminal states (``success`` / ``failed``) are ignored.

These tests use the fakeredis-backed queue from the ``app`` fixture
so they don't need a live Redis or RQ worker.
"""
from datetime import datetime

from sqlalchemy import select

from colony_manager.models import SyncJob
from colony_manager_gui.worker import _sweep_stale_jobs


def test_sweep_marks_row_without_rq_job_id(db_session, app):
    """A row in 'pending' with no rq_job_id is presumed orphaned."""
    job = SyncJob(kind='sync', status='pending', rq_job_id=None)
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    _sweep_stale_jobs(app, app.rq_queue)

    db_session.expire_all()
    refreshed = db_session.get(SyncJob, job_id)
    assert refreshed.status == 'failed'
    assert refreshed.error == 'Worker restarted while job was in flight.'
    assert refreshed.finished_at is not None


def test_sweep_marks_row_with_stale_rq_job_id(db_session, app):
    """A row whose RQ id no longer exists in Redis is failed."""
    job = SyncJob(
        kind='rematch', status='running', rq_job_id='nonexistent-rq-id',
    )
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    _sweep_stale_jobs(app, app.rq_queue)

    db_session.expire_all()
    refreshed = db_session.get(SyncJob, job_id)
    assert refreshed.status == 'failed'
    assert refreshed.error == 'Worker restarted while job was in flight.'


def test_sweep_keeps_row_with_live_rq_job_id(db_session, app):
    """A row whose RQ id still resolves to a Job is left alone.

    With fakeredis + ``is_async=False``, enqueueing actually runs the
    function then persists the Job in the finished registry — so
    ``Job.fetch`` succeeds afterwards and the sweep treats the row
    as still-tracked.
    """
    # Real enqueue against the fake Redis. The job runs to completion
    # (no-op lambda), and its id stays fetchable.
    with app.app_context():
        rq_job = app.rq_queue.enqueue(lambda: None)

    # Manually create a SyncJob row pointing at that rq id, in a
    # non-terminal state. Real-world this would never linger like
    # this — but the sweep mustn't touch it either way.
    job = SyncJob(
        kind='sync', status='pending', rq_job_id=rq_job.id,
    )
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    _sweep_stale_jobs(app, app.rq_queue)

    db_session.expire_all()
    refreshed = db_session.get(SyncJob, job_id)
    assert refreshed.status == 'pending'  # unchanged
    assert refreshed.error is None
    assert refreshed.finished_at is None


def test_sweep_ignores_terminal_states(db_session, app):
    """Rows already in ``success`` / ``failed`` aren't touched."""
    succeeded = SyncJob(
        kind='sync', status='success', rq_job_id=None,
        finished_at=datetime(2025, 1, 1, 12, 0, 0),
    )
    failed = SyncJob(
        kind='sync', status='failed', rq_job_id=None, error='prior boom',
        finished_at=datetime(2025, 1, 2, 12, 0, 0),
    )
    db_session.add_all([succeeded, failed])
    db_session.commit()
    succ_id, fail_id = succeeded.id, failed.id

    _sweep_stale_jobs(app, app.rq_queue)

    db_session.expire_all()
    assert db_session.get(SyncJob, succ_id).status == 'success'
    refreshed_failed = db_session.get(SyncJob, fail_id)
    assert refreshed_failed.status == 'failed'
    assert refreshed_failed.error == 'prior boom'  # original error preserved


def test_sweep_no_op_when_no_stale_rows(db_session, app):
    """Empty DB → sweep is a no-op, no exception."""
    _sweep_stale_jobs(app, app.rq_queue)

    rows = db_session.scalars(select(SyncJob)).all()
    assert rows == []


def test_sweep_handles_mixed_rows(db_session, app):
    """One stale + one live + one terminal — only the stale flips."""
    with app.app_context():
        rq_job = app.rq_queue.enqueue(lambda: None)

    stale = SyncJob(kind='sync', status='pending', rq_job_id='dead-id')
    live = SyncJob(kind='sync', status='pending', rq_job_id=rq_job.id)
    done = SyncJob(
        kind='sync', status='success', rq_job_id='whatever',
        finished_at=datetime(2025, 1, 1),
    )
    db_session.add_all([stale, live, done])
    db_session.commit()
    stale_id, live_id, done_id = stale.id, live.id, done.id

    _sweep_stale_jobs(app, app.rq_queue)

    db_session.expire_all()
    assert db_session.get(SyncJob, stale_id).status == 'failed'
    assert db_session.get(SyncJob, live_id).status == 'pending'
    assert db_session.get(SyncJob, done_id).status == 'success'
