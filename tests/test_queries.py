"""Unit tests for the dashboard query helpers in colony_manager_gui.queries.

Exercises each helper end-to-end against the per-test Postgres clone:
* All four helpers return ``[(species_name, count), ...]`` row tuples.
* Empty-DB returns ``[]`` (the OUTER JOINs collapse to no rows).
* Active / inactive / pair-state filters narrow correctly.
"""
from datetime import date

from colony_manager.models import BreedingPair, Ear
from colony_manager_gui import queries

from .factories import make_animal, make_cage, make_species


def test_count_active_cages_empty(db_session):
    assert queries.count_active_cages(db_session) == []


def test_count_active_cages_with_active_and_inactive(db_session):
    species = make_species(db_session, name='Mouse')
    # Active cage: has an un-terminated animal.
    cage_a = make_cage(db_session, species=species, custom_id='ACT')
    make_animal(db_session, cage=cage_a, species=species)
    # Active cage (empty): the OR-no-animals branch.
    make_cage(db_session, species=species, custom_id='EMPTY')
    # Inactive: only terminated animals.
    cage_t = make_cage(db_session, species=species, custom_id='TERM')
    terminated = make_animal(db_session, cage=cage_t, species=species)
    terminated.terminate(termination_date=date.today())
    db_session.commit()

    rows = queries.count_active_cages(db_session)
    by_name = dict(rows)
    # 2 active cages (ACT + EMPTY); TERM is excluded because its only
    # animal is terminated.
    assert by_name == {'Mouse': 2}


def test_count_active_animals_excludes_terminated_and_unassigned_ids(db_session):
    species = make_species(db_session, name='Mouse')
    # Active + has custom_id → counted.
    make_animal(db_session, species=species, custom_id='A-1')
    # Active but no custom_id → excluded.
    no_id = make_animal(db_session, species=species)
    no_id.custom_id = None
    # Terminated → excluded.
    terminated = make_animal(db_session, species=species, custom_id='T-1')
    terminated.terminate(termination_date=date.today())
    db_session.commit()

    rows = queries.count_active_animals(db_session)
    assert dict(rows) == {'Mouse': 1}


def test_count_unprocessed_ears(db_session):
    species = make_species(db_session, name='Mouse')
    animal = make_animal(db_session, species=species)
    # Ear without an immunolabel_date → counted.
    pending = Ear(animal_id=animal.id, side='Left')
    # Ear with date → excluded.
    done = Ear(animal_id=animal.id, side='Right', immunolabel_date=date.today())
    db_session.add_all([pending, done])
    db_session.commit()

    rows = queries.count_unprocessed_ears(db_session)
    assert dict(rows) == {'Mouse': 1}


def test_count_active_breeding_pairs(db_session):
    species = make_species(db_session, name='Mouse')
    male = make_animal(db_session, species=species, sex='male')
    female = make_animal(db_session, species=species, sex='female')
    active = BreedingPair(
        custom_id='BP-A', male_animal_id=male.id,
        female_animal_id=female.id, start_date=date.today(),
        is_active=True,
    )
    male2 = make_animal(db_session, species=species, sex='male')
    female2 = make_animal(db_session, species=species, sex='female')
    inactive = BreedingPair(
        custom_id='BP-I', male_animal_id=male2.id,
        female_animal_id=female2.id, start_date=date.today(),
        is_active=False,
    )
    db_session.add_all([active, inactive])
    db_session.commit()

    rows = queries.count_active_breeding_pairs(db_session)
    assert dict(rows) == {'Mouse': 1}
