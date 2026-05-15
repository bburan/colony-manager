"""Phase 1 sync tests — pure-Python helpers, no filesystem.

Covers:

* ``_candidate_animals_for`` — single id, list of ids, cache hit vs
  miss, unknown ids skipped.
* ``_candidate_ears_for`` — scalar / list side, side-key vs ear-key
  fallback, length-mismatch, non-Left/Right skip, cache hit vs miss.
* ``_maybe_auto_create_events`` — every guard clause + happy path +
  dry-run no-op.
* ``_is_unmatched`` — per-target_type attribute dispatch.

Phase 2 (orchestration: ``sync_locations``, ``rematch_datatype``)
lives in a separate test file once the helpers are nailed down.
"""
from datetime import date
from types import SimpleNamespace

from colony_manager_gui.sync import (
    _candidate_animals_for, _candidate_ears_for,
    _is_unmatched, _maybe_auto_create_events,
)
from colony_manager.models import AnimalEvent

from .factories import (
    make_animal, make_animal_event_data_type, make_ear, make_procedure,
    make_procedure_target, make_species,
)


# ---------------------------------------------------------------------------
# _candidate_animals_for
# ---------------------------------------------------------------------------

def test_candidate_animals_empty_input(db_session):
    assert _candidate_animals_for(db_session, {}) == []
    assert _candidate_animals_for(db_session, {'animal_id': None}) == []
    assert _candidate_animals_for(db_session, {'animal_id': []}) == []


def test_candidate_animals_str_id_resolves_via_db(db_session):
    a = make_animal(db_session, custom_id='SOLO-1')
    assert _candidate_animals_for(db_session, {'animal_id': 'SOLO-1'}) == [a]


def test_candidate_animals_unknown_id_returns_empty(db_session):
    make_animal(db_session, custom_id='REAL')
    result = _candidate_animals_for(db_session, {'animal_id': 'GHOST'})
    assert result == []


def test_candidate_animals_list_iterates_all(db_session):
    species = make_species(db_session)
    a = make_animal(db_session, species=species, custom_id='LIST-A')
    b = make_animal(db_session, species=species, custom_id='LIST-B')
    result = _candidate_animals_for(
        db_session, {'animal_id': ['LIST-A', 'LIST-B']},
    )
    assert result == [a, b]


def test_candidate_animals_skips_unknown_in_list(db_session):
    a = make_animal(db_session, custom_id='REAL-A')
    result = _candidate_animals_for(
        db_session, {'animal_id': ['REAL-A', 'NOPE']},
    )
    assert result == [a]


def test_candidate_animals_uses_cache_when_provided(db_session):
    """When ``animals_by_cid`` is supplied, the DB shouldn't be touched.

    Verify by passing a cache that maps an id to an object that isn't
    in the DB at all — function still returns it.
    """
    fake = SimpleNamespace(custom_id='FAKE', id=12345)
    result = _candidate_animals_for(
        db_session, {'animal_id': 'FAKE'},
        animals_by_cid={'FAKE': fake},
    )
    assert result == [fake]


def test_candidate_animals_cache_miss_returns_empty(db_session):
    """Cache provided but id absent from cache — no DB fallback fires."""
    real = make_animal(db_session, custom_id='REAL-DB')
    result = _candidate_animals_for(
        db_session, {'animal_id': 'REAL-DB'},
        animals_by_cid={},
    )
    # Empty cache → real DB row is NOT discovered (cache is authoritative).
    assert result == []


# ---------------------------------------------------------------------------
# _candidate_ears_for
# ---------------------------------------------------------------------------

def test_candidate_ears_empty_inputs(db_session):
    assert _candidate_ears_for(db_session, {}, []) == []
    assert _candidate_ears_for(
        db_session, {'animal_id': 'X', 'side': 'Left'}, [],
    ) == []


