"""Smoke + targeted coverage for the ``animals`` blueprint.

By far the largest route file (~56 Model.query / db.session.query
sites). Tests cluster into list/filter, detail-view, CRUD,
event/log nesting, modals, and the unmatched-data + reassign flows.

Where a route's success path requires a lot of fixture setup, we test
the 404 / no-op path instead — that still exercises the get_or_404
conversion. The dashboard's eager-loading paths for ``view_animal``
get their own coverage via a seeded animal with at least one event.
"""
from datetime import date, timedelta

from sqlalchemy import select

from colony_manager.enums import DataStatus
from colony_manager.models import (
    Animal, AnimalEvent, AnimalEventData, Data, DataLocation, FeedLog,
    WeightLog,
)

from .factories import (
    make_animal, make_animal_event_data_type, make_breeding_pair,
    make_cage, make_data_location, make_event, make_feed, make_feed_log,
    make_procedure, make_procedure_target, make_species,
    make_termination_reason, make_weight_log,
)


# ---------------------------------------------------------------------------
# List + filters
# ---------------------------------------------------------------------------

def test_list_animals_with_seeded(logged_in_client, db_session):
    species = make_species(db_session)
    make_animal(db_session, species=species, custom_id='LST-1')
    response = logged_in_client.get('/animals/')
    assert response.status_code == 200
    assert b'LST-1' in response.data


def test_list_animals_target_age_column(logged_in_client, db_session):
    species = make_species(db_session)
    dob = date.today()
    make_animal(db_session, species=species, custom_id='TGT-1', dob=dob)
    expected = (dob + timedelta(days=56)).strftime('%Y-%m-%d').encode()
    response = logged_in_client.get(
        '/animals/?target_age=8w&status_filter=all')
    assert response.status_code == 200
    assert b'Date of target age' in response.data
    assert expected in response.data


def test_list_animals_target_age_missing_unit_errors(logged_in_client, db_session):
    species = make_species(db_session)
    make_animal(db_session, species=species, custom_id='TGT-ERR',
                dob=date.today())
    response = logged_in_client.get('/animals/?target_age=8&status_filter=all')
    assert response.status_code == 200
    assert b'Include a unit' in response.data
    assert b'Date of target age' not in response.data


def test_list_animals_target_age_blank_for_terminated(logged_in_client, db_session):
    species = make_species(db_session)
    dob = date.today()
    animal = make_animal(db_session, species=species, custom_id='TGT-DEAD', dob=dob)
    animal.terminate(termination_date=date.today())
    db_session.commit()
    would_be = (dob + timedelta(days=56)).strftime('%Y-%m-%d').encode()
    response = logged_in_client.get(
        '/animals/?target_age=8w&status_filter=all')
    assert response.status_code == 200
    # Column is present but the terminated animal shows no projected date.
    assert b'Date of target age' in response.data
    assert would_be not in response.data


def test_list_animals_target_age_past_not_shown(logged_in_client, db_session):
    species = make_species(db_session)
    dob = date.today() - timedelta(days=400)
    make_animal(db_session, species=species, custom_id='TGT-PAST', dob=dob)
    already = (dob + timedelta(days=56)).strftime('%Y-%m-%d').encode()
    response = logged_in_client.get(
        '/animals/?target_age=8w&status_filter=all')
    assert response.status_code == 200
    # Column shows, but a target age already in the past is not rendered.
    assert b'Date of target age' in response.data
    assert already not in response.data


def test_list_animals_blank_target_age_hides_column(logged_in_client, db_session):
    species = make_species(db_session)
    make_animal(db_session, species=species, custom_id='TGT-2', dob=date.today())
    response = logged_in_client.get('/animals/?status_filter=all')
    assert response.status_code == 200
    assert b'Date of target age' not in response.data


def test_list_animals_terminated_age_shows_euthanasia_indicator(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='EUTH-1',
                         dob=date.today() - timedelta(days=100))
    animal.terminate(termination_date=date.today() - timedelta(days=30))
    db_session.commit()
    response = logged_in_client.get('/animals/?status_filter=all')
    assert response.status_code == 200
    # Age at euthanasia (70 days), flagged with the (t) indicator.
    # Default age unit is days (navbar/session-driven, unset in tests).
    assert b'70.0 days (t)' in response.data


