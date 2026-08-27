"""Tests for the partial-match flag on ``Data``.

A multi-animal filename is only *fully* matched once every animal it names
has a linked target. ``unmatched_animal_ids`` lists the ones that don't
yet (drives the entity-page badge); ``has_unmatched_animals`` is the
persisted boolean the data-review page filters on. The flag has to track
linkage, so it stays true as the user links animals one at a time and only
clears when the last named animal is matched.
"""
from datetime import date

from sqlalchemy import select

from colony_manager.models import AnimalData, AnimalEventData, Data

from .factories import (
    make_animal, make_animal_data_type, make_animal_event_data_type,
    make_data_location, make_event, make_procedure, make_procedure_target,
)


def _make_animal_data(session, *, parsed, linked_animals, name='f'):
    dtype = make_animal_data_type(session)
    location = make_data_location(session, datatype=dtype, base_path='/tmp/ua')
    row = AnimalData(
        datatype_id=dtype.id,
        location_id=location.id,
        target_type='animal',
        relative_path=name,
        name=name,
        parsed_metadata=parsed,
    )
    session.add(row)
    row.animals = list(linked_animals)
    row.recompute_unmatched_flag()
    session.commit()
    return row


def test_flag_true_when_a_named_animal_is_unlinked(db_session):
    a1 = make_animal(db_session, custom_id='B028-1')
    a2 = make_animal(db_session, custom_id='B029-1')
    # B0828-4 is a typo — no such animal, so it can never be linked.
    row = _make_animal_data(
        db_session,
        parsed={'animal_id': ['B028-1', 'B0828-4', 'B029-1']},
        linked_animals=[a1, a2],
    )
    assert row.matched_animal_ids == {'B028-1', 'B029-1'}
    assert row.unmatched_animal_ids == ['B0828-4']
    assert row.has_unmatched_animals is True


def test_flag_false_when_all_named_animals_linked(db_session):
    a1 = make_animal(db_session, custom_id='B028-1')
    a2 = make_animal(db_session, custom_id='B029-1')
    row = _make_animal_data(
        db_session,
        parsed={'animal_id': ['B028-1', 'B029-1']},
        linked_animals=[a1, a2],
    )
    assert row.unmatched_animal_ids == []
    assert row.has_unmatched_animals is False


def test_flag_tracks_events_linked_one_at_a_time(db_session):
    """The scenario from the bug report: a file stays flagged until *every*
    named animal has a linked event, clearing only on the last link."""
    a1 = make_animal(db_session, custom_id='B032-1')
    a2 = make_animal(db_session, custom_id='B032-2')
    procedure = make_procedure(db_session, name='Noise Exposure')
    target = make_procedure_target(db_session)
    e1 = make_event(
        db_session, animal=a1, procedure=procedure, procedure_target=target,
        scheduled_date=date(2025, 1, 1), completion_date=date(2025, 1, 1),
    )
    e2 = make_event(
        db_session, animal=a2, procedure=procedure, procedure_target=target,
        scheduled_date=date(2025, 1, 1), completion_date=date(2025, 1, 1),
    )
    dtype = make_animal_event_data_type(db_session, default_procedure=procedure)
    location = make_data_location(db_session, datatype=dtype, base_path='/tmp/ne')
    row = AnimalEventData(
        datatype_id=dtype.id,
        location_id=location.id,
        target_type='animal_event',
        relative_path='ne',
        name='ne',
        parsed_metadata={'animal_id': ['B032-1', 'B032-2']},
    )
    db_session.add(row)
    row.recompute_unmatched_flag()
    db_session.commit()
    assert row.has_unmatched_animals is True
    assert set(row.unmatched_animal_ids) == {'B032-1', 'B032-2'}

    row.events.append(e1)
    row.recompute_unmatched_flag()
    db_session.commit()
    assert row.has_unmatched_animals is True          # B032-2 still unlinked
    assert row.unmatched_animal_ids == ['B032-2']

    row.events.append(e2)
    row.recompute_unmatched_flag()
    db_session.commit()
    assert row.has_unmatched_animals is False          # now fully matched
    assert row.unmatched_animal_ids == []


def test_review_query_finds_only_flagged(db_session):
    a1 = make_animal(db_session, custom_id='B028-1')
    flagged = _make_animal_data(
        db_session,
        parsed={'animal_id': ['B028-1', 'B0828-4']},
        linked_animals=[a1],
        name='flagged',
    )
    clean = _make_animal_data(
        db_session,
        parsed={'animal_id': ['B028-1']},
        linked_animals=[a1],
        name='clean',
    )

    found = db_session.scalars(
        select(Data).where(Data.has_unmatched_animals.is_(True))
    ).all()
    assert flagged in found
    assert clean not in found
