"""Tests for ``Animal.get_daily_logs``.

The method powers the dashboard's weight + feed table. It returns a
dict keyed by Animal (sorted by display_id) whose value is a list of
day-slot dicts spanning the configured date window. Each slot can
hold a WeightLog and any FeedLogs for that day.

After the refactor the method takes an explicit ``session`` argument.
"""
from datetime import date, timedelta

from colony_manager.models import Animal

from .factories import (
    make_animal, make_feed, make_feed_log, make_species, make_weight_log,
)


# ---------------------------------------------------------------------------
# Window shape
# ---------------------------------------------------------------------------

def test_empty_input_returns_empty_dict(db_session):
    """No animals → no rows joined → empty dict."""
    make_animal(db_session)  # exists but has no weights/feeds
    result = Animal.get_daily_logs(db_session)
    assert result == {}


def test_window_has_one_slot_per_day(db_session):
    """``before=2, after=1`` over today is a 4-day window."""
    animal = make_animal(db_session)
    today = date.today()
    make_weight_log(db_session, animal=animal, date=today, weight=22.0)

    result = Animal.get_daily_logs(db_session, before=2, after=1)
    days = result[animal]
    assert len(days) == 4
    assert [d['date'] for d in days] == [
        today - timedelta(days=2),
        today - timedelta(days=1),
        today,
        today + timedelta(days=1),
    ]


def test_reference_date_overrides_today(db_session):
    """Passing ``reference_date`` shifts the window without using today."""
    animal = make_animal(db_session)
    anchor = date(2025, 6, 15)
    make_weight_log(db_session, animal=animal, date=anchor, weight=20.0)

    result = Animal.get_daily_logs(
        db_session, reference_date=anchor, before=1, after=1,
    )
    days = result[animal]
    assert [d['date'] for d in days] == [
        date(2025, 6, 14),
        date(2025, 6, 15),
        date(2025, 6, 16),
    ]


# ---------------------------------------------------------------------------
# Weight placement
# ---------------------------------------------------------------------------

def test_weight_placed_in_correct_slot(db_session):
    animal = make_animal(db_session)
    today = date.today()
    weight = make_weight_log(
        db_session, animal=animal,
        date=today - timedelta(days=1),
        weight=21.5,
    )

    result = Animal.get_daily_logs(db_session, before=2, after=0)
    days = result[animal]
    assert days[0]['weight'] is None       # 2 days ago — empty
    assert days[1]['weight'] is weight     # 1 day ago — populated
    assert days[2]['weight'] is None       # today — empty


def test_weight_outside_window_excluded(db_session):
    animal = make_animal(db_session)
    today = date.today()
    # Far past — outside the requested ``before=1`` window.
    make_weight_log(
        db_session, animal=animal,
        date=today - timedelta(days=30),
        weight=19.0,
    )
    # Inside the window — should appear.
    inside = make_weight_log(
        db_session, animal=animal,
        date=today,
        weight=22.0,
    )

    result = Animal.get_daily_logs(db_session, before=1, after=0)
    days = result[animal]
    assert days[0]['weight'] is None
    assert days[1]['weight'] is inside


# ---------------------------------------------------------------------------
# Feed aggregation
# ---------------------------------------------------------------------------

def test_feed_log_aggregates_total_grams(db_session):
    """``total_feed`` is quantity × per-pellet weight, summed per day."""
    animal = make_animal(db_session)
    feed_a = make_feed(db_session, weight=0.5)
    feed_b = make_feed(db_session, weight=1.0)
    today = date.today()

    make_feed_log(db_session, animal=animal, feed=feed_a, date=today, quantity=3)
    make_feed_log(db_session, animal=animal, feed=feed_b, date=today, quantity=2)

    result = Animal.get_daily_logs(db_session, before=0, after=0)
    day = result[animal][0]
    # 3 * 0.5  +  2 * 1.0  =  3.5g total feed
    assert day['total_feed'] == 3.5
    assert len(day['feeds']) == 2


def test_feed_log_in_separate_days_does_not_bleed(db_session):
    animal = make_animal(db_session)
    feed = make_feed(db_session, weight=0.5)
    today = date.today()
    yesterday = today - timedelta(days=1)

    make_feed_log(db_session, animal=animal, feed=feed, date=today, quantity=4)
    make_feed_log(db_session, animal=animal, feed=feed, date=yesterday, quantity=2)

    result = Animal.get_daily_logs(db_session, before=1, after=0)
    days = result[animal]
    assert days[0]['total_feed'] == 1.0   # yesterday: 2 * 0.5
    assert days[1]['total_feed'] == 2.0   # today: 4 * 0.5


# ---------------------------------------------------------------------------
# Multi-animal behavior
# ---------------------------------------------------------------------------

def test_animals_sorted_by_display_id(db_session):
    species = make_species(db_session)
    today = date.today()

    z = make_animal(db_session, species=species, custom_id='Z-001')
    a = make_animal(db_session, species=species, custom_id='A-001')
    m = make_animal(db_session, species=species, custom_id='M-001')

    for animal in (z, a, m):
        make_weight_log(db_session, animal=animal, date=today, weight=20.0)

    result = Animal.get_daily_logs(db_session, before=0, after=0)
    assert [a.display_id for a in result.keys()] == ['A-001', 'M-001', 'Z-001']


def test_species_filter_excludes_other_species(db_session):
    mouse = make_species(db_session, name='Mouse-only')
    gerbil = make_species(db_session, name='Gerbil-only')
    today = date.today()

    mouse_animal = make_animal(db_session, species=mouse)
    gerbil_animal = make_animal(db_session, species=gerbil)
    make_weight_log(db_session, animal=mouse_animal, date=today, weight=18.0)
    make_weight_log(db_session, animal=gerbil_animal, date=today, weight=60.0)

    result = Animal.get_daily_logs(
        db_session, before=0, after=0, species=mouse,
    )
    assert list(result.keys()) == [mouse_animal]


# ---------------------------------------------------------------------------
# Baseline cache priming
# ---------------------------------------------------------------------------

def test_baseline_weight_cache_populated(db_session):
    """``get_daily_logs`` primes ``_baseline_weight_cached`` on each animal.

    Without this priming, the dashboard's per-cell ``animal.baseline_weight``
    reads would each fire a separate query.
    """
    animal = make_animal(db_session)
    today = date.today()
    # Two consecutive baselines, then a normal weight.
    make_weight_log(
        db_session, animal=animal,
        date=today - timedelta(days=2),
        weight=20.0, baseline=True,
    )
    make_weight_log(
        db_session, animal=animal,
        date=today - timedelta(days=1),
        weight=22.0, baseline=True,
    )
    make_weight_log(
        db_session, animal=animal,
        date=today, weight=21.0, baseline=False,
    )

    result = Animal.get_daily_logs(db_session, before=3, after=0)
    populated_animal = next(iter(result.keys()))
    assert populated_animal._baseline_weight_cached == 21.0  # mean(20, 22)


def test_baseline_cache_none_when_no_baselines(db_session):
    animal = make_animal(db_session)
    today = date.today()
    make_weight_log(
        db_session, animal=animal, date=today,
        weight=21.0, baseline=False,
    )

    result = Animal.get_daily_logs(db_session, before=0, after=0)
    populated_animal = next(iter(result.keys()))
    assert populated_animal._baseline_weight_cached is None