def test_list_animals_search_filter(logged_in_client, db_session):
    species = make_species(db_session)
    make_animal(db_session, species=species, custom_id='FIND-ME')
    make_animal(db_session, species=species, custom_id='OTHER-1')
    response = logged_in_client.get('/animals/?search_query=FIND')
    assert response.status_code == 200
    assert b'FIND-ME' in response.data
    assert b'OTHER-1' not in response.data


def test_list_animals_status_terminated_filter(logged_in_client, db_session):
    species = make_species(db_session)
    active = make_animal(db_session, species=species, custom_id='ACTIVE-A')
    term = make_animal(db_session, species=species, custom_id='TERM-A')
    term.terminate(termination_date=date.today())
    db_session.commit()

    response = logged_in_client.get('/animals/?status_filter=terminated')
    assert response.status_code == 200
    assert b'TERM-A' in response.data
    assert b'ACTIVE-A' not in response.data


def test_list_animals_sex_filter(logged_in_client, db_session):
    species = make_species(db_session)
    make_animal(db_session, species=species, custom_id='M-X', sex='male')
    make_animal(db_session, species=species, custom_id='F-X', sex='female')
    response = logged_in_client.get('/animals/?sex_filter=male')
    assert response.status_code == 200
    assert b'M-X' in response.data
    assert b'F-X' not in response.data


def test_list_animals_study_filter(logged_in_client, db_session):
    """``?study_filter=<id>`` narrows the list to animals enrolled in
    that study — the dropdown wired into animals.html alongside the
    existing tag / procedure / event-tag filters.
    """
    from colony_manager.models import Study

    species = make_species(db_session)
    enrolled = make_animal(db_session, species=species, custom_id='ENR-1')
    make_animal(db_session, species=species, custom_id='SKIP-1')

    target_study = Study(name='Target')
    other_study = Study(name='Other')
    db_session.add_all([target_study, other_study])
    db_session.commit()
    target_study.animals.append(enrolled)
    db_session.commit()

    response = logged_in_client.get(
        f'/animals/?study_filter={target_study.id}'
    )
    assert response.status_code == 200
    assert b'ENR-1' in response.data
    assert b'SKIP-1' not in response.data


def test_list_animals_event_filter_has_events(logged_in_client, db_session):
    """Exercises Animal.events.any() — runs through the refactored .where chain."""
    species = make_species(db_session)
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    with_events = make_animal(db_session, species=species, custom_id='WE-1')
    make_event(db_session, animal=with_events, procedure=procedure,
               procedure_target=target)
    make_animal(db_session, species=species, custom_id='NE-1')

    response = logged_in_client.get('/animals/?event_filter=has_events')
    assert response.status_code == 200
    assert b'WE-1' in response.data
    assert b'NE-1' not in response.data


def test_list_animals_sort_by_event_date(logged_in_client, db_session):
    """Exercises the last_event_subq outerjoin + nulls-last sort path."""
    species = make_species(db_session)
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    recent = make_animal(db_session, species=species, custom_id='REC-1')
    make_event(db_session, animal=recent, procedure=procedure,
               procedure_target=target,
               scheduled_date=date.today() - timedelta(days=5),
               completion_date=date.today() - timedelta(days=5))
    make_animal(db_session, species=species, custom_id='NEV-1')  # never had events

    response = logged_in_client.get('/animals/?sort_by=event_date&sort_dir=desc')
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Detail view (eager loads + bulk-load helpers)
# ---------------------------------------------------------------------------

def test_view_animal_returns_200(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='VW-1')
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    make_event(db_session, animal=animal, procedure=procedure,
               procedure_target=target)
    response = logged_in_client.get(f'/animals/{animal.id}')
    assert response.status_code == 200
    assert b'VW-1' in response.data


def test_view_animal_returns_404_for_unknown(logged_in_client):
    response = logged_in_client.get('/animals/99999')
    assert response.status_code == 404


def test_view_animal_events_default_to_most_recent_first(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='VW-SORT-1')
    target = make_procedure_target(db_session)
    older = make_procedure(db_session, name='Older Procedure')
    newer = make_procedure(db_session, name='Newer Procedure')
    make_event(db_session, animal=animal, procedure=older, procedure_target=target,
               scheduled_date=date.today() - timedelta(days=10),
               completion_date=date.today() - timedelta(days=10))
    make_event(db_session, animal=animal, procedure=newer, procedure_target=target,
               scheduled_date=date.today() - timedelta(days=1),
               completion_date=date.today() - timedelta(days=1))

    response = logged_in_client.get(f'/animals/{animal.id}')
    assert response.status_code == 200
    body = response.data.decode()
    assert body.index('Newer Procedure') < body.index('Older Procedure')


