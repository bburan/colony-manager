"""Dashboard / list-page query helpers.

These were previously classmethods on ``colony_manager.models.Species``,
which made the library layer reach back into Flask-SQLAlchemy's session.
They're presentation aggregates, not domain logic, so they live in the
GUI layer and take an explicit session argument.
"""
from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased

from colony_manager.models import (
    Animal, BreedingPair, Cage, Ear, Species,
)


def count_active_cages(session):
    """``[(species_name, cage_count), ...]`` for the dashboard top cards.

    A cage counts as active when it has at least one un-terminated animal
    — matching the Cages page's ``status_filter='active'`` definition
    (``Cage.animals.any(Animal.terminated == False)``). Empty cages and
    cages holding only terminated animals are NOT active, so this card
    agrees with the count you get on the Cages page.
    """
    return session.execute(
        select(
            Species.name,
            func.count(func.distinct(Cage.id)),
        )
        .select_from(Cage)
        .join(Species, Cage.species_id == Species.id)
        .join(Animal, Animal.cage_id == Cage.id)
        .where(Animal.terminated == False)  # noqa: E712
        .group_by(Species.id)
    ).all()


def count_active_animals(session):
    """``[(species_name, animal_count), ...]`` for currently-active animals."""
    return session.execute(
        select(
            Species.name,
            func.count(func.distinct(Animal.id)),
        )
        .outerjoin(Species.animals)
        .where(
            and_(
                Animal.terminated == False,  # noqa: E712
                Animal.custom_id.isnot(None),
            )
        )
        .group_by(Species.id)
    ).all()


def count_unprocessed_ears(session):
    """``[(species_name, ear_count), ...]`` for ears awaiting immunolabeling.

    An ear counts as unlabeled when it has no immunolabeling panel
    assigned (``panel_id`` is NULL) — the panel, not the date, is the
    signal, since the date is sometimes left blank even after labeling.
    Inner joins so a species with no unlabeled ears is omitted entirely
    rather than shown with a count of 0.
    """
    return session.execute(
        select(
            Species.name,
            func.count(func.distinct(Ear.id)),
        )
        .join(Species.animals)
        .join(Animal.ears)
        .where(Ear.panel_id.is_(None))
        .group_by(Species.id)
    ).all()


def count_active_breeding_pairs(session):
    """``[(species_name, pair_count), ...]`` for active breeding pairs.

    A pair is active when **both animals are still alive** (un-terminated).
    The ``is_active`` column is intentionally ignored: there is currently no
    UI to edit a breeding pair or toggle that flag, so it's effectively
    always ``True`` and aliveness is the only meaningful signal. Inner joins
    omit species with no active pairs (no 0-count rows).
    """
    male = aliased(Animal)
    female = aliased(Animal)
    return session.execute(
        select(
            Species.name,
            func.count(func.distinct(BreedingPair.id)),
        )
        .select_from(BreedingPair)
        .join(male, BreedingPair.male_animal_id == male.id)
        .join(female, BreedingPair.female_animal_id == female.id)
        .join(Species, male.species_id == Species.id)
        .where(
            male.terminated == False,    # noqa: E712
            female.terminated == False,  # noqa: E712
        )
        .group_by(Species.id)
    ).all()
