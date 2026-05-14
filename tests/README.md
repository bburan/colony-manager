# Test suite

Two tiers:

| Tier | What it covers | Needs Postgres? |
|---|---|---|
| **Unit** | Helper-level code (escapes, safe-url, public decorator, secret-key handling, description registry). Already in this directory. | No |
| **Integration** | Models, sync core, GUI routes. Runs against a real Postgres via template-DB cloning. | Yes |

The unit tier runs anywhere with `pytest`. The integration tier needs a one-time Postgres setup, described below.

## One-time Postgres setup

You need a role on your Postgres cluster that can `CREATEDB`. Superuser is **not** required. **You do not need to create a database** — the fixtures do that themselves. You only create the role.

### Option A — Docker container

Most users on Windows will be running Postgres in a Docker container. Pick the path that matches your situation.

**A1. You already have a Postgres container running** (e.g. for the app itself):

```cmd
:: Find the container name
docker ps
```

You should see a row like `postgres:16` or similar. Note the container name (rightmost column).

Open a shell inside the container:

```cmd
docker exec -it <container_name> bash
```

You're now inside the container. The official `postgres` image creates a `postgres` superuser whose login uses peer/trust auth on the unix socket, so no password is needed from inside. Create the test role:

```bash
psql -U postgres -d postgres -c "CREATE ROLE colony_test WITH LOGIN PASSWORD 'testing' CREATEDB;"
```

Verify:

```bash
psql -U postgres -d postgres -c "\du colony_test"
```

The output should show `Create DB` under "Attributes". Exit the container:

```bash
exit
```

Back on your Windows host, figure out which port the container exposes. From the `docker ps` output, look at the `PORTS` column — something like `0.0.0.0:5432->5432/tcp` means port 5432 on the host. Then:

```cmd
set TEST_DATABASE_URL=postgresql+psycopg2://colony_test:testing@localhost:5432
```

If the host port is different (e.g. `0.0.0.0:5433->5432/tcp`), use `5433` instead.

Test the connection from the host (requires `psql` on Windows — install via the Postgres installer or skip this step):

```cmd
psql -h localhost -p 5432 -U colony_test -d postgres
```

If you don't have `psql` on Windows, skip this — `pytest` itself will tell you immediately if the connection is wrong.

**A2. Spin up a fresh Postgres container just for tests:**

```cmd
docker run -d --name colony-test-pg ^
    -e POSTGRES_PASSWORD=admin ^
    -p 5432:5432 ^
    postgres:16
```

