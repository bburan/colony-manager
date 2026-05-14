"""Lightweight factories for building model instances in tests.

Hand-rolled (no factory-boy) to keep the dependency footprint small.
Each helper takes an explicit ``session`` and commits, so callers can
verify the result via fresh queries without juggling flush/commit
state. Default values are minimal — supply only what your test cares
about, and let the rest pick sensible defaults.

Example::

    def test_thing(db_session):
        species = make_species(db_session)
        cage = make_cage(db_session, species=species)
        animal = make_animal(db_session, cage=cage, species=species)
        ...
"""
from datetime import date, timedelta
from itertools import count

from colony_manager.models import (
    Animal, AnimalEvent, AnimalProcedure, AnimalProcedureTarget,
    BreedingPair, Cage, Ear, Litter, Source, Species,
    TerminationReason, User,
)


# Unique-suffix generators so tests within a session don't collide on
# UNIQUE constraints when they reuse the default ``name`` / ``custom_id``.
_species_seq = count(1)
_source_seq = count(1)
_cage_seq = count(1)
_animal_seq = count(1)
_termination_reason_seq = count(1)
_procedure_seq = count(1)
_procedure_target_seq = count(1)


def make_species(session, name=None):
    obj = Species(name=name or f'Species {next(_species_seq)}')
    session.add(obj)
    session.commit()
    return obj


def make_source(session, name=None):
    obj = Source(name=name or f'Source {next(_source_seq)}')
    session.add(obj)
    session.commit()
    return obj


def make_cage(session, *, species=None, custom_id=None, notes=None):
    species = species or make_species(session)
    obj = Cage(
        custom_id=custom_id or f'C{next(_cage_seq):03d}',
        species_id=species.id,
        notes=notes,
    )
    session.add(obj)
    session.commit()
    return obj


def make_animal(
    session, *, cage=None, species=None, sex='male',
    dob=None, custom_id=None, source=None,
):
    """Build an Animal. Auto-creates cage/species if not supplied."""
    if cage is None and species is None:
        species = make_species(session)
        cage = make_cage(session, species=species)
    elif cage is None:
        cage = make_cage(session, species=species)
    elif species is None:
        species = cage.species

    obj = Animal(
        cage_id=cage.id,
        species_id=species.id,
        sex=sex,
        dob=dob or date.today() - timedelta(days=90),
        custom_id=custom_id or f'A{next(_animal_seq):04d}',
        source_id=source.id if source else None,
    )
    session.add(obj)
    session.commit()
    return obj


def make_termination_reason(session, name=None):
    obj = TerminationReason(
        name=name or f'Reason {next(_termination_reason_seq)}',
    )
    session.add(obj)
    session.commit()
    return obj


def make_procedure(session, name=None, parent=None):
    obj = AnimalProcedure(
        name=name or f'Procedure {next(_procedure_seq)}',
        parent_id=parent.id if parent else None,
    )
    session.add(obj)
    session.commit()
    return obj


def make_procedure_target(session, name=None, requires_side=False):
    obj = AnimalProcedureTarget(
        name=name or f'Target {next(_procedure_target_seq)}',
        requires_side=requires_side,
    )
    session.add(obj)
    session.commit()
    return obj


def make_breeding_pair(
    session, *, male=None, female=None, custom_id=None,
    start_date=None, species=None,
):
    """Build a BreedingPair. Auto-creates male/female if not supplied."""
    species = species or make_species(session)
    if male is None:
        male = make_animal(session, species=species, sex='male')
    if female is None:
        female = make_animal(session, species=species, sex='female')
    obj = BreedingPair(
        custom_id=custom_id or f'BP{next(_cage_seq):03d}',
        start_date=start_date or date.today() - timedelta(days=30),
        male_animal_id=male.id,
        female_animal_id=female.id,
    )
    session.add(obj)
    session.commit()
    return obj


def make_litter(session, *, breeding_pair=None, dob=None, pup_count=4):
    breeding_pair = breeding_pair or make_breeding_pair(session)
    obj = Litter(
        breeding_pair_id=breeding_pair.id,
        dob=dob or date.today() - timedelta(days=14),
        pup_count=pup_count,
    )
    session.add(obj)
    session.commit()
    return obj


def make_user(
    session, *, email=None, first_name='Test', last_name='User',
    password='secret', active=True, admin=False,
):
    obj = User(
        email=email or f'user{next(_animal_seq)}@example.com',
        first_name=first_name,
        last_name=last_name,
        active=active,
        admin=admin,
    )
    obj.set_password(password)
    session.add(obj)
    session.commit()
    return obj


def make_event(
    session, *, animal, procedure=None, procedure_target=None,
    scheduled_date=None, completion_date=None, side=None,
):
    procedure = procedure or make_procedure(session)
    procedure_target = procedure_target or make_procedure_target(session)
    obj = AnimalEvent(
        animal_id=animal.id,
        procedure_id=procedure.id,
        procedure_target_id=procedure_target.id,
        scheduled_date=scheduled_date or date.today(),
        completion_date=completion_date,
        side=side,
    )
    session.add(obj)
    session.commit()
    return obj