def test_candidate_ears_scalar_side_broadcasts(db_session):
    species = make_species(db_session)
    a = make_animal(db_session, species=species, custom_id='EAR-A')
    b = make_animal(db_session, species=species, custom_id='EAR-B')
    a_left = make_ear(db_session, animal=a, side='Left')
    b_left = make_ear(db_session, animal=b, side='Left')
    make_ear(db_session, animal=a, side='Right')  # must not appear

    result = _candidate_ears_for(
        db_session,
        {'animal_id': ['EAR-A', 'EAR-B'], 'side': 'Left'},
        [a, b],
    )
    assert result == [a_left, b_left]


def test_candidate_ears_per_animal_side_list(db_session):
    species = make_species(db_session)
    a = make_animal(db_session, species=species, custom_id='PER-A')
    b = make_animal(db_session, species=species, custom_id='PER-B')
    a_left = make_ear(db_session, animal=a, side='Left')
    b_right = make_ear(db_session, animal=b, side='Right')

    result = _candidate_ears_for(
        db_session,
        {'animal_id': ['PER-A', 'PER-B'], 'side': ['Left', 'Right']},
        [a, b],
    )
    assert result == [a_left, b_right]


def test_candidate_ears_side_list_length_mismatch_returns_empty(db_session):
    a = make_animal(db_session, custom_id='MM-A')
    make_ear(db_session, animal=a, side='Left')
    result = _candidate_ears_for(
        db_session,
        {'animal_id': ['MM-A'], 'side': ['Left', 'Right']},
        [a],
    )
    assert result == []


def test_candidate_ears_falls_back_to_ear_key(db_session):
    """When ``side`` is absent, the parser may have set ``ear`` instead."""
    a = make_animal(db_session, custom_id='FB-A')
    ear = make_ear(db_session, animal=a, side='Right')
    result = _candidate_ears_for(
        db_session,
        {'animal_id': 'FB-A', 'ear': 'right'},
        [a],
    )
    assert result == [ear]


def test_candidate_ears_skips_invalid_side(db_session):
    a = make_animal(db_session, custom_id='INV-A')
    make_ear(db_session, animal=a, side='Left')
    result = _candidate_ears_for(
        db_session,
        {'animal_id': 'INV-A', 'side': 'middle'},  # canonicalizes to None
        [a],
    )
    assert result == []


def test_candidate_ears_uses_cache_when_provided(db_session):
    a = make_animal(db_session, custom_id='CACHE-A')
    fake_ear = SimpleNamespace(animal_id=a.id, side='Left', id=999)
    result = _candidate_ears_for(
        db_session,
        {'animal_id': 'CACHE-A', 'side': 'Left'},
        [a],
        ears_by_animal_side={(a.id, 'Left'): fake_ear},
    )
    assert result == [fake_ear]


def test_candidate_ears_skips_animals_not_in_candidates(db_session):
    """An id parsed from a filename but not in ``candidate_animals``
    (e.g. it didn't survive the upstream animal lookup) is skipped.
    """
    a = make_animal(db_session, custom_id='IN')
    make_ear(db_session, animal=a, side='Left')
    result = _candidate_ears_for(
        db_session,
        {'animal_id': ['IN', 'OUT'], 'side': ['Left', 'Left']},
        [a],  # only IN is in candidates
    )
    assert len(result) == 1
    assert result[0].side == 'Left'


# ---------------------------------------------------------------------------
# _maybe_auto_create_events
# ---------------------------------------------------------------------------

def _aedtype_with(session, *, auto_create=True, procedure=None, target=None):
    """Helper: build an AnimalEventDataType with the given knobs.

    The factory doesn't expose ``auto_create``, so we set it after.
    """
    dtype = make_animal_event_data_type(
        session, default_procedure=procedure, default_procedure_target=target,
    )
    dtype.auto_create = auto_create
    session.commit()
    return dtype


def test_auto_create_returns_empty_when_flag_off(db_session):
    procedure = make_procedure(db_session)
    animal = make_animal(db_session)
    dtype = _aedtype_with(db_session, auto_create=False, procedure=procedure)

    events = _maybe_auto_create_events(
        db_session, dtype, {'date': date.today()}, [animal],
    )
    assert events == []


