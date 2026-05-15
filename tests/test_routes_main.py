"""Smoke + targeted coverage for the ``main`` blueprint.

23 Model.query sites across the dashboard, calendar, settings list,
and the settings CRUD routes. The dashboard itself is exercised by
the smoke baseline (`tests/test_routes_smoke.py`); this file targets
the settings sub-routes and the create-setting duplicate-check path.
"""
from sqlalchemy import select

from colony_manager.models import (
    AnimalEventDataType, DataType, Feed, Species, TerminationReason,
)


# ---------------------------------------------------------------------------
# Settings list
# ---------------------------------------------------------------------------

def test_list_settings_renders_with_seeded_data(logged_in_client, db_session):
    db_session.add(Species(name='SettingsTest-Species'))
    db_session.add(TerminationReason(name='SettingsTest-Reason'))
    db_session.commit()

    response = logged_in_client.get('/settings')
    assert response.status_code == 200
    assert b'SettingsTest-Species' in response.data
    assert b'SettingsTest-Reason' in response.data


# ---------------------------------------------------------------------------
# Settings CRUD (exercises Model.query duplicate-check and get_or_404)
# ---------------------------------------------------------------------------

def test_create_setting_persists_simple_row(logged_in_client, db_session):
    response = logged_in_client.post(
        '/settings/species/create',
        data={'name': 'CreatedSpecies'},
        follow_redirects=False,
    )
    # Either HTMX (non-3xx) or non-HTMX redirect; both are accepted.
    assert response.status_code in (200, 302)

    species = db_session.scalars(
        select(Species).where(Species.name == 'CreatedSpecies')
    ).first()
    assert species is not None


def test_create_setting_rejects_duplicate(logged_in_client, db_session):
    db_session.add(Species(name='DupSpecies'))
    db_session.commit()

    response = logged_in_client.post(
        '/settings/species/create',
        data={'name': 'DupSpecies'},
        follow_redirects=False,
    )
    # Refactored dupe-check path: route returns 400 via htmx_error or 302
    # redirect non-HTMX. Either way, only ONE Species should exist.
    assert response.status_code in (302, 400)
    rows = db_session.scalars(
        select(Species).where(Species.name == 'DupSpecies')
    ).all()
    assert len(rows) == 1


def test_update_setting_persists(logged_in_client, db_session):
    feed = Feed(name='OldFeed', weight=0.5)
    db_session.add(feed)
    db_session.commit()

    response = logged_in_client.post(
        f'/settings/feed/{feed.id}/update',
        data={'name': 'RenamedFeed', 'weight': '0.7'},
        follow_redirects=False,
    )
    assert response.status_code in (200, 302)
    db_session.refresh(feed)
    assert feed.name == 'RenamedFeed'


def test_update_setting_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.post(
        '/settings/species/99999/update',
        data={'name': 'Whatever'},
    )
    assert response.status_code == 404


def test_delete_setting(logged_in_client, db_session):
    species = Species(name='ToDelete')
    db_session.add(species)
    db_session.commit()
    sid = species.id

    response = logged_in_client.post(
        f'/settings/species/{sid}/delete',
        follow_redirects=False,
    )
    assert response.status_code in (200, 302)
    db_session.expire_all()  # invalidate cached identity map
    assert db_session.get(Species, sid) is None


def test_delete_setting_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.post('/settings/species/99999/delete')
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DataType modals + lifecycle
# ---------------------------------------------------------------------------

def test_create_datatype_modal_renders(logged_in_client):
    response = logged_in_client.get('/settings/datatype/create_modal')
    assert response.status_code == 200


def test_edit_datatype_modal_renders(logged_in_client, db_session):
    dt = AnimalEventDataType(name='DT-Edit')
    db_session.add(dt)
    db_session.commit()
    response = logged_in_client.get(
        f'/settings/datatype/{dt.id}/edit_modal'
    )
    assert response.status_code == 200


def test_edit_datatype_modal_returns_404_for_unknown(logged_in_client):
    response = logged_in_client.get('/settings/datatype/99999/edit_modal')
    assert response.status_code == 404


def test_delete_datatype_unlinked(logged_in_client, db_session):
    dt = AnimalEventDataType(name='DT-Del')
    db_session.add(dt)
    db_session.commit()
    dt_id = dt.id

    response = logged_in_client.post(
        f'/settings/datatype/{dt_id}/delete', follow_redirects=False,
    )
    assert response.status_code in (200, 302)
    db_session.expire_all()  # invalidate cached identity map
    assert db_session.get(DataType, dt_id) is None


# ---------------------------------------------------------------------------
# Species selection in session
# ---------------------------------------------------------------------------

def test_set_species_writes_session(app, logged_in_client, db_session):
    species = Species(name='SetSpec')
    db_session.add(species)
    db_session.commit()
    response = logged_in_client.post(
        f'/set-species/{species.id}',
        follow_redirects=False,
    )
    assert response.status_code == 302
    with logged_in_client.session_transaction() as sess:
        assert sess.get('selected_species') == str(species.id)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def test_calendar_renders_with_no_events(logged_in_client):
    """``view_calendar`` already in smoke; this also exercises the AnimalEvent
    .options(joinedload(...)).all() refactor under empty data.
    """
    response = logged_in_client.get('/calendar')
    assert response.status_code == 200
