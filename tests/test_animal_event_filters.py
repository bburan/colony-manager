"""The animal page's Events filters: by event type (procedure) and by
data file type (DataType).

Assertions key on procedure / file names in the rendered page, which is
enough: the filters only decide which events and files are rendered.
"""
from datetime import date

from colony_manager.models import AnimalEventData

from .factories import (
    make_animal, make_animal_event_data_type, make_data_location, make_event,
    make_procedure, make_procedure_target, make_species,
)


def _attach_file(session, event, datatype, location, name):
    f = AnimalEventData(datatype_id=datatype.id, location_id=location.id,
                        relative_path=name, name=name)
    f.events = [event]
    session.add(f)
    session.commit()
    return f


def _setup(db_session, tmp_path):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='EF-1')
    target = make_procedure_target(db_session)
    exposure = make_procedure(db_session, name='Noise Exposure')
    loud = make_procedure(db_session, name='Loud Subtype', parent=exposure)
    surgery = make_procedure(db_session, name='Surgery Proc')
    ev_loud = make_event(db_session, animal=animal, procedure=loud,
                         procedure_target=target,
                         scheduled_date=date(2026, 1, 1),
                         completion_date=date(2026, 1, 1))
    ev_surgery = make_event(db_session, animal=animal, procedure=surgery,
                            procedure_target=target,
                            scheduled_date=date(2026, 2, 1),
                            completion_date=date(2026, 2, 1))
    abr = make_animal_event_data_type(db_session, name='ABR Type')
    dpoae = make_animal_event_data_type(db_session, name='DPOAE Type')
    abr_loc = make_data_location(db_session, datatype=abr, base_path=tmp_path)
    dp_loc = make_data_location(db_session, datatype=dpoae, base_path=tmp_path)
    _attach_file(db_session, ev_loud, abr, abr_loc, 'loud-abr.md')
    _attach_file(db_session, ev_loud, dpoae, dp_loc, 'loud-dpoae.md')
    _attach_file(db_session, ev_surgery, dpoae, dp_loc, 'surgery-dpoae.md')
    return animal, exposure, surgery, abr, dpoae


def test_filter_options_come_from_this_animal(logged_in_client, db_session, tmp_path):
    animal, *_ = _setup(db_session, tmp_path)
    make_procedure(db_session, name='Unused Procedure')

    body = logged_in_client.get(f'/animals/{animal.id}').get_data(as_text=True)
    # Parent of a used procedure is on offer; an unused procedure is not.
    assert 'Noise Exposure &gt; Loud Subtype' in body
    assert '>Noise Exposure</option>' in body
    assert 'Unused Procedure' not in body
    assert '>ABR Type</option>' in body


def test_filter_by_parent_procedure_includes_subtypes(logged_in_client, db_session, tmp_path):
    animal, exposure, *_ = _setup(db_session, tmp_path)

    body = logged_in_client.get(
        f'/animals/{animal.id}?event_procedure={exposure.id}').get_data(as_text=True)
    assert 'loud-abr.md' in body
    assert 'surgery-dpoae.md' not in body
    assert 'Showing 1 of 2 events.' in body


def test_filter_by_file_type_narrows_events_and_their_files(logged_in_client, db_session, tmp_path):
    animal, _, _, abr, _ = _setup(db_session, tmp_path)

    body = logged_in_client.get(
        f'/animals/{animal.id}?event_datatype={abr.id}').get_data(as_text=True)
    assert 'loud-abr.md' in body
    # Same event, other type: hidden.
    assert 'loud-dpoae.md' not in body
    # Event with no file of this type: hidden.
    assert 'surgery-dpoae.md' not in body


def test_filters_combine(logged_in_client, db_session, tmp_path):
    animal, _, surgery, abr, _ = _setup(db_session, tmp_path)

    body = logged_in_client.get(
        f'/animals/{animal.id}?event_procedure={surgery.id}&event_datatype={abr.id}'
    ).get_data(as_text=True)
    assert 'Showing 0 of 2 events.' in body


def test_unknown_filter_value_shows_everything(logged_in_client, db_session, tmp_path):
    animal, *_ = _setup(db_session, tmp_path)

    body = logged_in_client.get(
        f'/animals/{animal.id}?event_procedure=999999&event_datatype=bogus'
    ).get_data(as_text=True)
    assert 'loud-abr.md' in body
    assert 'surgery-dpoae.md' in body
    assert 'event-filter-summary' not in body
