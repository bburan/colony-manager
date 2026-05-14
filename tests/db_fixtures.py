"""Postgres template-DB fixtures for the integration test suite.

How it works
------------
1. A session-scoped fixture (``template_db``) creates a fresh database
   named ``{prefix}_template_{worker}`` and runs ``alembic upgrade head``
   against it. With ``pytest-xdist`` each worker builds its own template
   because Postgres won't clone a template while another session holds
   it open.

2. A function-scoped fixture (``test_db``) clones the template into a
   throwaway DB (``{prefix}_{worker}_{uuid}``), points ``DATABASE_URL``
   at it, and tears it down afterwards.

3. ``db_session`` yields a ``colony_manager.db`` session bound to the
   per-test DB. ``app`` / ``client`` yield a Flask app + test client
   bound to the same DB.

Inputs (env vars only)
----------------------
- ``TEST_DATABASE_URL`` — cluster URL, no trailing DB name. Example:
  ``postgresql+psycopg2://colony_test:pw@localhost:5432``. The role
  must have ``CREATEDB``.
- ``TEST_DB_PREFIX`` — optional, defaults to ``colony_test``.
- ``TEST_KEEP_DBS`` — optional. If set, skip teardown so a failing
  test's DB can be inspected with ``psql``.

See ``tests/README.md`` for setup details.
"""
import os
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cluster_url():
    """Return the no-trailing-DB cluster URL."""
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip(
            'TEST_DATABASE_URL not set — skipping Postgres integration tests. '
            'See tests/README.md for setup instructions.',
            allow_module_level=False,
        )
    return url.rstrip('/')


def _admin_url():
    """Maintenance-DB URL used for CREATE/DROP DATABASE."""
    return f'{_cluster_url()}/postgres'


def _db_url(db_name):
    return f'{_cluster_url()}/{db_name}'


def _prefix():
    return os.environ.get('TEST_DB_PREFIX', 'colony_test')


def _worker_id():
    """Stable per-worker id (``master`` if not running under xdist)."""
    return os.environ.get('PYTEST_XDIST_WORKER', 'master')


@contextmanager
def _admin_connection():
    """AUTOCOMMIT connection to the maintenance DB.

    CREATE/DROP DATABASE can't run inside a transaction, so we force
    AUTOCOMMIT isolation. Caller is responsible for not nesting.
    """
    engine = create_engine(_admin_url(), isolation_level='AUTOCOMMIT')
    try:
        with engine.connect() as conn:
            yield conn
    finally:
        engine.dispose()


def _db_exists(conn, db_name):
    """Return True if ``db_name`` is in pg_database.

    Reading pg_database is allowed for any role; only mutating it
    requires superuser.
    """
    row = conn.execute(text(
        'SELECT 1 FROM pg_database WHERE datname = :n'
    ), {'n': db_name}).first()
    return row is not None


def _force_drop(conn, db_name):
    """Drop a database, killing any lingering sessions first.

    Tolerant of the DB not existing — useful for cleanup paths where
    we don't know the state. Unmarks template DBs first because Postgres
    refuses ``DROP DATABASE`` on rows where ``datistemplate = true``.
    """
    if not _db_exists(conn, db_name):
        return
    # Unset the template flag if it's set. ``ALTER DATABASE`` works for
    # the database owner (which a CREATEDB user is, having created it);
    # direct ``UPDATE pg_database`` would require superuser.
    conn.execute(text(
        f'ALTER DATABASE "{db_name}" WITH is_template = false'
    ))
    # Terminate every backend connected to ``db_name`` except this one.
    # Without this, ``DROP DATABASE`` fails with "database is being
    # accessed by other users" if a test crashed without disposing its
    # engine pool.
    conn.execute(text(
        'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
        'WHERE datname = :db AND pid <> pg_backend_pid()'
    ), {'db': db_name})
    conn.execute(text(f'DROP DATABASE "{db_name}"'))


def _alembic_upgrade(url):
    """Run ``alembic upgrade head`` against ``url`` programmatically.

    ``migrations/env.py`` reads ``DATABASE_URL`` from the environment,
    so we set it for the duration of the call and restore the prior
    value afterwards.
    """
    from alembic.config import Config
    from alembic import command

    # alembic.ini lives at the repo root.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(repo_root, 'alembic.ini'))

    prior = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = url
    try:
        command.upgrade(cfg, 'head')
    finally:
        if prior is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = prior


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def template_db():
    """Build the per-worker template DB. Yields the template's name.

    Scope: session — pytest-xdist runs session fixtures once per
    worker, which is what we want. Each worker owns its template so
    template clones don't fight for the exclusive lock Postgres takes
    during ``CREATE DATABASE ... TEMPLATE``.
    """
    name = f'{_prefix()}_template_{_worker_id()}'

    # Build (or rebuild) the template. ``_force_drop`` handles
    # unmarking a prior template before dropping it.
    with _admin_connection() as conn:
        _force_drop(conn, name)
        conn.execute(text(f'CREATE DATABASE "{name}"'))

    _alembic_upgrade(_db_url(name))

    # Mark as template so accidental writes raise; also a visual cue
    # in ``\l`` output that this DB is special.
    with _admin_connection() as conn:
        conn.execute(text(
            f'ALTER DATABASE "{name}" WITH is_template = true'
        ))

    yield name

    if os.environ.get('TEST_KEEP_DBS'):
        return
    with _admin_connection() as conn:
        _force_drop(conn, name)


@pytest.fixture
def test_db(template_db, monkeypatch):
    """Clone the template into a throwaway DB and point env at it.

    Yields the DB URL. Sets ``DATABASE_URL`` and ``SECRET_KEY`` (the
    latter so ``create_app()`` doesn't blow up). Resets
    ``colony_manager.db``'s lazy bindings before and after so engine
    pools never outlive their DB.
    """
    name = f'{_prefix()}_{_worker_id()}_{uuid.uuid4().hex[:8]}'
    url = _db_url(name)

    with _admin_connection() as conn:
        conn.execute(text(
            f'CREATE DATABASE "{name}" TEMPLATE "{template_db}"'
        ))

    # Make sure colony_manager.db starts from a clean slate. Without
    # this, a session-cached engine from a prior test would still be
    # bound to the previous DB.
    import colony_manager.db as cm_db
    cm_db.reset_bindings()

    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')

    yield url

    # Drop the cached engine before dropping the DB, otherwise
    # _force_drop has to terminate our own backend.
    cm_db.reset_bindings()

    if os.environ.get('TEST_KEEP_DBS'):
        return
    with _admin_connection() as conn:
        _force_drop(conn, name)


@pytest.fixture
def db_session(test_db):
    """A ``colony_manager.db`` session bound to the per-test DB.

    Use this for model-level tests that don't need a Flask app::

        def test_animal_terminate(db_session):
            cage = Cage(custom_id='C1', species_id=...)
            db_session.add(cage)
            db_session.commit()
            ...
    """
    import colony_manager.db as cm_db
    session = cm_db.get_session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        cm_db.get_session().remove()


@pytest.fixture
def app(test_db):
    """Flask app bound to the per-test DB.

    CSRF is disabled because tests POST forms directly without
    rendering the CSRF token; flip it back on per-test if you need
    to exercise CSRF specifically.
    """
    from colony_manager_gui import create_app
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    yield app


@pytest.fixture
def client(app):
    return app.test_client()
