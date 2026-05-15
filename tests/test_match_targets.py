"""Tests for the polymorphic ``DataType.match_targets`` methods.

Each ``DataType`` subclass resolves a parsed metadata dict to a list
of target model instances:

* ``AnimalEventDataType`` — match an existing event by animal +
  procedure + date (scheduled or completion), optionally narrowed by
  side.
* ``ConfocalImageDataType`` — match by animal + ear side + frequency
  + image_type name.
* ``AnimalDataType`` / ``EarDataType`` — direct lookup by custom_id
  (and side, for ears).

All four take an explicit ``session`` after the refactor.
"""
from datetime import date, timedelta

from .factories import (
    make_animal, make_animal_data_type, make_animal_event_data_type,
    make_confocal_image, make_confocal_image_data_type,
    make_confocal_image_type, make_ear, make_ear_data_type,
    make_event, make_procedure, make_procedure_target, make_species,
)


# ---------------------------------------------------------------------------
# AnimalEventDataType
# ---------------------------------------------------------------------------

def test_animal_event_matches_by_animal_procedure_date(db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='AE-1')
    procedure = make_procedure(db_session, name='Dissection')
    target = make_procedure_target(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    event = make_event(
        db_session, animal=animal, procedure=procedure,
        procedure_target=target,
        scheduled_date=date(2025, 6, 1),
        completion_date=date(2025, 6, 1),
    )

    matches = dtype.match_targets(db_session, {
        'animal_id': 'AE-1',
        'date': date(2025, 6, 1),
    })
    assert matches == [event]


def test_animal_event_matches_by_scheduled_date_only(db_session):
    """An event whose ``scheduled_date`` (not completion) matches still hits."""
    animal = make_animal(db_session, custom_id='AE-2')
    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    event = make_event(
        db_session, animal=animal, procedure=procedure,
        scheduled_date=date(2025, 6, 5),
        completion_date=None,
    )

    matches = dtype.match_targets(db_session, {
        'animal_id': 'AE-2',
        'date': date(2025, 6, 5),
    })
    assert matches == [event]


def test_animal_event_side_filter_narrows(db_session):
    animal = make_animal(db_session, custom_id='AE-3')
    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    left = make_event(
        db_session, animal=animal, procedure=procedure,
        scheduled_date=date(2025, 6, 10), side='Left',
    )
    make_event(  # right-side event that must be excluded
        db_session, animal=animal, procedure=procedure,
        scheduled_date=date(2025, 6, 10), side='Right',
    )

    matches = dtype.match_targets(db_session, {
        'animal_id': 'AE-3',
        'date': date(2025, 6, 10),
        'side': 'left',  # canonicalized to 'Left' by _canonical_side
    })
    assert matches == [left]


def test_animal_event_returns_empty_when_animal_unknown(db_session):
    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    matches = dtype.match_targets(db_session, {
        'animal_id': 'does-not-exist',
        'date': date.today(),
    })
    assert matches == []


def test_animal_event_returns_empty_when_no_default_procedure(db_session):
    """A DataType without ``default_procedure_id`` can never match."""
    dtype = make_animal_event_data_type(db_session)  # no procedure
    matches = dtype.match_targets(db_session, {
        'animal_id': 'whatever',
        'date': date.today(),
    })
    assert matches == []


def test_animal_event_accepts_list_of_ids(db_session):
    procedure = make_procedure(db_session)
    species = make_species(db_session)
    a1 = make_animal(db_session, species=species, custom_id='M-1')
    a2 = make_animal(db_session, species=species, custom_id='M-2')
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    e1 = make_event(
        db_session, animal=a1, procedure=procedure,
        scheduled_date=date(2025, 7, 1),
    )
    e2 = make_event(
        db_session, animal=a2, procedure=procedure,
        scheduled_date=date(2025, 7, 1),
    )

    matches = dtype.match_targets(db_session, {
        'animal_id': ['M-1', 'M-2'],
        'date': date(2025, 7, 1),
    })
    assert set(matches) == {e1, e2}


# ---------------------------------------------------------------------------
# ConfocalImageDataType
# ---------------------------------------------------------------------------

def test_confocal_matches_by_animal_ear_freq_imagetype(db_session):
    animal = make_animal(db_session, custom_id='C-1')
    left_ear = make_ear(db_session, animal=animal, side='Left')
    image_type = make_confocal_image_type(db_session, name='Myo7a')
    image = make_confocal_image(
        db_session, ear=left_ear, image_type=image_type, frequency=8000.0,
    )
    dtype = make_confocal_image_data_type(db_session)

    matches = dtype.match_targets(db_session, {
        'animal_id': 'C-1',
        'ear': 'left',
        'frequency': 8000.0,
        'image_type': 'Myo7a',
    })
    assert matches == [image]


def test_confocal_frequency_tolerance(db_session):
    """Frequency comparison uses ``abs(diff) < 1e-6`` — tiny float wobble ok."""
    animal = make_animal(db_session, custom_id='C-2')
    ear = make_ear(db_session, animal=animal, side='Right')
    image_type = make_confocal_image_type(db_session, name='Phall')
    image = make_confocal_image(
        db_session, ear=ear, image_type=image_type, frequency=16000.0,
    )
    dtype = make_confocal_image_data_type(db_session)

    matches = dtype.match_targets(db_session, {
        'animal_id': 'C-2',
        'ear': 'right',
        'frequency': 16000.0000000001,  # within tolerance
        'image_type': 'Phall',
    })
    assert matches == [image]


def test_confocal_returns_empty_when_image_type_missing(db_session):
    animal = make_animal(db_session, custom_id='C-3')
    make_ear(db_session, animal=animal, side='Left')
    dtype = make_confocal_image_data_type(db_session)

    matches = dtype.match_targets(db_session, {
        'animal_id': 'C-3',
        'ear': 'left',
        'frequency': 8000.0,
        'image_type': 'NotARealType',
    })
    assert matches == []


def test_confocal_returns_empty_when_required_field_missing(db_session):
    """Method needs animal_id, ear, frequency, and image_type."""
    dtype = make_confocal_image_data_type(db_session)
    assert dtype.match_targets(db_session, {}) == []
    assert dtype.match_targets(db_session, {
        'animal_id': 'X', 'ear': 'left', 'frequency': 8000.0,
        # missing image_type
    }) == []


# ---------------------------------------------------------------------------
# AnimalDataType
# ---------------------------------------------------------------------------

def test_animal_datatype_matches_by_custom_id(db_session):
    animal = make_animal(db_session, custom_id='X-1')
    dtype = make_animal_data_type(db_session)
    matches = dtype.match_targets(db_session, {'animal_id': 'X-1'})
    assert matches == [animal]


def test_animal_datatype_accepts_list_and_skips_unknown(db_session):
    species = make_species(db_session)
    a = make_animal(db_session, species=species, custom_id='X-A')
    b = make_animal(db_session, species=species, custom_id='X-B')
    dtype = make_animal_data_type(db_session)

    matches = dtype.match_targets(db_session, {
        'animal_id': ['X-A', 'X-NOPE', 'X-B'],
    })
    assert matches == [a, b]


def test_animal_datatype_empty_input(db_session):
    dtype = make_animal_data_type(db_session)
    assert dtype.match_targets(db_session, {}) == []
    assert dtype.match_targets(db_session, {'animal_id': None}) == []


# ---------------------------------------------------------------------------
# EarDataType
# ---------------------------------------------------------------------------

def test_ear_datatype_matches_by_animal_and_side(db_session):
    animal = make_animal(db_session, custom_id='E-1')
    left = make_ear(db_session, animal=animal, side='Left')
    make_ear(db_session, animal=animal, side='Right')  # must not match
    dtype = make_ear_data_type(db_session)

    matches = dtype.match_targets(db_session, {
        'animal_id': 'E-1', 'side': 'left',
    })
    assert matches == [left]


def test_ear_datatype_per_animal_side_list(db_session):
    """Sides list parallel to animal_id — each animal gets its own side."""
    species = make_species(db_session)
    a = make_animal(db_session, species=species, custom_id='E-A')
    b = make_animal(db_session, species=species, custom_id='E-B')
    a_left = make_ear(db_session, animal=a, side='Left')
    b_right = make_ear(db_session, animal=b, side='Right')
    dtype = make_ear_data_type(db_session)

    matches = dtype.match_targets(db_session, {
        'animal_id': ['E-A', 'E-B'],
        'side': ['Left', 'Right'],
    })
    assert matches == [a_left, b_right]


def test_ear_datatype_returns_empty_when_side_list_length_mismatch(db_session):
    """Side list length must match animal_id length."""
    species = make_species(db_session)
    a = make_animal(db_session, species=species, custom_id='E-X')
    make_ear(db_session, animal=a, side='Left')
    dtype = make_ear_data_type(db_session)

    matches = dtype.match_targets(db_session, {
        'animal_id': ['E-X'],
        'side': ['Left', 'Right'],  # one extra
    })
    assert matches == []
