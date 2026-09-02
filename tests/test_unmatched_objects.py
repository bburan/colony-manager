"""Tests for ``Data.unmatched_objects`` — the per-row list that drives the
Unmatched-Data page's "Unlinked objects" column.

Each entry is a ``(kind, obj, label)`` tuple: resolved rows carry their ORM
object (linked in the UI, dark pill); unresolved names carry ``None`` (grey,
unlinked pill). Animal-targeted files yield animals; ear/confocal files yield
ears at side granularity, falling back to animal/typo pills.
"""
from colony_manager.models import AnimalData, EarData

from .factories import (
    make_animal, make_animal_data_type, make_data_location, make_ear,
    make_ear_data_type,
)


def _make_animal_data(session, *, parsed, candidates, linked=(), name='f'):
    dtype = make_animal_data_type(session)
    location = make_data_location(session, datatype=dtype, base_path='/tmp/uo_a')
    row = AnimalData(
        datatype_id=dtype.id, location_id=location.id, target_type='animal',
        relative_path=name, name=name, parsed_metadata=parsed,
    )
    session.add(row)
    row.animals = list(linked)
    row.candidate_animals = list(candidates)
    session.commit()
    return row


def _make_ear_data(session, *, parsed, candidate_animals, candidate_ears,
                   linked=(), name='e'):
    dtype = make_ear_data_type(session)
    location = make_data_location(session, datatype=dtype, base_path='/tmp/uo_e')
    row = EarData(
        datatype_id=dtype.id, location_id=location.id, target_type='ear',
        relative_path=name, name=name, parsed_metadata=parsed,
    )
    session.add(row)
    row.ears = list(linked)
    row.candidate_animals = list(candidate_animals)
    row.candidate_ears = list(candidate_ears)
    session.commit()
    return row


def test_animal_objects_link_when_resolved_grey_when_typo(db_session):
    a1 = make_animal(db_session, custom_id='B028-1')
    row = _make_animal_data(
        db_session,
        parsed={'animal_id': ['B028-1', 'B0828-4']},  # 2nd is a typo
        candidates=[a1],
    )
    assert row.unmatched_objects == [
        ('animal', a1, a1.display_id),
        ('animal', None, 'B0828-4'),
    ]


def test_ear_objects_yield_unlinked_ears_at_side_granularity(db_session):
    a = make_animal(db_session, custom_id='G014-4')
    ear = make_ear(db_session, animal=a, side='Left')
    row = _make_ear_data(
        db_session,
        parsed={'animal_id': ['G014-4'], 'side': 'Left'},
        candidate_animals=[a],
        candidate_ears=[ear],
    )
    assert row.unmatched_objects == [('ear', ear, ear.full_display)]


def test_ear_objects_exclude_already_linked_ear(db_session):
    a = make_animal(db_session, custom_id='G014-4')
    ear = make_ear(db_session, animal=a, side='Left')
    row = _make_ear_data(
        db_session,
        parsed={'animal_id': ['G014-4'], 'side': 'Left'},
        candidate_animals=[a],
        candidate_ears=[ear],
        linked=[ear],  # already matched → not "unlinked"
    )
    assert row.unmatched_objects == []


def test_ear_file_typo_falls_back_to_grey_pill(db_session):
    row = _make_ear_data(
        db_session,
        parsed={'animal_id': ['G999-9'], 'side': 'Left'},  # no such animal/ear
        candidate_animals=[],
        candidate_ears=[],
    )
    assert row.unmatched_objects == [('animal', None, 'G999-9')]
