"""Analysis Scoreboard: attribution persistence + aggregation + route.

Covers the pieces added for the scoreboard feature:

* ``sync.apply_rating_status`` persisting the new ``analyzed_by`` /
  ``analyzed_at`` columns from a description class's ``get_rating_status``
  (and clearing them when the analysis reports no attribution).
* the ``services/data_queries.py`` rollups (completion, by-analyst, recent).
* the ``/analysis-scoreboard`` route rendering.

Uses the same ``tests._description_fakes`` registry as the sync tests; the
``fake_analyzed`` description encodes analyst + date in the filename so the
rating job is deterministic and never touches disk.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from colony_manager.datatypes import reset_registry_cache
from colony_manager.models import AnimalData

from .factories import make_animal_data_type, make_data_location


@pytest.fixture(autouse=True)
def description_registry(monkeypatch):
    """Point the description-class registry at ``tests._description_fakes``."""
    monkeypatch.setenv(
        'COLONY_MANAGER_DESCRIPTION_REGISTRY', 'tests._description_fakes',
    )
    reset_registry_cache()
    yield
    reset_registry_cache()


def _make_ratable_type(session, name=None):
    dtype = make_animal_data_type(session, name=name)
    dtype.description_class = 'fake_analyzed'
    session.commit()
    return dtype


def _row(session, dtype, loc, rel, *, is_rated=None, rating_note=None,
         analyzed_by=None, analyzed_at=None):
    r = AnimalData(
        datatype_id=dtype.id, location_id=loc.id, target_type='animal',
        relative_path=rel, name=rel, is_rated=is_rated, rating_note=rating_note,
        analyzed_by=analyzed_by, analyzed_at=analyzed_at,
    )
    session.add(r)
    session.commit()
    return r


# ---------------------------------------------------------------------------
# Persistence: apply_rating_status -> analyzed_by / analyzed_at
# ---------------------------------------------------------------------------

def test_sync_rating_persists_analyzed_by_and_at(db_session, app):
    """A description reporting analyst + timestamp lands in the new columns;
    a file with no attribution leaves both NULL."""
    from colony_manager_gui.sync import sync_rating_status
    from colony_manager_gui import db as gui_db

    dtype = _make_ratable_type(db_session)
    loc = make_data_location(db_session, datatype=dtype, base_path='/tmp/analyzed')

    analyzed = _row(db_session, dtype, loc, 'M-001__by-Sean-Brad__on-2026-09-01.txt')
    bare = _row(db_session, dtype, loc, 'M-002.txt')

    with app.app_context():
        sync_rating_status()
        gui_db.session.commit()

    db_session.refresh(analyzed)
    db_session.refresh(bare)

    assert analyzed.is_rated is True
    assert analyzed.analyzed_by == ['Brad', 'Sean']          # stored sorted
    assert analyzed.analyzed_at == datetime(2026, 9, 1, 0, 0)

    assert bare.is_rated is False
    assert bare.analyzed_by is None
    assert bare.analyzed_at is None


def test_sync_rating_clears_stale_attribution(db_session, app):
    """A row whose description no longer reports attribution has its
    analyzed_by/at cleared rather than keeping a stale value."""
    from colony_manager_gui.sync import sync_rating_status
    from colony_manager_gui import db as gui_db

    dtype = _make_ratable_type(db_session)
    loc = make_data_location(db_session, datatype=dtype, base_path='/tmp/analyzed')
    # Pre-seed stale attribution on a file the fake reports as unanalyzed.
    row = _row(db_session, dtype, loc, 'M-003.txt',
               is_rated=True, analyzed_by=['Ghost'], analyzed_at=datetime(2020, 1, 1))

    with app.app_context():
        sync_rating_status()
        gui_db.session.commit()

    db_session.refresh(row)
    assert row.analyzed_by is None
    assert row.analyzed_at is None


# ---------------------------------------------------------------------------
# Aggregation service
# ---------------------------------------------------------------------------

def test_ratable_datatypes_only_returns_supported(db_session):
    from colony_manager_gui.services import data_queries

    ratable = _make_ratable_type(db_session, name='Ratable')
    plain = make_animal_data_type(db_session, name='Plain')  # no description_class

    result = data_queries.ratable_datatypes(db_session)
    ids = {dt.id for dt in result}
    assert ratable.id in ids
    assert plain.id not in ids


def test_scoreboard_summary_counts(db_session):
    from colony_manager_gui.services import data_queries

    dtype = _make_ratable_type(db_session)
    loc = make_data_location(db_session, datatype=dtype, base_path='/tmp/s')

    _row(db_session, dtype, loc, 'a.txt', is_rated=True)
    _row(db_session, dtype, loc, 'b.txt', is_rated=True)
    _row(db_session, dtype, loc, 'c.txt', is_rated=False, rating_note='Partial — no spiral for OHC1')
    _row(db_session, dtype, loc, 'd.txt', is_rated=False, rating_note='Not analyzed')
    _row(db_session, dtype, loc, 'e.txt', is_rated=None)

    (s,) = data_queries.scoreboard_summary(db_session, [dtype])
    assert s['total'] == 5
    assert s['analyzed'] == 2
    assert s['partial'] == 1
    assert s['not_started'] == 2      # 'd' (note, not partial) + 'e' (NULL)
    assert s['pct'] == 40             # 2 / 5


def test_scoreboard_summary_includes_empty_types(db_session):
    from colony_manager_gui.services import data_queries

    dtype = _make_ratable_type(db_session)
    (s,) = data_queries.scoreboard_summary(db_session, [dtype])
    assert s == {'datatype': dtype, 'total': 0, 'analyzed': 0,
                 'partial': 0, 'not_started': 0, 'pct': 0}


def test_scoreboard_by_analyst_rollup_and_window(db_session):
    from colony_manager_gui.services import data_queries

    dtype = _make_ratable_type(db_session)
    loc = make_data_location(db_session, datatype=dtype, base_path='/tmp/a')
    now = datetime.now()

    _row(db_session, dtype, loc, 'a.txt', is_rated=True,
         analyzed_by=['Brad', 'Sean'], analyzed_at=now - timedelta(days=2))
    _row(db_session, dtype, loc, 'b.txt', is_rated=True,
         analyzed_by=['Brad'], analyzed_at=now - timedelta(days=1))
    # Outside a 30-day window:
    _row(db_session, dtype, loc, 'c.txt', is_rated=True,
         analyzed_by=['Sean'], analyzed_at=now - timedelta(days=90))

    all_time = {p['user']: p for p in
                data_queries.scoreboard_by_analyst(db_session, [dtype])}
    assert all_time['Brad']['total'] == 2
    assert all_time['Sean']['total'] == 2
    assert all_time['Brad']['by_type'][dtype.name] == 2
    assert all_time['Brad']['last_active'] == now - timedelta(days=1)
    # Sorted most-work-first, then name.
    ordered = data_queries.scoreboard_by_analyst(db_session, [dtype])
    assert ordered[0]['user'] == 'Brad'

    windowed = {p['user']: p for p in data_queries.scoreboard_by_analyst(
        db_session, [dtype], since=now - timedelta(days=30))}
    assert windowed['Brad']['total'] == 2
    assert windowed['Sean']['total'] == 1     # the 90-day-old row is excluded


def test_recent_analyses_orders_and_windows(db_session):
    from colony_manager_gui.services import data_queries

    dtype = _make_ratable_type(db_session)
    loc = make_data_location(db_session, datatype=dtype, base_path='/tmp/r')
    now = datetime.now()

    _row(db_session, dtype, loc, 'old.txt', is_rated=True,
         analyzed_by=['Sean'], analyzed_at=now - timedelta(days=100))
    newest = _row(db_session, dtype, loc, 'new.txt', is_rated=True,
                  analyzed_by=['Brad'], analyzed_at=now - timedelta(days=1))
    # No analyzed_at -> excluded from the recent feed.
    _row(db_session, dtype, loc, 'none.txt', is_rated=True, analyzed_by=['Brad'])

    recent = data_queries.recent_analyses(db_session, [dtype])
    assert recent[0].id == newest.id
    assert all(r.analyzed_at is not None for r in recent)

    windowed = data_queries.recent_analyses(
        db_session, [dtype], since=now - timedelta(days=30))
    assert [r.id for r in windowed] == [newest.id]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

def test_scoreboard_route_renders(db_session, logged_in_client):
    dtype = _make_ratable_type(db_session, name='ABR IO')
    loc = make_data_location(db_session, datatype=dtype, base_path='/tmp/route')
    _row(db_session, dtype, loc, 'x.txt', is_rated=True,
         analyzed_by=['Brad'], analyzed_at=datetime.now())

    resp = logged_in_client.get('/animals/analysis-scoreboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Analysis Scoreboard' in body
    assert 'ABR IO' in body
    assert 'Brad' in body


def test_scoreboard_route_window_all(db_session, logged_in_client):
    resp = logged_in_client.get('/animals/analysis-scoreboard?window=all')
    assert resp.status_code == 200
