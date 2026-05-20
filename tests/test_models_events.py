"""Tests for ``AnimalEvent`` properties and Animal's event aggregations.

Covers the display-state machine driven by ``scheduled_date`` vs.
``completion_date`` (the GUI's events accordion + dashboard rely on
these), and the three Python-side collection properties on Animal
(``events_by_date``, ``scheduled_events``, ``completed_events``).
"""
from datetime import date, timedelta

from .factories import make_animal, make_event, make_procedure


# ---------------------------------------------------------------------------
# AnimalEvent.status
# ---------------------------------------------------------------------------

def test_event_status_complete(db_session):
    animal = make_animal(db_session)
    event = make_event(
        db_session, animal=animal,
        scheduled_date=date.today() - timedelta(days=1),
        completion_date=date.today(),
    )
    assert event.status == 'complete'


def test_event_status_overdue(db_session):
    animal = make_animal(db_session)
    event = make_event(
        db_session, animal=animal,
        scheduled_date=date.today() - timedelta(days=2),
        completion_date=None,
    )
    assert event.status == 'overdue'


def test_event_status_due(db_session):
    animal = make_animal(db_session)
    event = make_event(
        db_session, animal=animal,
        scheduled_date=date.today(),
        completion_date=None,
    )
    assert event.status == 'due'


def test_event_status_future_is_blank(db_session):
    animal = make_animal(db_session)
    event = make_event(
        db_session, animal=animal,
        scheduled_date=date.today() + timedelta(days=7),
        completion_date=None,
    )
    assert event.status == ''


def test_event_status_complete_wins_over_overdue(db_session):
    """A completed event in the past is 'complete', not 'overdue'."""
    animal = make_animal(db_session)
    event = make_event(
        db_session, animal=animal,
        scheduled_date=date.today() - timedelta(days=30),
        completion_date=date.today() - timedelta(days=20),
    )
    assert event.status == 'complete'


# ---------------------------------------------------------------------------
# AnimalEvent.date
# ---------------------------------------------------------------------------

def test_event_date_uses_completion_when_set(db_session):
    animal = make_animal(db_session)
    completed_on = date.today() - timedelta(days=5)
    event = make_event(
        db_session, animal=animal,
        scheduled_date=date.today() - timedelta(days=10),
        completion_date=completed_on,
    )
    assert event.date == completed_on


def test_event_date_falls_back_to_scheduled_when_pending(db_session):
    animal = make_animal(db_session)
    scheduled_for = date.today() + timedelta(days=3)
    event = make_event(
        db_session, animal=animal,
        scheduled_date=scheduled_for,
        completion_date=None,
    )
    assert event.date == scheduled_for


# ---------------------------------------------------------------------------
# Animal.events_by_date
# ---------------------------------------------------------------------------

def test_events_by_date_groups_by_effective_date(db_session):
    """Each group key is the effective ``date`` (completion or scheduled).

    Within a group, events are sorted by procedure name.
    """
    animal = make_animal(db_session)
    proc_a = make_procedure(db_session, name='AAA Procedure')
    proc_b = make_procedure(db_session, name='BBB Procedure')

    today = date.today()
    yesterday = today - timedelta(days=1)

    e_today_b = make_event(
        db_session, animal=animal, procedure=proc_b,
        scheduled_date=today,
    )
    e_today_a = make_event(
        db_session, animal=animal, procedure=proc_a,
        scheduled_date=today,
    )
    e_yesterday = make_event(
        db_session, animal=animal, procedure=proc_a,
        scheduled_date=yesterday - timedelta(days=2),
        completion_date=yesterday,
    )

    grouped = animal.events_by_date

    # Date ordering: ascending by effective date (sorted() over keys).
    assert list(grouped.keys()) == [yesterday, today]

    # Today's group sorted by procedure name (AAA before BBB).
    assert grouped[today] == [e_today_a, e_today_b]
    assert grouped[yesterday] == [e_yesterday]


def test_events_by_date_empty_for_animal_without_events(db_session):
    animal = make_animal(db_session)
    assert animal.events_by_date == {}


# ---------------------------------------------------------------------------
# Animal.scheduled_events / completed_events
# ---------------------------------------------------------------------------

