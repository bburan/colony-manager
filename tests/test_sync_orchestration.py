"""Phase 2 sync tests — end-to-end orchestration against a tmp_path.

Exercises :func:`colony_manager_gui.sync.sync_locations` and
:func:`colony_manager_gui.sync.rematch_datatype` with a real
filesystem layout (via pytest's ``tmp_path``) and the fake
DataTypeDescription classes from ``tests._description_fakes``.

The fakes register two parsers via the standard
``COLONY_MANAGER_DESCRIPTION_REGISTRY`` env var so the production
``load_description_class`` codepath runs unchanged.

Because sync writes through Flask-SQLAlchemy's ``db.session``, every
test wraps the sync call in ``app.app_context()``. The per-test DB
clone keeps state isolated across tests.
"""
import os

import pytest
from sqlalchemy import select

from colony_manager.datatypes import reset_registry_cache
from colony_manager.models import AnimalEvent, AnimalEventData, Data

from .factories import (
    make_animal, make_animal_event_data_type, make_data_location,
    make_procedure, make_procedure_target, make_species,
)


# ---------------------------------------------------------------------------
# Fixtures specific to orchestration tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def description_registry(monkeypatch):
    """Point the description-class registry at ``tests._description_fakes``.

    ``autouse`` so every test in this file gets the fakes; the
    registry cache is reset both before and after to keep stale
    state from a prior conftest run from leaking.
    """
    monkeypatch.setenv(
        'COLONY_MANAGER_DESCRIPTION_REGISTRY', 'tests._description_fakes',
    )
    reset_registry_cache()
    yield
    reset_registry_cache()


def _write_file(directory, name, content='x'):
    """Create ``directory/name`` with ``content`` and return its path."""
    path = directory / name
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# sync_locations — happy path
# ---------------------------------------------------------------------------

def test_sync_locations_creates_data_row_for_matching_file(db_session, app, tmp_path):
    """A file whose name matches an existing animal + event gets persisted
    as an AnimalEventData row linked to that event.
    """
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='M-001')
    procedure = make_procedure(db_session, name='Dissection')
    target = make_procedure_target(db_session)
    from datetime import date as _date
    event = AnimalEvent(
        animal_id=animal.id,
        procedure_id=procedure.id,
        procedure_target_id=target.id,
        scheduled_date=_date(2025, 6, 15),
        completion_date=_date(2025, 6, 15),
    )
    db_session.add(event)
    db_session.commit()

    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event'
    db_session.commit()

    _write_file(tmp_path, 'M-001_2025-06-15.txt')
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)

    with app.app_context():
        totals = sync_locations()
        gui_db.session.commit()

    assert totals['added'] == 1
    assert totals['unmatched'] == 0

    rows = db_session.scalars(select(AnimalEventData)).all()
    assert len(rows) == 1
    assert rows[0].relative_path == 'M-001_2025-06-15.txt'
    assert event in rows[0].events


def test_sync_locations_marks_unmatched_when_no_event_exists(
    db_session, app, tmp_path,
):
    """If the filename parses but no matching event exists, the Data row
    is still added (with empty target relationship) and counted as
    unmatched.
    """
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)

    _write_file(tmp_path, 'NOSUCH-ANIMAL_2025-07-01.txt')

    with app.app_context():
        totals = sync_locations()
        gui_db.session.commit()

    assert totals['added'] == 1
    assert totals['unmatched'] == 1
    rows = db_session.scalars(select(AnimalEventData)).all()
    assert len(rows) == 1
    assert len(rows[0].events) == 0


def test_sync_locations_skips_unparseable_files(
    db_session, app, tmp_path,
):
    """Filenames that don't match the fake parser are ignored entirely
    (no row added, no unmatched count incremented).
    """
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)

    _write_file(tmp_path, 'random-not-a-data-file.txt')

    with app.app_context():
        totals = sync_locations()
        gui_db.session.commit()

    assert totals['added'] == 0
    assert totals['unmatched'] == 0
    assert db_session.scalars(select(Data)).all() == []


def test_sync_locations_skips_already_synced_paths(
    db_session, app, tmp_path,
):
    """Files already represented by an existing Data row aren't re-added."""
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)
    _write_file(tmp_path, 'X-1_2025-06-01.txt')

    with app.app_context():
        first = sync_locations()
        gui_db.session.commit()
    assert first['added'] == 1

    with app.app_context():
        second = sync_locations()
        gui_db.session.commit()

    assert second['added'] == 0
    assert second['skipped'] == 1
    assert len(db_session.scalars(select(AnimalEventData)).all()) == 1


