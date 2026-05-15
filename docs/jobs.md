# Background jobs

Sync and rematch runs (file walks, hash computation, target matching) are slow enough that they can't block an HTTP response. They run in a background worker via [RQ](https://python-rq.org).

## Architecture

```
┌─────────┐  enqueue   ┌───────┐  pop   ┌────────┐  read/write  ┌──────────┐
│  Flask  │──────────▶ │ Redis │ ─────▶ │ Worker │ ────────────▶│ Postgres │
│ (web)   │            │       │        │ (RQ)   │              │ (SyncJob)│
└─────────┘            └───────┘        └────────┘              └──────────┘
                                            │
                                            └─── runs sync_locations /
                                                 rematch_datatype
```

- **Web process** (Gunicorn): inserts a `SyncJob` row, pushes a job to the `sync` queue, returns the redirect immediately.
- **Worker process** (`python -m colony_manager_gui.worker`): drains the queue serially. Updates the `SyncJob` row through its lifecycle: `pending → running → success | failed`.
- **Redis**: brokers the queue. Holds job metadata (function name, args, status) for the worker to pick up.
- **Postgres**: the authoritative store of job state for the UI to display. `SyncJob.rq_job_id` ties each row to its RQ counterpart so the boot-time sweep can identify orphans.

## Operations

### Triggering a sync from the UI

Settings page → DataType row → **Sync Now** button. The route hits `POST /settings/datatype/<id>/sync`, which calls `enqueue_datatype_sync(datatype_id)` and redirects. The recent-jobs panel polls every few seconds via HTMX and renders the row's current status.

### Triggering programmatically

```python
from colony_manager_gui import jobs

with app.app_context():
    job_id = jobs.enqueue_datatype_sync(datatype_id)
    # or
    job_id = jobs.enqueue_datatype_rematch(datatype_id, force=False)
```

Returns the `SyncJob.id`, useful for storing and polling.

### Monitoring

```sh
# Worker process logs (real-time)
docker compose logs -f worker

# Redis queue depth
docker compose exec redis redis-cli LLEN rq:queue:sync

# Most recent jobs (SQL)
docker compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB \
    -c "SELECT id, kind, status, enqueued_at, finished_at FROM sync_job ORDER BY id DESC LIMIT 10;"

# Live worker + queue stats via the RQ CLI
docker compose exec worker rq info --url redis://redis:6379/0
docker compose exec worker rq info -i 5 --url redis://redis:6379/0  # top-style refresh
```

For a sustained dashboard, bring up the optional `rq-dashboard` service
defined in `docker-compose.example.yml` and browse to
`http://localhost:9181`. It surfaces queued / running / finished /
failed jobs with stack traces and one-click requeue. **It has no built-
in auth** — the example compose binds it to `127.0.0.1:9181` so only
the host reaches it; set `RQ_DASHBOARD_USERNAME` / `RQ_DASHBOARD_PASSWORD`
and switch the bind to `9181:9181` if you want LAN access.

### Scaling

Single worker is the safe default — guarantees no two sync runs against the same `DataType` clash on disk I/O. To scale:

```sh
docker compose up -d --scale worker=3
```

The stale-job sweep at boot is idempotent across workers (each calls `_sweep_stale_jobs` once). If you need stricter per-`DataType` serialization with multiple workers, layer a Redis `SETNX` lock at the top of `run_sync_job` / `run_rematch_job` — not currently implemented.

### Recovery

If a worker is killed mid-job (OOM, SIGTERM, container recycle), the next worker boot's `_sweep_stale_jobs` finds the `SyncJob` row stuck in `pending`/`running` whose `rq_job_id` is no longer in Redis and marks it `failed` with the message *"Worker restarted while job was in flight."* Operators can then re-trigger the sync from the UI.

To manually mark a stuck row failed without restarting the worker:

```sql
UPDATE sync_job
SET status = 'failed', error = 'manual recovery', finished_at = now()
WHERE id = <id>;
```

## Local development

### Option A — `docker compose up` (production-fidelity)

Runs the full stack with a real Redis + real worker. Recommended whenever you're testing background behavior.

```sh
docker compose up -d
```

### Option B — Flask only, no Redis

If you're iterating on routes/templates and don't care about background execution, leave `REDIS_URL` unset:

```sh
unset REDIS_URL
flask --app colony_manager_gui:create_app run
```

Without `REDIS_URL`, `_configure_rq` falls back to **fakeredis + `is_async=False`**. Enqueuing a sync executes it inline in the request thread. Slower per click, but no Redis or worker process needed.

This is also how the test suite runs — every Postgres-backed test under `pytest` uses the fakeredis fallback automatically.

### Running the worker manually (without compose)

