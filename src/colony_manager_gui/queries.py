"""Dashboard / list-page query helpers.

These were previously classmethods on ``colony_manager.models.Species``,
which made the library layer reach back into Flask-SQLAlchemy's session.
They're presentation aggregates, not domain logic, so they live in the
GUI layer and take an explicit session argument.
"""
from sqlalchemy import and_, or_, func, select

from colony_manager.models import (
    Animal, BreedingPair, Cage, Ear, Species,
)


def count_active_cages(session):
    """``[(species_name, cage_count), ...]`` for the dashboard top cards.

    A cage counts as active when it has at least one un-terminated
    animal, OR has no animals at all (newly-created empty cage).

    The query starts from Cage and outer-joins to Animal so empty
    cages survive the join (the previous Species-rooted version
    couldn't see them — empty cages have no animal rows to traverse).
    """
    return session.execute(
        select(
            Species.name,
            func.count(func.distinct(Cage.id)),
        )
        .select_from(Cage)
        .join(Species, Cage.species_id == Species.id)
        .outerjoin(Animal, Animal.cage_id == Cage.id)
        .where(
            or_(
                Animal.termination_date.is_(None),
                Animal.id.is_(None),
            )
        )
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
                Animal.termination_date.is_(None),
                Animal.custom_id.isnot(None),
            )
        )
        .group_by(Species.id)
    ).all()


def count_unprocessed_ears(session):
    """``[(species_name, ear_count), ...]`` for ears awaiting immunolabeling."""
    return session.execute(
        select(
            Species.name,
            func.count(func.distinct(Ear.id)),
        )
        .outerjoin(Species.animals)
        .outerjoin(Animal.ears)
        .where(Ear.immunolabel_date.is_(None))
        .group_by(Species.id)
    ).all()


def count_active_breeding_pairs(session):
    """``[(species_name, pair_count), ...]`` for active breeding pairs."""
    return session.execute(
        select(
            Species.name,
            func.count(func.distinct(BreedingPair.id)),
        )
        .outerjoin(Species.animals)
        .outerjoin(
            BreedingPair,
            and_(
                Animal.id == BreedingPair.male_animal_id,
                BreedingPair.is_active == True,  # noqa: E712 — SQL boolean
            ),
        )
        .group_by(Species.id)
    ).all()
