"""RQ worker entry point for background sync / rematch jobs.

Run via::

    python -m colony_manager_gui.worker

or from Docker via the worker service in ``docker-compose.yml``.

Wires the Flask app context once at startup so each job picks up the
configured ``db.session``, then performs a stale-job sweep (any
``SyncJob`` rows whose RQ id is no longer in Redis get marked failed —
this catches the "Gunicorn killed the worker mid-job" scenario the
threading-based predecessor couldn't), and finally enters the
``rq.Worker.work()`` loop on the configured queue.

The actual ``Queue`` object is built in the Flask app factory
(``create_app``) and stashed on ``app.rq_queue`` — see :mod:`jobs`.
"""
import logging
import os
import sys
from datetime import datetime

log = logging.getLogger(__name__)


def _sweep_stale_jobs(app, queue):
    """Mark any SyncJob whose RQ counterpart has vanished as failed.

    Runs once at worker boot. A row stays untouched if its
    ``rq_job_id`` still resolves to an RQ ``Job`` row in Redis —
    that means the job is legitimately queued or running and will
    be picked up momentarily. A row with no ``rq_job_id`` (or one
    whose RQ side returned ``NoSuchJobError``) is presumed orphaned.
    """
    from sqlalchemy import select
    from rq.job import Job
    from rq.exceptions import NoSuchJobError

    from colony_manager.models import SyncJob
    from . import db

    with app.app_context():
        rows = db.session.scalars(
            select(SyncJob).where(SyncJob.status.in_(('pending', 'running')))
        ).all()
        swept = 0
        for job in rows:
            if job.rq_job_id:
                try:
                    Job.fetch(job.rq_job_id, connection=queue.connection)
                    continue  # still live in Redis
                except NoSuchJobError:
                    pass
            job.status = 'failed'
            job.error = 'Worker restarted while job was in flight.'
            job.finished_at = datetime.utcnow()
            swept += 1
        if swept:
            db.session.commit()
            log.warning('Marked %d stale SyncJob row(s) as failed.', swept)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-8s %(name)s: %(message)s',
    )

    # Imported here so a stray import-time failure surfaces with a
    # full traceback under the configured logger rather than during
    # interpreter startup.
    from rq import Worker

    from . import create_app

    app = create_app()
    queue = getattr(app, 'rq_queue', None)
    if queue is None:
        log.error(
            'app.rq_queue is unset — did create_app() configure RQ? '
            'Check that REDIS_URL is set in the environment.'
        )
        sys.exit(1)

    _sweep_stale_jobs(app, queue)

    log.info('Starting RQ worker on queue %r', queue.name)
    # Push the app context for the worker process so the forked
    # children inherit it. Each job function still re-resolves
    # ``db.session`` from the scoped registry, which is fork-safe
    # because the child gets its own copy of the registry.
    with app.app_context():
        worker = Worker([queue], connection=queue.connection)
        worker.work(with_scheduler=True)


if __name__ == '__main__':
    main()