# ---------------------------------------------------------------------------
# sync_locations — dry-run
# ---------------------------------------------------------------------------

def test_sync_locations_dry_run_persists_nothing(
    db_session, app, tmp_path,
):
    from colony_manager_gui.sync import sync_locations

    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)
    _write_file(tmp_path, 'M-001_2025-08-01.txt')

    with app.app_context():
        totals = sync_locations(dry_run=True)

    # Counters still increment in dry-run so the operator can preview,
    # but nothing is committed.
    assert totals['added'] == 1
    assert db_session.scalars(select(Data)).all() == []


# ---------------------------------------------------------------------------
# sync_locations — auto-create
# ---------------------------------------------------------------------------

def test_sync_locations_auto_creates_event_when_enabled(
    db_session, app, tmp_path,
):
    """With ``auto_create=True``, an unmatched file for a known animal
    triggers automatic event creation, then the file links to it.
    """
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='AC-1')
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
        default_procedure_target=target,
    )
    dtype.description_class = 'fake_animal_event'
    dtype.auto_create = True
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)

    _write_file(tmp_path, 'AC-1_2025-09-10.txt')

    with app.app_context():
        totals = sync_locations()
        gui_db.session.commit()

    assert totals['auto_created'] == 1
    events = db_session.scalars(
        select(AnimalEvent).where(AnimalEvent.animal_id == animal.id)
    ).all()
    assert len(events) == 1
    e = events[0]
    from datetime import date as _date
    assert e.scheduled_date == _date(2025, 9, 10)
    assert e.completion_date == _date(2025, 9, 10)
    assert e.procedure_id == procedure.id


# ---------------------------------------------------------------------------
# rematch_datatype
# ---------------------------------------------------------------------------

def test_rematch_links_previously_unmatched_after_animal_created(
    db_session, app, tmp_path,
):
    """A file synced before its animal existed is unmatched; rematch
    after the animal is created should hook it up.
    """
    from colony_manager_gui.sync import sync_locations, rematch_datatype
    from colony_manager_gui import db as gui_db

    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)
    _write_file(tmp_path, 'LATE-1_2025-10-05.txt')

    # First sync: animal doesn't exist yet → unmatched.
    with app.app_context():
        first = sync_locations()
        gui_db.session.commit()
    assert first['unmatched'] == 1
    rows = db_session.scalars(select(AnimalEventData)).all()
    assert len(rows[0].events) == 0

    # Create the animal + event afterward, then rematch.
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='LATE-1')
    from datetime import date as _date
    event = AnimalEvent(
        animal_id=animal.id,
        procedure_id=procedure.id,
        procedure_target_id=target.id,
        scheduled_date=_date(2025, 10, 5),
        completion_date=_date(2025, 10, 5),
    )
    db_session.add(event)
    db_session.commit()

    with app.app_context():
        rm = rematch_datatype(dtype.id, force=False)
        gui_db.session.commit()

    assert rm['matched'] == 1
    db_session.refresh(rows[0])
    assert event in rows[0].events


def test_rematch_force_relinks_all_rows(db_session, app, tmp_path):
    """``force=True`` re-resolves every row, including already-matched."""
    from colony_manager_gui.sync import sync_locations, rematch_datatype
    from colony_manager_gui import db as gui_db

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='F-1')
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    from datetime import date as _date
    event = AnimalEvent(
        animal_id=animal.id,
        procedure_id=procedure.id,
        procedure_target_id=target.id,
        scheduled_date=_date(2025, 11, 1),
        completion_date=_date(2025, 11, 1),
    )
    db_session.add(event)
    db_session.commit()

    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)
    _write_file(tmp_path, 'F-1_2025-11-01.txt')

    with app.app_context():
        sync_locations()
        gui_db.session.commit()
        rm = rematch_datatype(dtype.id, force=True)
        gui_db.session.commit()

    # ``walked`` counts every row we attempted (including already-matched
    # ones because force=True bypasses the unmatched-only filter).
    assert rm['walked'] == 1
    assert rm['matched'] == 1
