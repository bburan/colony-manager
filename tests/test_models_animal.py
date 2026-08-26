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

from colony_manager.models import Animal, AnimalTag, Ear, WeightLog

from .factories import (
    make_animal, make_breeding_pair, make_cage, make_event, make_source,
    make_species, make_termination_reason,
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
    assert animal.terminated is False


def test_terminate_without_date_marks_terminated(db_session):
    """terminate() with no date sets terminated=True, leaves date as None.

    Supports loading historical data where the exact termination date was
    not recorded.
    """
    animal = make_animal(db_session)
    animal.terminate()
    db_session.commit()
    db_session.refresh(animal)

    assert animal.terminated is True
    assert animal.termination_date is None
    assert animal.is_active is False


def test_terminate_without_date_already_terminated_raises(db_session):
    """A second terminate() call raises even when the first had no date."""
    animal = make_animal(db_session)
    animal.terminate()
    db_session.commit()

    with pytest.raises(ValueError, match='already terminated'):
        animal.terminate()


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


def test_age_display_terminated_shows_age_at_euthanasia(db_session):
    # Born 100 days ago, euthanized 30 days ago -> 70 days old at death,
    # not the 100 chronological days a living animal would show.
    animal = make_animal(db_session, dob=date.today() - timedelta(days=100))
    animal.terminate(termination_date=date.today() - timedelta(days=30))
    db_session.commit()

    assert animal.age_display('day') == '70.0 days (t)'
    assert animal.age_display('week') == '10.0 weeks (t)'


def test_age_display_terminated_without_date_is_unknown(db_session):
    animal = make_animal(db_session, dob=date.today() - timedelta(days=100))
    animal.terminate()  # no termination_date recorded
    db_session.commit()

    assert animal.age_display('day') == 'Unknown (t)'
    assert animal.age_display('month') == 'Unknown (t)'


def test_target_age_date_units(db_session):
    dob = date(2026, 1, 1)
    animal = make_animal(db_session, dob=dob)

    assert animal.target_age_date(56, 'day') == dob + timedelta(days=56)
    # 8 weeks and 56 days land on the same calendar date.
    assert animal.target_age_date(8, 'week') == dob + timedelta(days=56)
    assert animal.target_age_date(2, 'month') == dob + timedelta(days=60)


def test_target_age_date_accepts_string_and_fractional(db_session):
    dob = date(2026, 1, 1)
    animal = make_animal(db_session, dob=dob)

    # The raw query-string value arrives as a str; fractional weeks round
    # to the nearest whole day (1.5 weeks == 10.5 days -> 10 days).
    assert animal.target_age_date('1.5', 'week') == dob + timedelta(days=10)


def test_target_age_date_display_future(db_session):
    dob = date.today()
    animal = make_animal(db_session, dob=dob)
    expected = (dob + timedelta(days=56)).strftime('%Y-%m-%d')
    assert animal.target_age_date_display(8, 'week') == expected


def test_target_age_date_display_past_returns_none(db_session):
    # Target age already behind this animal -> nothing upcoming to show.
    animal = make_animal(db_session, dob=date.today() - timedelta(days=400))
    assert animal.target_age_date_display(8, 'week') is None


def test_target_age_date_display_terminated_returns_none(db_session):
    animal = make_animal(db_session, dob=date.today())
    animal.terminate(termination_date=date.today())
    db_session.commit()
    assert animal.target_age_date_display(8, 'week') is None


def test_is_active_true_until_terminated(db_session):
    animal = make_animal(db_session)
    assert animal.is_active is True

    animal.terminate(termination_date=date.today())
    db_session.commit()
    assert animal.is_active is False


def _empty_animal(db_session):
    """An animal with no assigned ID and no events — i.e. an accidental add."""
    animal = make_animal(db_session)
    animal.custom_id = None
    db_session.commit()
    return animal


def test_is_deletable_true_for_empty_animal(db_session):
    assert _empty_animal(db_session).is_deletable is True


def test_is_deletable_false_with_custom_id(db_session):
    animal = make_animal(db_session, custom_id='HAS-ID')
    assert animal.is_deletable is False


def test_is_deletable_false_with_events(db_session):
    animal = _empty_animal(db_session)
    make_event(db_session, animal=animal)
    assert animal.is_deletable is False


def test_is_deletable_false_when_terminated(db_session):
    animal = _empty_animal(db_session)
    animal.terminate(termination_date=date.today())
    db_session.commit()
    assert animal.is_deletable is False


def test_is_deletable_false_for_breeding_pair_member(db_session):
    pair = make_breeding_pair(db_session)
    male = db_session.get(Animal, pair.male_animal_id)
    male.custom_id = None
    db_session.commit()
    assert male.is_deletable is False


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


def test_tags_relationship_iterates_in_name_order(db_session):
    """``Animal.tags`` has ``order_by='AnimalTag.name'`` so iteration is
    deterministic regardless of which order tags were attached.
    """
    animal = make_animal(db_session)
    # Insert in non-alphabetical order.
    zebra = AnimalTag(name='zebra')
    apple = AnimalTag(name='Apple')
    monkey = AnimalTag(name='Monkey')
    db_session.add_all([zebra, apple, monkey])
    db_session.commit()
    animal.tags = [zebra, monkey, apple]
    db_session.commit()
    db_session.refresh(animal)

    # Postgres sorts case-sensitively by default, so 'Apple' < 'Monkey'
    # < 'zebra' (capital letters sort before lowercase).
    assert [t.name for t in animal.tags] == ['Apple', 'Monkey', 'zebra']


def test_baseline_from_weights_ignores_null_weights(db_session):
    animal = make_animal(db_session)
    # A None-weight row in the middle must not break the run of baselines.
    weights = [
        _weight(animal.id, 0, None, baseline=True),
        _weight(animal.id, 1, 20.0, baseline=True),
        _weight(animal.id, 2, 22.0, baseline=True),
    ]
    assert Animal._baseline_from_weights(weights) == pytest.approx(21.0)