def test_view_animal_events_respect_ascending_session_pref(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='VW-SORT-2')
    target = make_procedure_target(db_session)
    older = make_procedure(db_session, name='Older Procedure')
    newer = make_procedure(db_session, name='Newer Procedure')
    make_event(db_session, animal=animal, procedure=older, procedure_target=target,
               scheduled_date=date.today() - timedelta(days=10),
               completion_date=date.today() - timedelta(days=10))
    make_event(db_session, animal=animal, procedure=newer, procedure_target=target,
               scheduled_date=date.today() - timedelta(days=1),
               completion_date=date.today() - timedelta(days=1))

    logged_in_client.post('/set-event-sort-dir/asc', follow_redirects=False)
    response = logged_in_client.get(f'/animals/{animal.id}')
    assert response.status_code == 200
    body = response.data.decode()
    assert body.index('Older Procedure') < body.index('Newer Procedure')


def test_set_event_sort_dir_writes_session(logged_in_client):
    response = logged_in_client.post('/set-event-sort-dir/asc', follow_redirects=False)
    assert response.status_code == 302
    with logged_in_client.session_transaction() as sess:
        assert sess.get('event_sort_dir') == 'asc'


def test_set_event_sort_dir_rejects_invalid_direction(logged_in_client):
    response = logged_in_client.post('/set-event-sort-dir/sideways', follow_redirects=False)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Create / update / delete / terminate
# ---------------------------------------------------------------------------