def test_auto_create_returns_empty_when_wrong_target_type(db_session):
    """Non-animal_event DataTypes can't auto-create regardless of flag."""
    # Use a SimpleNamespace standing in for a DataType-shaped object — we
    # only need auto_create + target_type to fail the guard before any
    # DB calls happen.
    dtype = SimpleNamespace(
        auto_create=True, target_type='confocal_image',
        default_procedure_id=1, default_procedure_target_id=None,
    )
    animal = make_animal(db_session)
    events = _maybe_auto_create_events(
        db_session, dtype, {'date': date.today()}, [animal],
    )
    assert events == []


def test_auto_create_returns_empty_without_default_procedure(db_session):
    animal = make_animal(db_session)
    dtype = _aedtype_with(db_session, auto_create=True)  # no procedure
    events = _maybe_auto_create_events(
        db_session, dtype, {'date': date.today()}, [animal],
    )
    assert events == []


def test_auto_create_returns_empty_without_date(db_session):
    procedure = make_procedure(db_session)
    animal = make_animal(db_session)
    dtype = _aedtype_with(db_session, procedure=procedure)
    events = _maybe_auto_create_events(db_session, dtype, {}, [animal])
    assert events == []


def test_auto_create_returns_empty_without_candidates(db_session):
    procedure = make_procedure(db_session)
    dtype = _aedtype_with(db_session, procedure=procedure)
    events = _maybe_auto_create_events(
        db_session, dtype, {'date': date.today()}, [],
    )
    assert events == []


def test_auto_create_dry_run_no_op(db_session):
    procedure = make_procedure(db_session)
    animal = make_animal(db_session)
    dtype = _aedtype_with(db_session, procedure=procedure)
    events = _maybe_auto_create_events(
        db_session, dtype, {'date': date.today()}, [animal], dry_run=True,
    )
    assert events == []
    # Nothing persisted.
    db_session.commit()
    from sqlalchemy import select
    persisted = db_session.scalars(select(AnimalEvent)).all()
    assert persisted == []


def test_auto_create_creates_one_event_per_candidate(db_session):
    species = make_species(db_session)
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    dtype = _aedtype_with(
        db_session, procedure=procedure, target=target,
    )
    a = make_animal(db_session, species=species, custom_id='AC-A')
    b = make_animal(db_session, species=species, custom_id='AC-B')

    target_date = date(2025, 8, 15)
    events = _maybe_auto_create_events(
        db_session, dtype, {'date': target_date}, [a, b],
    )
    db_session.commit()

    assert len(events) == 2
    assert {e.animal_id for e in events} == {a.id, b.id}
    for e in events:
        assert e.procedure_id == procedure.id
        assert e.procedure_target_id == target.id
        assert e.scheduled_date == target_date
        assert e.completion_date == target_date


# ---------------------------------------------------------------------------
# _is_unmatched
# ---------------------------------------------------------------------------

def test_is_unmatched_unknown_target_type_returns_true():
    """Defensive fallback: an unrecognized discriminator means we can't
    decide, so callers should treat the row as unmatched.
    """
    row = SimpleNamespace()
    assert _is_unmatched(row, 'mystery_type') is True


def test_is_unmatched_animal_event_empty():
    row = SimpleNamespace(events=[])
    assert _is_unmatched(row, 'animal_event') is True


def test_is_unmatched_animal_event_populated():
    row = SimpleNamespace(events=[object()])
    assert _is_unmatched(row, 'animal_event') is False


def test_is_unmatched_confocal_image_empty():
    row = SimpleNamespace(confocal_images=[])
    assert _is_unmatched(row, 'confocal_image') is True


def test_is_unmatched_animal_empty():
    row = SimpleNamespace(animals=[])
    assert _is_unmatched(row, 'animal') is True


def test_is_unmatched_ear_empty():
    row = SimpleNamespace(ears=[])
    assert _is_unmatched(row, 'ear') is True
