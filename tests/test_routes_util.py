"""Unit coverage for the helpers in :mod:`colony_manager_gui.routes.util`.

Specifically the standalone replacements for the Flask-SQLAlchemy
sugar we dropped (``get_or_404``, ``paginate``). They run against the
unified ``colony_manager.db`` session, so an app context isn't
required — only ``DATABASE_URL``, supplied by the ``test_db`` fixture.
"""
from sqlalchemy import select
from werkzeug.exceptions import NotFound
import pytest

from colony_manager.models import Animal, Cage, Species, Source
from colony_manager_gui.routes.util import get_or_404, paginate, Pagination


# ---------------------------------------------------------------------------
# get_or_404
# ---------------------------------------------------------------------------

def test_get_or_404_returns_existing_row(db_session):
    species = Species(name='Mouse')
    db_session.add(species)
    db_session.commit()

    # ``get_or_404`` loads through the route-side scoped session, which
    # is deliberately separate from the test's ``db_session``, so the
    # returned instance is a different Python object backed by the same
    # DB row — identity check is by primary key, not ``is``.
    loaded = get_or_404(Species, species.id)
    assert loaded is not None
    assert loaded.id == species.id
    assert loaded.name == 'Mouse'


def test_get_or_404_aborts_404_for_missing_row(db_session):
    with pytest.raises(NotFound):
        get_or_404(Species, 999_999)


def test_get_or_404_description_is_passed_through(db_session):
    with pytest.raises(NotFound) as exc_info:
        get_or_404(Species, 999_999, description='custom not-found message')
    assert exc_info.value.description == 'custom not-found message'


# ---------------------------------------------------------------------------
# paginate
# ---------------------------------------------------------------------------

def _make_species_rows(session, n):
    for i in range(n):
        session.add(Species(name=f'Species {i:03d}'))
    session.commit()


def test_paginate_returns_first_page_and_total(db_session):
    _make_species_rows(db_session, 25)
    stmt = select(Species).order_by(Species.id)

    page1 = paginate(stmt, page=1, per_page=10)

    assert isinstance(page1, Pagination)
    assert page1.total == 25
    assert page1.pages == 3
    assert len(page1.items) == 10
    assert page1.page == 1
    assert page1.has_prev is False
    assert page1.has_next is True
    assert page1.prev_num is None
    assert page1.next_num == 2


def test_paginate_middle_and_last_page(db_session):
    _make_species_rows(db_session, 25)
    stmt = select(Species).order_by(Species.id)

    page2 = paginate(stmt, page=2, per_page=10)
    assert page2.has_prev is True
    assert page2.has_next is True
    assert len(page2.items) == 10

    page3 = paginate(stmt, page=3, per_page=10)
    assert page3.has_prev is True
    assert page3.has_next is False
    assert len(page3.items) == 5


def test_paginate_handles_empty_result(db_session):
    stmt = select(Species).where(Species.name == 'does-not-exist')
    result = paginate(stmt, page=1, per_page=10)

    assert result.total == 0
    assert result.pages == 0
    assert result.items == []
    assert result.has_prev is False
    assert result.has_next is False


def test_paginate_clamps_page_to_at_least_one(db_session):
    _make_species_rows(db_session, 5)
    stmt = select(Species).order_by(Species.id)

    result = paginate(stmt, page=0, per_page=10)
    assert result.page == 1


def test_pagination_iter_pages_inserts_gap_marker(db_session):
    p = Pagination(items=[], page=10, per_page=10, total=200)
    pages = list(p.iter_pages(left_edge=1, right_edge=1, left_current=1, right_current=1))
    # Expect: 1, None (gap), 9, 10, None (gap), 20
    assert pages[0] == 1
    assert pages[-1] == 20
    assert None in pages  # at least one gap marker


# ---------------------------------------------------------------------------
# Unified session — the whole point of the migration
# ---------------------------------------------------------------------------

def test_db_proxy_routes_through_unified_scoped_session(test_db):
    """The split-brain check: ``colony_manager_gui.db.session`` must
    resolve to the same scoped registry as ``colony_manager.db``, so
    routes, workers, and scripts all share one session lifecycle.

    Uses ``test_db`` rather than ``db_session`` because ``db_session``
    now creates a *separate* Session (see fixture docstring); the
    production session is the scoped registry.
    """
    from colony_manager_gui import db as gui_db
    from colony_manager.db import get_session

    # Both sides return the ``scoped_session`` registry itself — that's
    # what makes ``db.session.add(x)`` proxy through to the current
    # thread's underlying Session.
    assert gui_db.session is get_session()
    # And calling the registry hands back the same Session twice within
    # the thread (the scope guarantee).
    registry = get_session()
    assert registry() is registry()
