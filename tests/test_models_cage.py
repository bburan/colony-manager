"""Tests for ``Cage`` aggregate properties.

The Cage model exposes derived facts about its animals
(``animals_count``, ``active_animals_count``, ``sources``, ``sex``,
``sex_symbol``, ``age_display``, ``source_display``, ``is_active``).
Each property has two code paths:

1. **Uncached** — iterate ``self.animals`` (a ``lazy='dynamic'``
   relationship that issues SQL on access).
2. **Cached** — read from ``_cached_animals``, set by the bulk-load
   helper in routes/cages.py so list views don't fan out into N
   queries per row.

Coverage strategy: each aggregate is verified end-to-end against a
seeded cage in the uncached path, plus one parity test that proves
the cached path returns the same answer for the same fixture data.
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
# Cached path parity
# ---------------------------------------------------------------------------

def test_cached_path_matches_uncached(db_session):
    """``_cached_animals`` must not change any property's answer.

    Routes set this cache to short-circuit the dynamic relationship's
    queries; the in-memory iteration must produce the same aggregates
    as iterating the lazy query.
    """
    species = make_species(db_session)
    cage = make_cage(db_session, species=species)
    src = make_source(db_session, name='S')
    a1 = make_animal(
        db_session, cage=cage, species=species, source=src, sex='male',
        dob=date.today() - timedelta(days=30),
    )
    a2 = make_animal(
        db_session, cage=cage, species=species, source=src, sex='female',
        dob=date.today() - timedelta(days=60),
    )
    a2.terminate(termination_date=date.today())
    db_session.commit()

    uncached = (
        cage.animals_count,
        cage.active_animals_count,
        cage.is_active,
        sorted(cage.sex),
        cage.sex_symbol,
        cage.age_display('day'),
        cage.source_display,
    )

    # Re-fetch a fresh Cage so we know the uncached read above didn't
    # leak state, then prime the cache the way routes/cages do.
    fresh = db_session.get(Cage, cage.id)
    fresh._cached_animals = [a1, a2]

    cached = (
        fresh.animals_count,
        fresh.active_animals_count,
        fresh.is_active,
        sorted(fresh.sex),
        fresh.sex_symbol,
        fresh.age_display('day'),
        fresh.source_display,
    )

    assert uncached == cached
