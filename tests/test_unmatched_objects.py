"""Tests for ``Data.unmatched_objects`` — the per-row list that drives the
Unmatched-Data page's "Unlinked objects" column.

Each entry is an ``UnmatchedObject(kind, obj, label, animal, side)``:
resolved rows carry their ORM object (linked in the UI, dark pill);
unresolved names carry ``None`` (grey, unlinked pill). Animal-targeted
files yield animals; ear/confocal files yield ears at side granularity --
including ears that don't exist yet, since the target of those datatypes
is an ear. Such an entry still carries the resolved ``animal`` and the
``side``, which the page renders as a split dark/light pill linking to
the animal. Only a file naming no side at all falls back to an animal
pill.
"""
from colony_manager.models import AnimalData, EarData, UnmatchedObject

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
        UnmatchedObject('animal', a1, a1.display_id, a1, None),
        UnmatchedObject('animal', None, 'B0828-4', None, None),
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
    assert row.unmatched_objects == [
        UnmatchedObject('ear', ear, ear.full_display, ear.animal, ear.side)]


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


def test_ear_file_typo_names_the_ear_not_the_animal(db_session):
    """A typo still yields a grey pill, but an ear-shaped one.

    The datatype's target is an ear, so naming the animal alone would
    understate what is missing even when nothing resolves.
    """
    row = _make_ear_data(
        db_session,
        parsed={'animal_id': ['G999-9'], 'side': 'Left'},  # no such animal/ear
        candidate_animals=[],
        candidate_ears=[],
    )
    assert row.unmatched_objects == [
        UnmatchedObject('ear', None, 'G999-9 Left', None, 'Left')]


def test_existing_animal_missing_that_ear_reports_the_ear(db_session):
    """The real-world B047-3R case: animal is present, its Right ear is not.

    Reporting ``B047-3`` here is actively misleading -- the animal is fine
    and linkable; it is the Right ear row that does not exist. The animal
    rides along on the entry so the page can render a split pill whose
    linked half reaches the page where that ear gets created.
    """
    a = make_animal(db_session, custom_id='B047-3')
    make_ear(db_session, animal=a, side='Left')      # only the other side
    row = _make_ear_data(
        db_session,
        parsed={'animal_id': ['B047-3'], 'ear': 'Right'},
        candidate_animals=[a],
        candidate_ears=[],
    )
    assert row.unmatched_objects == [
        UnmatchedObject('ear', None, 'B047-3 Right', a, 'Right')]


def test_ear_resolves_even_when_not_a_candidate(db_session):
    """An ear that exists but was never made a candidate still links.

    Matching failed to nominate it, but the row is right there, so the
    pill should reach its detail page rather than render as a dead name.
    """
    a = make_animal(db_session, custom_id='B047-4')
    ear = make_ear(db_session, animal=a, side='Right')
    row = _make_ear_data(
        db_session,
        parsed={'animal_id': ['B047-4'], 'ear': 'Right'},
        candidate_animals=[a],
        candidate_ears=[],                            # matcher missed it
    )
    assert row.unmatched_objects == [
        UnmatchedObject('ear', ear, ear.full_display, ear.animal, ear.side)]


def test_side_spelled_as_a_list_is_zipped_against_animals(db_session):
    """Ear Dissection Notes store ``side`` as a list, one per animal."""
    a1 = make_animal(db_session, custom_id='G020-1')
    a2 = make_animal(db_session, custom_id='G020-2')
    row = _make_ear_data(
        db_session,
        parsed={'animal_id': ['G020-1', 'G020-2'], 'side': ['Left', 'Right']},
        candidate_animals=[a1, a2],
        candidate_ears=[],
    )
    assert row.unmatched_objects == [
        UnmatchedObject('ear', None, 'G020-1 Left', a1, 'Left'),
        UnmatchedObject('ear', None, 'G020-2 Right', a2, 'Right'),
    ]


def test_lowercase_side_matches_an_existing_ear(db_session):
    """psi-derived files lowercase the side; ``Ear.side`` is capitalised."""
    a = make_animal(db_session, custom_id='G021-1')
    ear = make_ear(db_session, animal=a, side='Left')
    row = _make_ear_data(
        db_session,
        parsed={'animal_id': ['G021-1'], 'side': 'left'},
        candidate_animals=[a],
        candidate_ears=[],
    )
    assert row.unmatched_objects == [
        UnmatchedObject('ear', ear, ear.full_display, ear.animal, ear.side)]


def test_no_side_in_filename_still_falls_back_to_the_animal(db_session):
    """Without a side there is nothing more specific than the animal."""
    a = make_animal(db_session, custom_id='G022-1')
    make_ear(db_session, animal=a, side='Left')
    row = _make_ear_data(
        db_session,
        parsed={'animal_id': ['G022-1']},              # no ear/side key
        candidate_animals=[a],
        candidate_ears=[],
    )
    assert row.unmatched_objects == [
        UnmatchedObject('animal', a, a.display_id, a, None)]