def test_create_animal(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    response = logged_in_client.post('/animals/create', data={
        'custom_id': 'NEW-1',
        'cage': str(cage.id),
        'species': str(species.id),
        'sex': 'male',
        'dob': date.today().isoformat(),
    }, follow_redirects=False)
    assert response.status_code == 302
    db_session.expire_all()
    persisted = db_session.scalars(
        select(Animal).where(Animal.custom_id == 'NEW-1')
    ).one()
    assert persisted.sex == 'male'


def test_update_animal_returns_404_for_unknown(logged_in_client):
    response = logged_in_client.post(
        '/animals/99999/update',
        data={'custom_id': 'x'},
    )
    assert response.status_code == 404


def test_delete_animal(logged_in_client, db_session):
    # Deletable = no ID and no events (an accidental add).
    animal = make_animal(db_session)
    animal.custom_id = None
    db_session.commit()
    animal_id = animal.id
    response = logged_in_client.post(
        f'/animals/{animal_id}/delete', follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    assert db_session.get(Animal, animal_id) is None


def test_delete_animal_with_custom_id_refused(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='HAS-ID')
    animal_id = animal.id
    response = logged_in_client.post(
        f'/animals/{animal_id}/delete', follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    assert db_session.get(Animal, animal_id) is not None


def test_delete_animal_with_events_refused(logged_in_client, db_session):
    animal = make_animal(db_session)
    animal.custom_id = None
    db_session.commit()
    make_event(db_session, animal=animal)
    animal_id = animal.id
    response = logged_in_client.post(
        f'/animals/{animal_id}/delete', follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    assert db_session.get(Animal, animal_id) is not None


def test_delete_animal_in_breeding_pair_refused(logged_in_client, db_session):
    """The route reads animal.breeding_pair_male / breeding_pair_female
    (backrefs added in BreedingPair) to refuse deletion of sires/dams even
    when the animal has no ID or events of its own.
    """
    pair = make_breeding_pair(db_session)
    male = db_session.get(Animal, pair.male_animal_id)
    male.custom_id = None  # isolate the breeding-pair guard
    db_session.commit()
    male_id = male.id
    response = logged_in_client.post(
        f'/animals/{male_id}/delete', follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    assert db_session.get(Animal, male_id) is not None


def test_terminate_animal_via_route(logged_in_client, db_session):
    species = make_species(db_session)
    reason = make_termination_reason(db_session)
    animal = make_animal(db_session, species=species, custom_id='TR-1')
    response = logged_in_client.post(
        f'/animals/{animal.id}/terminate',
        data={
            'termination_date': date.today().isoformat(),
            'termination_reason': str(reason.id),
            'ears_extracted': 'None',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    refreshed = db_session.get(Animal, animal.id)
    assert refreshed.terminated is True
    assert refreshed.termination_date == date.today()


def test_terminate_animal_without_date_via_route(logged_in_client, db_session):
    """Submitting the termination form with no date still marks the animal
    as terminated — supports historical data with unknown termination dates.
    """
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='TR-2')
    response = logged_in_client.post(
        f'/animals/{animal.id}/terminate',
        data={
            'termination_date': '',   # deliberately empty
            'ears_extracted': 'None',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    refreshed = db_session.get(Animal, animal.id)
    assert refreshed.terminated is True
    assert refreshed.termination_date is None


def test_unterminate_animal_via_edit_form(logged_in_client, db_session):
    """Unchecking 'Terminated' in the edit-animal form re-activates the
    animal and clears its termination_date/reason.

    Regression: before the terminated flag was added, clearing
    termination_date was enough to un-terminate.  Now that is_active is
    derived from the boolean flag, the flag must be cleared too — and,
    since an active animal with a termination date on record is
    confusing, the date/reason are cleared along with it.
    """
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    reason = make_termination_reason(db_session)
    animal = make_animal(db_session, species=species, custom_id='UT-1')
    animal.terminate(termination_date=date.today(), termination_reason=reason)
    db_session.commit()
    assert animal.is_active is False

    # POST the edit form without the 'terminated' checkbox — an unchecked
    # BooleanField is not included in the POST body, so WTForms sets it False.
    # 'termination_date'/'termination_reason' are also omitted here, but a
    # real browser would resubmit their pre-filled values unchanged — either
    # way populate_obj() clears them once 'terminated' is False.
    response = logged_in_client.post(
        f'/animals/{animal.id}/update',
        data={
            'cage': str(cage.id),
            'species': str(species.id),
            'sex': animal.sex,
            'dob': animal.dob.isoformat(),
            # 'terminated' omitted — checkbox unchecked
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    refreshed = db_session.get(Animal, animal.id)
    assert refreshed.terminated is False
    assert refreshed.is_active is True
    assert refreshed.termination_date is None
    assert refreshed.termination_reason_id is None


def test_unterminate_animal_via_edit_form_resubmitting_unchanged_date(
    logged_in_client, db_session,
):
    """Same as test_unterminate_animal_via_edit_form, but the POST includes
    the animal's existing (unchanged) termination_date/reason explicitly —
    what a real browser actually sends for pre-filled fields the user never
    touched, rather than omitting the keys outright. Must not be mistaken
    for a new/edited date and rejected by validate_terminated.
    """
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    reason = make_termination_reason(db_session)
    animal = make_animal(db_session, species=species, custom_id='UT-2')
    animal.terminate(termination_date=date.today(), termination_reason=reason)
    db_session.commit()

    response = logged_in_client.post(
        f'/animals/{animal.id}/update',
        data={
            'cage': str(cage.id),
            'species': str(species.id),
            'sex': animal.sex,
            'dob': animal.dob.isoformat(),
            'termination_date': date.today().isoformat(),
            'termination_reason': str(reason.id),
            # 'terminated' omitted — checkbox unchecked
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    refreshed = db_session.get(Animal, animal.id)
    assert refreshed.terminated is False
    assert refreshed.termination_date is None
    assert refreshed.termination_reason_id is None


def test_update_animal_rejects_termination_date_without_flag(logged_in_client, db_session):
    """A termination_date/reason submitted without the 'Terminated' checkbox
    is rejected rather than silently persisted.

    app.js normally auto-checks the box client-side when a date/reason is
    entered, but the server can't rely on JS having run (disabled JS, a
    raw POST, etc), so this must also be enforced server-side.
    """
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    animal = make_animal(db_session, species=species, cage=cage, custom_id='NT-1')

    response = logged_in_client.post(
        f'/animals/{animal.id}/update',
        data={
            'cage': str(cage.id),
            'species': str(species.id),
            'sex': animal.sex,
            'dob': animal.dob.isoformat(),
            'termination_date': date.today().isoformat(),
            # 'terminated' omitted — checkbox unchecked
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    refreshed = db_session.get(Animal, animal.id)
    assert refreshed.terminated is False
    assert refreshed.termination_date is None


def test_update_animal_rejects_termination_reason_without_flag(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    animal = make_animal(db_session, species=species, cage=cage, custom_id='NT-2')
    reason = make_termination_reason(db_session)

    response = logged_in_client.post(
        f'/animals/{animal.id}/update',
        data={
            'cage': str(cage.id),
            'species': str(species.id),
            'sex': animal.sex,
            'dob': animal.dob.isoformat(),
            'termination_reason': str(reason.id),
            # 'terminated' omitted — checkbox unchecked
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    refreshed = db_session.get(Animal, animal.id)
    assert refreshed.terminated is False
    assert refreshed.termination_reason_id is None


def test_update_animal_allows_termination_date_with_flag(logged_in_client, db_session):
    """Sanity check: the guard doesn't block the legitimate case of
    checking 'Terminated' and setting a date/reason in the same edit.
    """
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    animal = make_animal(db_session, species=species, cage=cage, custom_id='NT-3')
    reason = make_termination_reason(db_session)

    response = logged_in_client.post(
        f'/animals/{animal.id}/update',
        data={
            'cage': str(cage.id),
            'species': str(species.id),
            'sex': animal.sex,
            'dob': animal.dob.isoformat(),
            'terminated': 'y',
            'termination_date': date.today().isoformat(),
            'termination_reason': str(reason.id),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    refreshed = db_session.get(Animal, animal.id)
    assert refreshed.terminated is True
    assert refreshed.termination_date == date.today()
    assert refreshed.termination_reason_id == reason.id


# ---------------------------------------------------------------------------
# Animal events nested routes
# ---------------------------------------------------------------------------

def test_create_animal_event(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='AE-CR')
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    response = logged_in_client.post(
        f'/animals/{animal.id}/events/create',
        data={
            'procedure': str(procedure.id),
            'procedure_target': str(target.id),
            'side': '',
            'date': date.today().isoformat(),
            'action': 'completed',
            'notes': '',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    events = db_session.scalars(
        select(AnimalEvent).where(AnimalEvent.animal_id == animal.id)
    ).all()
    assert len(events) == 1


def test_delete_animal_event(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species)
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    event = make_event(db_session, animal=animal, procedure=procedure,
                       procedure_target=target)
    event_id = event.id

    response = logged_in_client.post(
        f'/animals/events/{event_id}/delete', follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    assert db_session.get(AnimalEvent, event_id) is None


def test_update_animal_event_returns_404_for_unknown(logged_in_client):
    response = logged_in_client.post('/animals/events/99999/update', data={})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Daily logs (weight + feed)
# ---------------------------------------------------------------------------

def test_delete_animal_daily_log_removes_weight_and_feeds(
    logged_in_client, db_session,
):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species)
    feed = make_feed(db_session)
    today = date.today()
    make_weight_log(db_session, animal=animal, date=today, weight=20.0)
    make_feed_log(db_session, animal=animal, feed=feed, date=today, quantity=3)

    response = logged_in_client.post(
        f'/animals/{animal.id}/{today.isoformat()}/weight-feed/delete',
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    weights = db_session.scalars(
        select(WeightLog).where(WeightLog.animal_id == animal.id)
    ).all()
    feeds = db_session.scalars(
        select(FeedLog).where(FeedLog.animal_id == animal.id)
    ).all()
    assert weights == []
    assert feeds == []


# ---------------------------------------------------------------------------
# Modals (exercise get_or_404 for animal / event / cage)
# ---------------------------------------------------------------------------

def test_edit_animal_modal(logged_in_client, db_session):
    animal = make_animal(db_session)
    response = logged_in_client.get(f'/animals/{animal.id}/edit_modal')
    assert response.status_code == 200


def test_edit_animal_modal_404(logged_in_client):
    response = logged_in_client.get('/animals/99999/edit_modal')
    assert response.status_code == 404


def test_assign_animal_id_modal(logged_in_client, db_session):
    animal = make_animal(db_session)
    response = logged_in_client.get(f'/animals/{animal.id}/assign_id_modal')
    assert response.status_code == 200


def test_edit_animal_note_modal(logged_in_client, db_session):
    animal = make_animal(db_session)
    response = logged_in_client.get(f'/animals/{animal.id}/edit_note_modal')
    assert response.status_code == 200


def test_terminate_animal_modal(logged_in_client, db_session):
    animal = make_animal(db_session)
    response = logged_in_client.get(f'/animals/{animal.id}/terminate_modal')
    assert response.status_code == 200


def test_quick_add_study_modal(logged_in_client, db_session):
    animal = make_animal(db_session)
    response = logged_in_client.get(
        f'/animals/{animal.id}/quick_add_study_modal'
    )
    assert response.status_code == 200


def test_create_animal_modal_for_cage(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    make_animal(db_session, cage=cage, species=species)  # cage needs an animal for dob/sex defaults
    response = logged_in_client.get(f'/animals/create_modal/{cage.id}')
    assert response.status_code == 200


def test_create_animal_event_modal(logged_in_client, db_session):
    animal = make_animal(db_session)
    response = logged_in_client.get(
        f'/animals/{animal.id}/events/create_modal'
    )
    assert response.status_code == 200


def test_edit_animal_event_modal(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species)
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    event = make_event(db_session, animal=animal, procedure=procedure,
                       procedure_target=target)
    response = logged_in_client.get(
        f'/animals/events/{event.id}/edit_modal'
    )
    assert response.status_code == 200


def test_delete_animal_event_modal(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species)
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    event = make_event(db_session, animal=animal, procedure=procedure,
                       procedure_target=target)
    response = logged_in_client.get(
        f'/animals/events/{event.id}/delete_modal'
    )
    assert response.status_code == 200


def test_create_daily_log_modal(logged_in_client, db_session):
    animal = make_animal(db_session)
    make_feed(db_session)  # need at least one feed type
    response = logged_in_client.get(
        f'/animals/{animal.id}/weight-feed/create_modal'
    )
    assert response.status_code == 200


def test_events_popover(logged_in_client, db_session):
    animal = make_animal(db_session)
    response = logged_in_client.get(
        f'/animals/{animal.id}/events_popover'
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Unmatched-data list (paginate path)
# ---------------------------------------------------------------------------

def test_list_unmatched_data_renders_on_empty_db(logged_in_client):
    """Exercises the union-all-of-subqueries path + paginate conversion."""
    response = logged_in_client.get('/animals/unmatched-data')
    assert response.status_code == 200


def test_list_unmatched_data_animal_event_filter(logged_in_client):
    response = logged_in_client.get(
        '/animals/unmatched-data?target_type=animal_event'
    )
    assert response.status_code == 200


def test_list_unmatched_data_missing_status_filter(logged_in_client):
    """``missing`` is one of the status options exposed by the dropdown."""
    response = logged_in_client.get(
        '/animals/unmatched-data?status=missing'
    )
    assert response.status_code == 200


def _make_unmatched_data_row(db_session, *, status=DataStatus.MISSING, name='f.txt'):
    """Helper: build the minimum DataType + DataLocation + AnimalEventData
    row needed to exercise the unmatched-data delete path.
    """
    dtype = make_animal_event_data_type(db_session)
    location = make_data_location(db_session, datatype=dtype, base_path='/tmp')
    row = AnimalEventData(
        datatype_id=dtype.id,
        location_id=location.id,
        relative_path=name,
        name=name,
        status=status,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_bulk_delete_unmatched_data(logged_in_client, db_session):
    row_a = _make_unmatched_data_row(db_session, name='a.txt')
    row_b = _make_unmatched_data_row(db_session, name='b.txt')
    a_id, b_id = row_a.id, row_b.id

    response = logged_in_client.post(
        '/animals/unmatched-data/delete',
        data={'data_ids': [str(a_id), str(b_id)]},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    assert db_session.get(Data, a_id) is None
    assert db_session.get(Data, b_id) is None


def test_bulk_delete_unmatched_data_empty_selection_no_op(
    logged_in_client, db_session,
):
    """Submitting with no ``data_ids`` should redirect with a warning, not 500."""
    response = logged_in_client.post(
        '/animals/unmatched-data/delete',
        data={},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_bulk_auto_create_unmatched_data_creates_events(
    logged_in_client, db_session,
):
    """Selected AnimalEventData rows with a candidate animal get a
    fresh AnimalEvent linked to them via the same auto-create flow
    the single-file 'wand' button uses.
    """
    from datetime import date
    from colony_manager.models import AnimalEventData, DataLocation

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='AC-1')
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    dtype = make_animal_event_data_type(
        db_session,
        default_procedure=procedure,
        default_procedure_target=target,
    )
    location = make_data_location(
        db_session, datatype=dtype, base_path='/tmp',
    )

    row = AnimalEventData(
        datatype_id=dtype.id,
        location_id=location.id,
        relative_path='AC-1_2025-12-10.txt',
        name='AC-1_2025-12-10.txt',
        status=DataStatus.UNREVIEWED,
        date=date(2025, 12, 10),
        # Populated by sync in real use; auto_create_animal_event's
        # siblings-linking step reads this to decide whether to
        # attach the file to the freshly-created event.
        parsed_metadata={'animal_id': 'AC-1', 'date': '2025-12-10'},
    )
    row.candidate_animals = [animal]
    db_session.add(row)
    db_session.commit()
    row_id = row.id

    response = logged_in_client.post(
        '/animals/unmatched-data/auto-create',
        data={'data_ids': [str(row_id)]},
        follow_redirects=False,
    )
    assert response.status_code == 302

    db_session.expire_all()
    persisted = db_session.get(AnimalEventData, row_id)
    assert len(persisted.events) == 1
    assert persisted.events[0].animal_id == animal.id
    assert persisted.events[0].procedure_id == procedure.id


def test_bulk_auto_create_empty_selection_no_op(logged_in_client):
    """Submitting with no checkboxes ticked redirects with a warning."""
    response = logged_in_client.post(
        '/animals/unmatched-data/auto-create',
        data={},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_bulk_auto_create_skips_files_without_candidates(
    logged_in_client, db_session,
):
    """A row with no candidate_animals is counted-skipped, not crashed."""
    from datetime import date
    from colony_manager.models import AnimalEventData

    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    location = make_data_location(db_session, datatype=dtype, base_path='/tmp')
    row = AnimalEventData(
        datatype_id=dtype.id,
        location_id=location.id,
        relative_path='orphan.txt',
        name='orphan.txt',
        status=DataStatus.UNREVIEWED,
        date=date(2025, 12, 10),
    )
    db_session.add(row)
    db_session.commit()
    row_id = row.id

    response = logged_in_client.post(
        '/animals/unmatched-data/auto-create',
        data={'data_ids': [str(row_id)]},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    persisted = db_session.get(AnimalEventData, row_id)
    assert persisted.events == []


def test_bulk_delete_skips_unknown_ids(logged_in_client, db_session):
    """Mixing real + unknown ids deletes only the real ones; no crash."""
    row = _make_unmatched_data_row(db_session, name='real.txt')
    row_id = row.id

    response = logged_in_client.post(
        '/animals/unmatched-data/delete',
        data={'data_ids': [str(row_id), '99999']},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    assert db_session.get(Data, row_id) is None


def test_unrated_data_state_filter(logged_in_client, db_session, monkeypatch):
    """The Status flag filters by unrated / partial / both."""
    from colony_manager.datatypes import reset_registry_cache
    from colony_manager.models import AnimalData
    from .factories import make_animal_data_type

    monkeypatch.setenv('COLONY_MANAGER_DESCRIPTION_REGISTRY', 'tests._description_fakes')
    reset_registry_cache()
    try:
        dtype = make_animal_data_type(db_session)
        dtype.description_class = 'fake_ratable'
        db_session.commit()
        loc = make_data_location(db_session, datatype=dtype, base_path='/tmp/state')

        def _row(rel, note):
            db_session.add(AnimalData(
                datatype_id=dtype.id, location_id=loc.id, target_type='animal',
                relative_path=rel, name=rel, is_rated=False, rating_note=note,
            ))

        _row('unrated_file.txt', 'Not analyzed')
        _row('null_note.txt', None)          # never scanned → unrated
        _row('partial_file.txt', 'Partial — no spiral for OHC1')
        db_session.commit()

        # Unrated: excludes the partial one; includes the NULL-note row.
        resp = logged_in_client.get('/animals/unrated-data?state=unrated')
        assert resp.status_code == 200
        assert b'unrated_file.txt' in resp.data
        assert b'null_note.txt' in resp.data
        assert b'partial_file.txt' not in resp.data

        # Partial: only the partial one.
        resp = logged_in_client.get('/animals/unrated-data?state=partial')
        assert b'partial_file.txt' in resp.data
        assert b'unrated_file.txt' not in resp.data
        assert b'null_note.txt' not in resp.data

        # Both (the default): everything not fully rated.
        resp = logged_in_client.get('/animals/unrated-data')
        assert b'unrated_file.txt' in resp.data
        assert b'partial_file.txt' in resp.data
        assert b'null_note.txt' in resp.data
    finally:
        reset_registry_cache()


def test_unrated_data_note_search_matches_all_terms(logged_in_client, db_session, monkeypatch):
    """Space-separated note terms are AND-ed as substrings of rating_note."""
    from colony_manager.datatypes import reset_registry_cache
    from colony_manager.models import AnimalData
    from .factories import make_animal_data_type

    monkeypatch.setenv('COLONY_MANAGER_DESCRIPTION_REGISTRY', 'tests._description_fakes')
    reset_registry_cache()
    try:
        dtype = make_animal_data_type(db_session)
        dtype.description_class = 'fake_ratable'
        db_session.commit()
        loc = make_data_location(db_session, datatype=dtype, base_path='/tmp/note')

        def _row(rel, note):
            db_session.add(AnimalData(
                datatype_id=dtype.id, location_id=loc.id, target_type='animal',
                relative_path=rel, name=rel, is_rated=False, rating_note=note,
            ))

        _row('multi.txt', 'Partial — no spiral for OHC1, OHC2, OHC3')
        _row('single.txt', 'Partial — no spiral for OHC1')
        _row('other.txt', 'Partial — no spiral for OHC3')
        _row('done.txt', 'Analyzed — IHC 33, OHC 33/33/32')
        db_session.commit()

        # "Partial OHC1" → both terms must appear; matches the two OHC1 notes.
        resp = logged_in_client.get(
            '/animals/unrated-data?state=both&note=Partial+OHC1'
        )
        assert resp.status_code == 200
        assert b'multi.txt' in resp.data
        assert b'single.txt' in resp.data
        assert b'other.txt' not in resp.data   # no OHC1
        assert b'done.txt' not in resp.data     # not Partial
    finally:
        reset_registry_cache()


def test_unrated_data_confocal_target_shows_full_display(logged_in_client, db_session, monkeypatch):
    """Confocal-image targets render their full_display, not an object repr."""
    from colony_manager.datatypes import reset_registry_cache
    from .factories import (
        make_animal, make_confocal_image, make_confocal_image_data,
        make_confocal_image_data_type, make_confocal_image_type, make_ear,
    )

    monkeypatch.setenv('COLONY_MANAGER_DESCRIPTION_REGISTRY', 'tests._description_fakes')
    reset_registry_cache()
    try:
        dtype = make_confocal_image_data_type(db_session)
        dtype.description_class = 'fake_ratable'
        db_session.commit()

        animal = make_animal(db_session, custom_id='CF-1')
        ear = make_ear(db_session, animal=animal, side='Left')
        image_type = make_confocal_image_type(db_session, name='IHC and OHC (counts)')
        image = make_confocal_image(db_session, ear=ear, image_type=image_type,
                                    frequency=11314.0)
        f = make_confocal_image_data(db_session, datatype=dtype,
                                     confocal_image=image)
        f.is_rated = False
        db_session.commit()

        resp = logged_in_client.get('/animals/unrated-data?state=unrated')
        assert resp.status_code == 200
        assert image.full_display.encode() in resp.data
        assert b'ConfocalImage object' not in resp.data
    finally:
        reset_registry_cache()


def test_refresh_data_rating_recomputes_single_row(logged_in_client, db_session, monkeypatch):
    """The per-row button recomputes just that row's rating status."""
    from colony_manager.datatypes import reset_registry_cache
    from colony_manager.models import AnimalData
    from .factories import make_animal_data_type

    monkeypatch.setenv('COLONY_MANAGER_DESCRIPTION_REGISTRY', 'tests._description_fakes')
    reset_registry_cache()
    try:
        dtype = make_animal_data_type(db_session)
        dtype.description_class = 'fake_ratable'
        db_session.commit()
        loc = make_data_location(db_session, datatype=dtype, base_path='/tmp/refresh')
        row = AnimalData(
            datatype_id=dtype.id, location_id=loc.id, target_type='animal',
            relative_path='M-001__raters-Sean-Brad.txt',
            name='M-001__raters-Sean-Brad.txt',
            is_rated=None, rating_note=None,
        )
        db_session.add(row)
        db_session.commit()
        rid = row.id

        # HTMX path returns the re-rendered row with the fresh status.
        resp = logged_in_client.post(
            f'/animals/data/{rid}/rating-refresh',
            headers={'HX-Request': 'true'},
        )
        assert resp.status_code == 200
        assert b'2 rater(s)' in resp.data
        db_session.refresh(row)
        assert row.is_rated is True
        assert row.raters == ['Brad', 'Sean']
        assert row.rater_count == 2

        # Non-HTMX falls back to a redirect.
        resp = logged_in_client.post(f'/animals/data/{rid}/rating-refresh')
        assert resp.status_code == 302
    finally:
        reset_registry_cache()