def test_scheduled_events_excludes_completed_and_sorts_ascending(db_session):
    animal = make_animal(db_session)
    near = make_event(
        db_session, animal=animal,
        scheduled_date=date.today() + timedelta(days=1),
        completion_date=None,
    )
    far = make_event(
        db_session, animal=animal,
        scheduled_date=date.today() + timedelta(days=10),
        completion_date=None,
    )
    done = make_event(  # noqa: F841 — must not appear in scheduled
        db_session, animal=animal,
        scheduled_date=date.today() - timedelta(days=5),
        completion_date=date.today() - timedelta(days=1),
    )

    scheduled = animal.scheduled_events
    assert scheduled == [near, far]


def test_completed_events_excludes_pending_and_sorts_ascending(db_session):
    animal = make_animal(db_session)
    earlier = make_event(
        db_session, animal=animal,
        scheduled_date=date.today() - timedelta(days=10),
        completion_date=date.today() - timedelta(days=8),
    )
    later = make_event(
        db_session, animal=animal,
        scheduled_date=date.today() - timedelta(days=5),
        completion_date=date.today() - timedelta(days=1),
    )
    pending = make_event(  # noqa: F841 — must not appear in completed
        db_session, animal=animal,
        scheduled_date=date.today() + timedelta(days=2),
        completion_date=None,
    )

    completed = animal.completed_events
    assert completed == [earlier, later]


# ---------------------------------------------------------------------------
# AnimalEvent.tags — sqlalchemy_continuum M2M versioning regression
# ---------------------------------------------------------------------------

def test_event_with_initial_tags_commits_cleanly(db_session):
    """Creating an event with one or more tags must not raise.

    Regression: ``sqlalchemy_continuum.make_versioned`` was being
    called twice on process startup — once in ``colony_manager.db``
    and once in ``colony_manager_gui/__init__.py`` — which registered
    continuum's ``after_flush`` listener twice. Every M2M assignment
    then generated two identical INSERTs into
    ``animal_event_tags_version`` with the same
    ``(animal_event_id, tag_id, transaction_id)``, hitting
    ``pk_animal_event_tags_version``.
    """
    from colony_manager.models import AnimalEventTag

    animal = make_animal(db_session)
    procedure = make_procedure(db_session)
    tag_a = AnimalEventTag(name='alpha')
    tag_b = AnimalEventTag(name='beta')
    db_session.add_all([tag_a, tag_b])
    db_session.commit()

    event = make_event(
        db_session, animal=animal, procedure=procedure,
        scheduled_date=date.today(),
    )
    event.tags = [tag_a, tag_b]
    db_session.commit()  # must not raise IntegrityError

    db_session.expire_all()
    refreshed = db_session.get(type(event), event.id)
    assert {t.name for t in refreshed.tags} == {'alpha', 'beta'}


def test_event_tag_reassignment_commits_cleanly(db_session):
    """Replacing an event's tag list (the ``populate_obj`` flow used by
    ``update_animal_event``) must not raise.

    Same regression as above (double ``make_versioned``); this case
    exercises the reassignment path that a real edit form takes:
    load → ``event.tags = new_list`` → commit.
    """
    from colony_manager.models import AnimalEventTag

    animal = make_animal(db_session)
    procedure = make_procedure(db_session)
    tag_a = AnimalEventTag(name='alpha')
    tag_b = AnimalEventTag(name='beta')
    tag_c = AnimalEventTag(name='gamma')
    db_session.add_all([tag_a, tag_b, tag_c])
    db_session.commit()

    event = make_event(
        db_session, animal=animal, procedure=procedure,
        scheduled_date=date.today(),
    )
    event.tags = [tag_a, tag_b]
    db_session.commit()

    # The actual regression trigger: reassign to an overlapping but
    # different set, mimicking what ``form.populate_obj(event)`` does.
    event.tags = [tag_b, tag_c]
    db_session.commit()  # must not raise IntegrityError

    db_session.expire_all()
    refreshed = db_session.get(type(event), event.id)
    assert {t.name for t in refreshed.tags} == {'beta', 'gamma'}