(The `^` is `cmd.exe`'s line continuation. You can also paste it all on one line.)

Wait a few seconds for the container to start, then create the role:

```cmd
docker exec -it colony-test-pg psql -U postgres -d postgres -c "CREATE ROLE colony_test WITH LOGIN PASSWORD 'testing' CREATEDB;"

:: If the image uses a different superuser (check ``docker inspect``),
:: substitute its name for ``postgres`` above.
```

Set the connection URL:

```cmd
set TEST_DATABASE_URL=postgresql+psycopg2://colony_test:testing@localhost:5432
```

When you're done with the container:

```cmd
docker stop colony-test-pg
docker rm colony-test-pg
```

### Option B — Native Postgres install

If Postgres is installed directly on Windows (e.g. via the EnterpriseDB installer), open `cmd.exe`:

```cmd
psql -U postgres -d postgres -c "CREATE ROLE colony_test WITH LOGIN PASSWORD 'testing' CREATEDB;"
```

You'll be prompted for the `postgres` superuser password you set during install. Verify:

```cmd
psql -U colony_test -d postgres -c "\du colony_test"
```

Set the connection URL:

```cmd
set TEST_DATABASE_URL=postgresql+psycopg2://colony_test:testing@localhost:5432
```

### Common to both options

**`role "X" does not exist`** — the superuser isn't named `postgres`. Inside the container, run `env | grep -i postgres` to find `POSTGRES_USER`. Use that name in place of `postgres` in the commands above.

**`database "X" does not exist`** — `psql` defaults the database name to the username. Always pass `-d postgres` explicitly to connect to the maintenance database.

If `\du colony_test` shows the role but **without** `Create DB`, grant it:

```sql
ALTER ROLE colony_test CREATEDB;
```

If you see `Cannot login` instead of a role row, your cluster's `pg_hba.conf` is rejecting the role — usually only an issue for native installs with restrictive auth config. Check `pg_hba.conf` for a line allowing `colony_test` (or `all`) from `localhost`/`127.0.0.1` via `md5` or `scram-sha-256`.

### Sanity check before running tests

This catches misconfiguration faster than running pytest:

```cmd
docker exec -it <container_name> psql -U colony_test -d postgres -c "CREATE DATABASE _connectivity_check; DROP DATABASE _connectivity_check;"
```

(For a native install, drop the `docker exec -it <container_name>` prefix.)

If that runs without error, the fixtures will work.

## Per-environment config

The fixtures read **environment variables only** (no .env file, no config file). Set these in your shell, `direnv`, IDE run-config, or CI secret store:

| Variable | Required | Example | Purpose |
|---|---|---|---|
| `TEST_DATABASE_URL` | yes | `postgresql+psycopg2://colony_test:pw@localhost:5432` | Cluster URL. **No trailing database name.** The fixtures append `/postgres` for admin operations and `/colony_test_*` for per-test DBs. |
| `TEST_DB_PREFIX` | no | `colony_test` | Defaults to `colony_test`. All template + per-test DBs get this prefix; useful if you share a cluster with other projects. |
| `TEST_KEEP_DBS` | no | `1` | If set (any truthy value), tests skip teardown so you can inspect a failing test's DB with `psql`. |

Example setup.

Windows `cmd.exe` (current session only):

```cmd
set TEST_DATABASE_URL=postgresql+psycopg2://colony_test:pw@localhost:5432
```

Windows `cmd.exe` (persist for future sessions):

```cmd
setx TEST_DATABASE_URL "postgresql+psycopg2://colony_test:pw@localhost:5432"
```

Note: `setx` only affects *future* `cmd.exe` sessions, not the current one. After running `setx`, open a new terminal.

bash/zsh (Linux, macOS, WSL):

```sh
export TEST_DATABASE_URL='postgresql+psycopg2://colony_test:pw@localhost:5432'
```

If `TEST_DATABASE_URL` isn't set, integration tests are **skipped** (not failed). The unit tier still runs.

## Running tests

Install test deps once:

```sh
pip install -e '.[test]'
# For parallel runs:
pip install pytest-xdist
```

Serial:

```sh
pytest                       # all tests
pytest tests/test_animal.py  # one file
pytest -k terminate          # by keyword
```

Parallel (one worker per CPU):

```sh
pytest -n auto
```

Each xdist worker builds its **own** template database (`colony_test_template_gw0`, `colony_test_template_gw1`, ...). Postgres takes an exclusive lock on a template DB during clone, so sharing a single template across workers would serialize them. The per-worker startup cost is a few seconds (running `alembic upgrade head` once).

## How it works

1. **Session start (once per worker):** `template_db` fixture
   - Drops + recreates `colony_test_template_<worker>`.
   - Runs `alembic upgrade head` against it.
   - Marks it as `is_template = true`.
2. **Per test that requests `db_session` / `app` / `client`:** `test_db` fixture
   - `CREATE DATABASE colony_test_<worker>_<uuid> TEMPLATE colony_test_template_<worker>` (file-level clone, fast).
   - Sets `DATABASE_URL` for the test's duration via `monkeypatch`.
   - Resets `colony_manager.db`'s lazy bindings so the next session bind picks up the new URL.
   - Yields.
   - Disposes engines, drops the DB.
3. **Session end:** template DB unmarked + dropped (unless `TEST_KEEP_DBS=1`).

## Writing integration tests

```python
def test_animal_terminate(db_session):
    from colony_manager.models import Animal, Cage, Species
    from sqlalchemy import select

    species = Species(name='Mouse')
    db_session.add(species)
    db_session.commit()

    # ... build cage + animal, call animal.terminate(...), assert state
    assert db_session.scalar(
        select(Animal).where(Animal.id == animal.id)
    ).termination_date is not None
```

For GUI tests:

```python
def test_list_cages_smoke(client):
    response = client.get('/cages/')
    assert response.status_code in (200, 302)  # 302 if auth redirects
```

The code style is **SQLAlchemy 2.0**: use `select(...)`, `session.execute(...)`, `session.scalars(...)`. **Do not** use `Model.query` in tests — it's being phased out everywhere.

## Troubleshooting

**`permission denied to create database`**
Your role lacks `CREATEDB`. Re-run the `CREATE ROLE ... CREATEDB` statement above, or `ALTER ROLE colony_test CREATEDB`.

**`database "colony_test_..." is being accessed by other users`**
A previous test crashed without disposing its engine pool. The fixture's `_force_drop` should handle this via `pg_terminate_backend`, but if it didn't, manually:

```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname LIKE 'colony_test_%' AND pid <> pg_backend_pid();
```

**Orphaned test DBs after a hard crash**

```sql
SELECT datname FROM pg_database WHERE datname LIKE 'colony_test_%';
-- Drop them one by one, or:
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT datname FROM pg_database WHERE datname LIKE 'colony_test_%' LOOP
        EXECUTE format('ALTER DATABASE %I WITH is_template = false', r.datname);
        EXECUTE format('DROP DATABASE %I', r.datname);
    END LOOP;
END $$;
```

**`alembic.util.exc.CommandError: Can't locate revision identified by '...'`**
The template was built from an older codebase. Drop the template (`DROP DATABASE colony_test_template_master`) — the next test run rebuilds it from the current migrations.

**Tests pass serially but fail under `-n auto`**
Almost always means a test is touching shared state (env vars, the filesystem, a module-level cache). The DB itself is per-test-isolated, so the leak is elsewhere. Check for `os.environ[...]` mutations without `monkeypatch`, or fixtures that reach into `colony_manager.db._engine` directly.

**Want to inspect a failing test's DB**

Windows `cmd.exe`:

```cmd
set TEST_KEEP_DBS=1
pytest tests\test_X.py::test_Y -x
:: Then look up the DB name from pytest output and:
psql -d colony_test_master_abc12345
set TEST_KEEP_DBS=
```

bash/zsh:

```sh
TEST_KEEP_DBS=1 pytest tests/test_X.py::test_Y -x
psql -d colony_test_master_abc12345
```

Remember to drop it manually when you're done (see "Orphaned test DBs").

## CI notes

For GitHub Actions, spin up a Postgres service container:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: colony_test
          POSTGRES_PASSWORD: testing
          POSTGRES_DB: postgres
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      TEST_DATABASE_URL: postgresql+psycopg2://colony_test:testing@localhost:5432
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.13' }
      - run: pip install -e '.[gui,test]' pytest-xdist
      - run: |
          psql "$TEST_DATABASE_URL/postgres" -c "ALTER ROLE colony_test CREATEDB;"
      - run: pytest -n auto
```

Postgres official images create the `POSTGRES_USER` role as a superuser, so `CREATEDB` is already implied — the `ALTER ROLE` step is belt-and-suspenders for non-official images.
