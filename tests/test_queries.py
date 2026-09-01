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
    # Empty cage: NOT active — matches the Cages page, which requires at
    # least one un-terminated animal.
    make_cage(db_session, species=species, custom_id='EMPTY')
    # Inactive: only terminated animals.
    cage_t = make_cage(db_session, species=species, custom_id='TERM')
    terminated = make_animal(db_session, cage=cage_t, species=species)
    terminated.terminate(termination_date=date.today())
    db_session.commit()

    rows = queries.count_active_cages(db_session)
    by_name = dict(rows)
    # Only ACT counts; EMPTY (no animals) and TERM (only terminated) are
    # both excluded — the dashboard now agrees with the Cages page.
    assert by_name == {'Mouse': 1}


def test_active_cage_count_matches_cages_page(db_session):
    """Dashboard 'Active Cages' agrees with the Cages page active filter.

    Regression for the two using different definitions of 'active' (the
    dashboard used to count empty cages, the Cages page never did).
    """
    from colony_manager_gui.services.cage_queries import get_filtered_cages

    species = make_species(db_session, name='Mouse')
    cage_a = make_cage(db_session, species=species, custom_id='ACT')
    make_animal(db_session, cage=cage_a, species=species)
    make_cage(db_session, species=species, custom_id='EMPTY')  # empty → not active
    db_session.commit()

    dashboard = dict(queries.count_active_cages(db_session)).get('Mouse', 0)
    page = get_filtered_cages(
        db_session, {'status_filter': 'active', 'species_id': species.id},
    )
    assert dashboard == len(page) == 1


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


def test_count_active_breeding_pairs_ignores_is_active_flag(db_session):
    """Both-alive pairs count regardless of the (currently unused, un-editable)
    is_active flag."""
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
    flagged_inactive = BreedingPair(
        custom_id='BP-I', male_animal_id=male2.id,
        female_animal_id=female2.id, start_date=date.today(),
        is_active=False,   # ignored — both animals are alive, so it counts
    )
    db_session.add_all([active, flagged_inactive])
    db_session.commit()

    rows = queries.count_active_breeding_pairs(db_session)
    assert dict(rows) == {'Mouse': 2}


def test_count_unprocessed_ears_omits_zero_species(db_session):
    """A species with no unlabeled ears is omitted, not shown as 0."""
    species = make_species(db_session, name='Mouse')
    animal = make_animal(db_session, species=species)
    # Only a labeled ear → 0 unlabeled.
    db_session.add(
        Ear(animal_id=animal.id, side='Left', immunolabel_date=date.today())
    )
    # A second species with no ears at all.
    make_species(db_session, name='Gerbil')
    db_session.commit()

    assert queries.count_unprocessed_ears(db_session) == []


def test_count_active_breeding_pairs_requires_both_alive(db_session):
    """An is_active pair with a terminated partner is not counted (and its
    species, having no other active pairs, is omitted)."""
    species = make_species(db_session, name='Mouse')
    male = make_animal(db_session, species=species, sex='male')
    female = make_animal(db_session, species=species, sex='female')
    pair = BreedingPair(
        custom_id='BP-DEAD', male_animal_id=male.id,
        female_animal_id=female.id, start_date=date.today(),
        is_active=True,   # flag left on; not auto-cleared on termination
    )
    db_session.add(pair)
    male.terminate(termination_date=date.today())
    db_session.commit()

    assert queries.count_active_breeding_pairs(db_session) == []
