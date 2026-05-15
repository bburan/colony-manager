"""Smoke tests for the Postgres template-clone fixtures.

Verifies the end-to-end path: template build → per-test clone →
``DATABASE_URL`` rebind → ``colony_manager.db`` session works → Flask
app boots against the same DB. These tests don't cover any feature
— they exist purely to fail loudly if the test infrastructure breaks.
"""
from sqlalchemy import select


def test_db_session_round_trip(db_session):
    """Insert and read back a row using the colony_manager.db session.

    Exercises: template clone, lazy-bind to the per-test URL, SQLAlchemy
    2.0 ``select()`` against the cloned schema, transaction commit.
    """
    from colony_manager.models import Species

    species = Species(name='Smoke Test Species')
    db_session.add(species)
    db_session.commit()

    found = db_session.scalars(
        select(Species).where(Species.name == 'Smoke Test Species')
    ).one()
    assert found.id == species.id


def test_db_isolation_between_tests(db_session):
    """A fresh clone has no rows from prior tests.

    If ``test_db_session_round_trip`` runs first and leaks, this
    assertion fails. Order-independent because pytest reruns the
    fixture; ordering only matters as a sanity check.
    """
    from colony_manager.models import Species

    rows = db_session.scalars(select(Species)).all()
    assert rows == []


def test_sync_job_rq_job_id_column_round_trip(db_session):
    """The rq_job_id column added in migration b7c2a3f9e081 is writable
    and survives a fresh query. Belt-and-suspenders for the migration.
    """
    from colony_manager.models import SyncJob

    job = SyncJob(
        kind='sync', status='pending', rq_job_id='deadbeef-cafe-1234',
    )
    db_session.add(job)
    db_session.commit()
    job_id = job.id
    db_session.expire_all()

    refreshed = db_session.get(SyncJob, job_id)
    assert refreshed.rq_job_id == 'deadbeef-cafe-1234'


def test_flask_app_boots(client):
    """Flask app factory builds against the per-test DB without erroring.

    Hits the dashboard root. Unauthenticated requests redirect to the
    login page (``check_login`` in the app factory), so we expect a
    3xx — but the key assertion is "not 500": that would mean the app
    couldn't reach the DB or the schema is wrong.
    """
    response = client.get('/', follow_redirects=False)
    assert response.status_code < 500, (
        f'App boot returned {response.status_code}; body: '
        f'{response.get_data(as_text=True)[:500]}'
    )
