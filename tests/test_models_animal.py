"""Tests for ``Animal`` model behavior.

Covers:

* ``Animal.terminate()`` — the documented success paths and the two
  ``ValueError`` cases (already terminated; invalid ``ears_extracted``).
* Computed properties that don't issue queries — ``age_in_*``,
  ``is_active``, ``sex_symbol``, ``source_display``, ``display_id``.
* ``Animal._baseline_from_weights`` static method — the algorithm used
  by both the per-instance property and the dashboard bulk path.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from colony_manager.models import Animal, Ear, WeightLog

from .factories import (
    make_animal, make_cage, make_source, make_species,
    make_termination_reason,
)


# ---------------------------------------------------------------------------
# terminate()
# ---------------------------------------------------------------------------

def test_terminate_sets_date_and_reason(db_session):
    animal = make_animal(db_session)
    reason = make_termination_reason(db_session)
    today = date.today()

    new_ears = animal.terminate(termination_date=today, termination_reason=reason)
    db_session.commit()

    assert animal.termination_date == today
    assert animal.termination_reason_id == reason.id
    assert new_ears == []  # no ears requested


@pytest.mark.parametrize('ears_extracted,expected_sides', [
    ('Left', ['Left']),
    ('Right', ['Right']),
    ('Both', ['Left', 'Right']),
    (None, []),
])
def test_terminate_ear_extraction(db_session, ears_extracted, expected_sides):
    animal = make_animal(db_session)
    new_ears = animal.terminate(
        termination_date=date.today(),
        ears_extracted=ears_extracted,
    )
    # ``terminate`` returns Ear instances but doesn't add them to the
    # session itself — the caller is responsible. Mirror what the GUI
    # route does so we can verify the persisted state.
    for ear in new_ears:
        db_session.add(ear)
    db_session.commit()

    sides = sorted(e.side for e in db_session.scalars(
        select(Ear).where(Ear.animal_id == animal.id)
    ).all())
    assert sides == sorted(expected_sides)


def test_terminate_already_terminated_raises(db_session):
    animal = make_animal(db_session)
    animal.terminate(termination_date=date.today())
    db_session.commit()

    with pytest.raises(ValueError, match='already terminated'):
        animal.terminate(termination_date=date.today())


def test_terminate_invalid_ears_value_raises(db_session):
    animal = make_animal(db_session)
    with pytest.raises(ValueError, match='ears_extracted'):
        animal.terminate(
            termination_date=date.today(),
            ears_extracted='Middle',  # not in the accepted set
        )
    # The bad call must not have mutated state.
    assert animal.termination_date is None


# ---------------------------------------------------------------------------
# Computed properties
# ---------------------------------------------------------------------------

def test_age_properties(db_session):
    dob = date.today() - timedelta(days=70)
    animal = make_animal(db_session, dob=dob)

    assert animal.age_in_days == 70
    assert animal.age_in_weeks == pytest.approx(10.0)
    assert animal.age_in_months == pytest.approx(70 / 30)


def test_age_display_units(db_session):
    animal = make_animal(db_session, dob=date.today() - timedelta(days=14))
    assert animal.age_display('day') == '14.0 days'
    assert animal.age_display('week') == '2.0 weeks'


def test_is_active_true_until_terminated(db_session):
    animal = make_animal(db_session)
    assert animal.is_active is True

    animal.terminate(termination_date=date.today())
    db_session.commit()
    assert animal.is_active is False


@pytest.mark.parametrize('sex,symbol', [
    ('male', '♂'),
    ('female', '♀'),
    ('unknown', '?'),
])
def test_sex_symbol(db_session, sex, symbol):
    # ``sex`` is stored as lowercase per the schema; the symbol mapping
    # only recognizes ``male``/``female`` and falls back to ``?`` for
    # everything else.
    animal = make_animal(db_session, sex=sex)
    assert animal.sex_symbol == symbol


def test_source_display_uses_external_source_when_no_breeding_pair(db_session):
    source = make_source(db_session, name='External Vendor')
    animal = make_animal(db_session, source=source)
    assert animal.source_display == 'External Vendor'


def test_source_display_falls_back_to_na(db_session):
    animal = make_animal(db_session)  # no source, no breeding pair
    assert animal.source_display == 'N/A'


def test_display_id_falls_back_to_cage_when_custom_id_missing(db_session):
    cage = make_cage(db_session, custom_id='CAGE-42')
    species = cage.species
    # Build directly so we can leave custom_id None.
    animal = Animal(
        cage_id=cage.id,
        species_id=species.id,
        sex='male',
        dob=date.today() - timedelta(days=30),
        custom_id=None,
    )
    db_session.add(animal)
    db_session.commit()

    assert animal.display_id == 'Animal from CAGE-42'


def test_display_id_uses_custom_id_when_present(db_session):
    animal = make_animal(db_session, custom_id='ABC-1')
    assert animal.display_id == 'ABC-1'


# ---------------------------------------------------------------------------
# _baseline_from_weights
# ---------------------------------------------------------------------------

def _weight(animal_id, day_offset, weight, baseline):
    """Tiny WeightLog factory for the baseline tests.

    The algorithm only reads ``weight`` and ``baseline``; ``date`` is
    used by the caller to order before passing in.
    """
    return WeightLog(
        animal_id=animal_id,
        date=date.today() - timedelta(days=day_offset),
        weight=weight,
        baseline=baseline,
    )


def test_baseline_from_weights_averages_consecutive_baselines(db_session):
    animal = make_animal(db_session)
    # Date desc order, as the method's docstring requires.
    weights = [
        _weight(animal.id, 0, 22.0, baseline=False),  # most recent non-baseline
        _weight(animal.id, 1, 20.0, baseline=True),
        _weight(animal.id, 2, 21.0, baseline=True),
        _weight(animal.id, 3, 18.0, baseline=False),  # older non-baseline; stop here
        _weight(animal.id, 4, 19.0, baseline=True),   # ignored — past a non-baseline
    ]
    assert Animal._baseline_from_weights(weights) == pytest.approx(20.5)


def test_baseline_from_weights_no_baselines_returns_none(db_session):
    animal = make_animal(db_session)
    weights = [_weight(animal.id, i, 20.0, baseline=False) for i in range(3)]
    assert Animal._baseline_from_weights(weights) is None


def test_baseline_from_weights_empty_returns_none(db_session):
    assert Animal._baseline_from_weights([]) is None


def test_baseline_from_weights_ignores_null_weights(db_session):
    animal = make_animal(db_session)
    # A None-weight row in the middle must not break the run of baselines.
    weights = [
        _weight(animal.id, 0, None, baseline=True),
        _weight(animal.id, 1, 20.0, baseline=True),
        _weight(animal.id, 2, 22.0, baseline=True),
    ]
    assert Animal._baseline_from_weights(weights) == pytest.approx(21.0)
