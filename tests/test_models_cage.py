"""Tests for ``Cage`` aggregate properties.

The Cage model exposes derived facts about its animals
(``animals_count``, ``active_animals_count``, ``sex``, ``sex_symbol``,
``age_display``, ``source_display``, ``is_active``). After the
lazy='dynamic' purge each property reads ``self.animals`` (now a
plain list backed by ``lazy='select'``) and computes the answer in
Python; list views eager-load the collection via
``selectinload(Cage.animals)`` to avoid N+1 fan-out across rows.
"""
from datetime import date, timedelta

from colony_manager.models import Cage

from .factories import make_animal, make_cage, make_source, make_species


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

def test_empty_cage_counts_are_zero(db_session):
    cage = make_cage(db_session)
    assert cage.animals_count == 0
    assert cage.active_animals_count == 0
    assert cage.is_active is False


def test_animals_count_includes_terminated(db_session):
    cage = make_cage(db_session)
    make_animal(db_session, cage=cage)
    terminated = make_animal(db_session, cage=cage)
    terminated.terminate(termination_date=date.today())
    db_session.commit()

    assert cage.animals_count == 2
    assert cage.active_animals_count == 1
    assert cage.is_active is True


def test_is_active_false_when_all_terminated(db_session):
    cage = make_cage(db_session)
    animal = make_animal(db_session, cage=cage)
    animal.terminate(termination_date=date.today())
    db_session.commit()

    assert cage.animals_count == 1
    assert cage.active_animals_count == 0
    assert cage.is_active is False


# ---------------------------------------------------------------------------
# Sex aggregation
# ---------------------------------------------------------------------------

def test_sex_single_sex_cage(db_session):
    cage = make_cage(db_session)
    make_animal(db_session, cage=cage, sex='male')
    make_animal(db_session, cage=cage, sex='male')

    assert cage.sex == ['male']
    assert cage.sex_symbol == '♂'


def test_sex_mixed_cage(db_session):
    cage = make_cage(db_session)
    make_animal(db_session, cage=cage, sex='male')
    make_animal(db_session, cage=cage, sex='female')

    assert sorted(cage.sex) == ['female', 'male']
    assert cage.sex_symbol == '⚥'


def test_sex_symbol_empty_cage_is_blank(db_session):
    cage = make_cage(db_session)
    assert cage.sex_symbol == ''


# ---------------------------------------------------------------------------
# Source aggregation
# ---------------------------------------------------------------------------

def test_source_display_joins_unique_sources(db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    a = make_source(db_session, name='Alpha')
    b = make_source(db_session, name='Beta')
    make_animal(db_session, cage=cage, species=species, source=a)
    make_animal(db_session, cage=cage, species=species, source=b)
    make_animal(db_session, cage=cage, species=species, source=a)  # duplicate

    assert cage.source_display == 'Alpha, Beta'


def test_source_display_empty_when_no_animals(db_session):
    cage = make_cage(db_session)
    assert cage.source_display == 'N/A'


# ---------------------------------------------------------------------------
# Age display
# ---------------------------------------------------------------------------

def test_age_display_single_animal(db_session):
    cage = make_cage(db_session)
    make_animal(
        db_session, cage=cage,
        dob=date.today() - timedelta(days=42),
    )
    assert cage.age_display('day') == '42.0 days'


def test_age_display_range(db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    make_animal(
        db_session, cage=cage, species=species,
        dob=date.today() - timedelta(days=10),
    )
    make_animal(
        db_session, cage=cage, species=species,
        dob=date.today() - timedelta(days=50),
    )
    # Sorted ascending in the property, so the youngest is first.
    assert cage.age_display('day') == '10.0 to 50.0 days'


def test_age_display_empty_cage(db_session):
    cage = make_cage(db_session)
    assert cage.age_display('day') == 'N/A'


# ---------------------------------------------------------------------------
# Property aggregation on a freshly-loaded cage
# ---------------------------------------------------------------------------

def test_properties_aggregate_correctly_after_fresh_load(db_session):
    """Every Cage aggregate property reads from ``self.animals`` directly
    (no per-instance cache). After committing the fixture and fetching
    a fresh Cage, the properties must still return the right answers.
    """
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    src = make_source(db_session, name='S')
    make_animal(
        db_session, cage=cage, species=species, source=src, sex='male',
        dob=date.today() - timedelta(days=30),
    )
    terminated = make_animal(
        db_session, cage=cage, species=species, source=src, sex='female',
        dob=date.today() - timedelta(days=60),
    )
    terminated.terminate(termination_date=date.today())
    db_session.commit()
    db_session.expire_all()

    fresh = db_session.get(Cage, cage.id)
    assert fresh.animals_count == 2
    assert fresh.active_animals_count == 1
    assert fresh.is_active is True
    assert sorted(fresh.sex) == ['female', 'male']
    assert fresh.sex_symbol == '⚥'
    assert fresh.age_display('day') == '30.0 to 60.0 days'
    assert fresh.source_display == 'S'
