"""Smoke + targeted coverage for the ``main`` blueprint.

23 Model.query sites across the dashboard, calendar, settings list,
and the settings CRUD routes. The dashboard itself is exercised by
the smoke baseline (`tests/test_routes_smoke.py`); this file targets
the settings sub-routes and the create-setting duplicate-check path.
"""
import json
import re
from datetime import date, timedelta

from sqlalchemy import select

from colony_manager.models import (
    Animal, AnimalEventDataType, DataType, Feed, Species, TerminationReason,
)
from .factories import make_animal, make_cage, make_event, make_procedure, make_species


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


def _parse_calendar_events(response):
    """Extract the calendar_events JSON array from the rendered calendar page."""
    html = response.data.decode()
    match = re.search(r'events:\s*(\[[\s\S]*?\]),\s*\n\s*eventDidMount', html)
    if not match:
        return []
    return json.loads(match.group(1))


def test_calendar_merges_consecutive_days_with_identical_animal_set(
    logged_in_client, db_session
):
    """Same procedure + same two animals on three consecutive days → one event."""
    proc = make_procedure(db_session, name='CalMerge-Proc')
    a1 = make_animal(db_session, custom_id='CalMerge-A1')
    a2 = make_animal(db_session, custom_id='CalMerge-A2')
    today = date.today()
    for animal in (a1, a2):
        for delta in range(3):
            make_event(db_session, animal=animal, procedure=proc,
                       completion_date=today + timedelta(days=delta))

    response = logged_in_client.get('/calendar')
    events = _parse_calendar_events(response)
    proc_events = [e for e in events if e['title'] == 'CalMerge-Proc']

    assert len(proc_events) == 1
    assert proc_events[0]['start'] == today.isoformat()
    assert proc_events[0]['end'] == (today + timedelta(days=3)).isoformat()


def test_calendar_does_not_merge_consecutive_days_with_different_animal_sets(
    logged_in_client, db_session
):
    """Same procedure but different animal each day → two separate events."""
    proc = make_procedure(db_session, name='CalNoMerge-Proc')
    a1 = make_animal(db_session, custom_id='CalNoMerge-A1')
    a2 = make_animal(db_session, custom_id='CalNoMerge-A2')
    today = date.today()
    make_event(db_session, animal=a1, procedure=proc, completion_date=today)
    make_event(db_session, animal=a2, procedure=proc,
               completion_date=today + timedelta(days=1))

    response = logged_in_client.get('/calendar')
    events = _parse_calendar_events(response)
    proc_events = [e for e in events if e['title'] == 'CalNoMerge-Proc']

    assert len(proc_events) == 2


def test_calendar_uses_procedure_display_name_for_nested_procedures(
    logged_in_client, db_session
):
    """A child procedure's title should show the full 'Parent > Child' hierarchy."""
    parent = make_procedure(db_session, name='CalHier-Parent')
    child = make_procedure(db_session, name='CalHier-Child', parent=parent)
    animal = make_animal(db_session, custom_id='CalHier-A1')
    make_event(db_session, animal=animal, procedure=child,
               completion_date=date.today())

    response = logged_in_client.get('/calendar')
    events = _parse_calendar_events(response)
    titles = [e['title'] for e in events]

    assert 'CalHier-Parent > CalHier-Child' in titles


def test_calendar_uses_fallback_label_for_animal_without_custom_id(
    logged_in_client, db_session
):
    """An animal with no custom_id should appear as 'Animal #<id>' in extendedProps."""
    proc = make_procedure(db_session, name='CalFallback-Proc')
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    animal = Animal(
        cage_id=cage.id, species_id=species.id,
        sex='male', dob=date.today(), custom_id=None,
    )
    db_session.add(animal)
    db_session.commit()
    make_event(db_session, animal=animal, procedure=proc,
               completion_date=date.today())

    response = logged_in_client.get('/calendar')
    events = _parse_calendar_events(response)
    proc_events = [e for e in events if e['title'] == 'CalFallback-Proc']

    assert len(proc_events) == 1
    animals = proc_events[0]['extendedProps']['animals']
    assert len(animals) == 1
    assert animals[0]['label'] == f'Animal #{animal.id}'
    assert animals[0]['id'] == animal.id