```sh
export DATABASE_URL=postgresql+psycopg2://...
export REDIS_URL=redis://localhost:6379/0
export SECRET_KEY=dev
export COLONY_MANAGER_DESCRIPTION_REGISTRY=mmm_db.registry
python -m colony_manager_gui.worker
```

The worker performs the stale-job sweep, then enters `Worker.work(with_scheduler=True)`. It blocks until killed.

> **Windows note**: RQ workers use `os.fork()`, which doesn't work on native Windows. Use WSL, Docker Desktop, or stick to Option B (`is_async=False`) for local Windows dev.

## Adding scheduled (cron-style) jobs

`rq-scheduler` is installed alongside RQ (see `pyproject.toml` gui extras). It uses the same Redis instance.

### Adding a recurring job

Define the function in a module the worker can import (e.g. `colony_manager_gui.scheduled_jobs`):

```python
def nightly_sync_all():
    """Re-sync every DataType. Runs at 02:00 UTC."""
    from colony_manager.models import DataType
    from colony_manager_gui import jobs, db
    from sqlalchemy import select

    for dt in db.session.scalars(select(DataType)).all():
        if dt.locations:
            jobs.enqueue_datatype_sync(dt.id)
```

Register it once (e.g. at app startup or in a one-off script):

```python
from rq_scheduler import Scheduler
from colony_manager_gui import create_app

app = create_app()
scheduler = Scheduler(queue=app.rq_queue, connection=app.rq_queue.connection)

# Cancel any previous registration before re-adding (idempotent).
for job in scheduler.get_jobs():
    if job.func_name.endswith('.nightly_sync_all'):
        scheduler.cancel(job)

scheduler.cron(
    '0 2 * * *',  # at 02:00 every day
    func='colony_manager_gui.scheduled_jobs.nightly_sync_all',
    repeat=None,  # forever
)
```

### Running the scheduler

`rq-scheduler` ships an `rqscheduler` command that polls the schedule and enqueues due jobs:

```sh
rqscheduler --url $REDIS_URL --interval 60
```

In compose, add a sibling service alongside `worker`:

```yaml
scheduler:
  build:
    context: .
    dockerfile: ./app/colony-manager/Dockerfile
  command: ["rqscheduler", "--url", "redis://redis:6379/0", "--interval", "60"]
  restart: unless-stopped
  depends_on: [db, redis]
  environment:
    - REDIS_URL=redis://redis:6379/0
    # (DATABASE_URL etc. only needed if scheduled job *definitions*
    # touch the DB during scheduler startup)
```

Not added by default — wait until you have an actual recurring job to register.

## Testing

Job-related tests use the same `app` fixture as the rest of the suite. Because the test env doesn't set `REDIS_URL`, `_configure_rq` wires a fakeredis queue with `is_async=False` — `queue.enqueue(...)` runs the work function inline and the test sees the final `SyncJob` row state synchronously.

Two patterns:

**Unit-style** (direct call to the enqueue helper):

```python
def test_enqueue_sync(app, db_session):
    with app.app_context():
        job_id = jobs.enqueue_datatype_sync(dtype.id)
    db_session.expire_all()
    assert db_session.get(SyncJob, job_id).status == 'success'
```

**Route-style** (POST `/settings/datatype/<id>/sync`):

```python
def test_route_enqueues(logged_in_client, db_session):
    response = logged_in_client.post(
        f'/settings/datatype/{dtype.id}/sync', follow_redirects=False,
    )
    assert response.status_code == 302
```

The fakeredis path doesn't fork; everything runs in the test process. No Redis service required.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `RuntimeError: REDIS_URL is required when fakeredis is not installed` at app boot | Production-style env without `REDIS_URL` and `fakeredis` not in the image | Set `REDIS_URL` (preferred) or `pip install fakeredis` (dev only) |
| Worker logs `Marked N stale SyncJob row(s) as failed.` at every boot | Pending/running rows are accumulating without the worker actually running | Check worker container health: `docker compose ps worker`. Look at recent worker logs |
| Jobs queue but never run | Worker not connected to the same Redis as web | Confirm both services have identical `REDIS_URL`. `docker compose exec web env \| grep REDIS_URL` |
| Worker dies with `ConnectionError` | Redis service not up yet at worker start | Ensure `depends_on: [redis]` on the worker service. Compose's `depends_on` doesn't guarantee Redis is *ready*, only *started* — RQ retries on its own for a few seconds |
| `Job is no longer in the queue` exception in worker | RQ job was deleted/expired before worker picked it up | Usually benign; the SyncJob row gets swept on next boot. If chronic, raise `result_ttl` / `failure_ttl` on `queue.enqueue` calls |
