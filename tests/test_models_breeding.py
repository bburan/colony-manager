"""Tests for ``BreedingPair`` / ``Litter`` and the related Animal paths.

* Round-trip persistence with the male/female FKs and the offspring
  back-populates.
* ``Litter.age_in_days`` computed from ``dob``.
* ``Animal.source_display`` returns the breeding pair's ``custom_id``
  when the animal was bred in-house — the third branch deferred from
  ``test_models_animal``.
"""
from datetime import date, timedelta

from sqlalchemy import select

from colony_manager.models import Animal, BreedingPair, Litter

from .factories import (
    make_animal, make_breeding_pair, make_litter, make_species,
)


def test_breeding_pair_persists_with_male_female(db_session):
    species = make_species(db_session)
    male = make_animal(db_session, species=species, sex='male')
    female = make_animal(db_session, species=species, sex='female')

    pair = make_breeding_pair(
        db_session, male=male, female=female, custom_id='BP-1',
    )

    fetched = db_session.scalar(
        select(BreedingPair).where(BreedingPair.custom_id == 'BP-1')
    )
    assert fetched.male_animal_id == male.id
    assert fetched.female_animal_id == female.id
    assert fetched.is_active is True  # column default


def test_breeding_pair_offspring_back_populates(db_session):
    species = make_species(db_session)
    pair = make_breeding_pair(db_session, species=species)
    pup = make_animal(db_session, species=species)
    pup.breeding_pair_id = pair.id
    db_session.commit()

    db_session.refresh(pair)
    assert pup in pair.offspring
    assert pup.breeding_pair is pair


def test_litter_age_in_days(db_session):
    pair = make_breeding_pair(db_session)
    litter = make_litter(
        db_session, breeding_pair=pair,
        dob=date.today() - timedelta(days=21),
    )
    assert litter.age_in_days == 21


def test_animal_source_display_uses_breeding_pair_when_bred_in_house(db_session):
    """``source_display`` prefers the breeding pair over any external source.

    The model's branch order: ``breeding_pair`` first, then ``source``,
    then 'N/A'. If both are set the breeding pair wins — that's the
    'bred in-house' semantics.
    """
    species = make_species(db_session)
    pair = make_breeding_pair(db_session, species=species, custom_id='BP-X')
    pup = make_animal(db_session, species=species)
    pup.breeding_pair_id = pair.id
    db_session.commit()
    db_session.refresh(pup)

    assert pup.source_display == 'BP-X'


def test_litter_cascade_delete_when_breeding_pair_deleted(db_session):
    """``BreedingPair.litters`` has ``cascade='all, delete-orphan'``.

    Deleting the pair must remove its litters in the same commit.
    """
    pair = make_breeding_pair(db_session)
    litter = make_litter(db_session, breeding_pair=pair)
    litter_id = litter.id

    db_session.delete(pair)
    db_session.commit()

    assert db_session.get(Litter, litter_id) is None
