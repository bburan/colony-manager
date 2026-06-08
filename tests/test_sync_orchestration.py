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
from colony_manager.enums import DataStatus
from colony_manager.models import AnimalEvent, AnimalEventData, AnimalData, Data

from .factories import (
    make_animal, make_animal_data_type, make_animal_event_data_type,
    make_data_location, make_procedure, make_procedure_target, make_species,
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


def test_intra_location_move_does_not_re_flag_as_missing(
    db_session, app, tmp_path,
):
    """Regression: a hash-matched rename within the same DataLocation
    used to leave the row stamped 'missing' after the move-recovery
    branch had already set it to 'unreviewed'. The missing-pass at
    the end of ``_sync_location`` was iterating ``existing_by_path``,
    whose keys are the *original* relative paths captured at the top
    of the sync, so for every moved row it stat()'d the old path,
    found nothing there, and re-flagged the row missing.

    Fix: when applying a MOVE, drop the old path from
    ``existing_by_path`` so the missing-pass doesn't see it.
    """
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event_hashed'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='MV-1')
    from datetime import date as _date
    event = AnimalEvent(
        animal_id=animal.id,
        procedure_id=procedure.id,
        procedure_target_id=target.id,
        scheduled_date=_date(2025, 12, 1),
        completion_date=_date(2025, 12, 1),
    )
    db_session.add(event)
    db_session.commit()

    # First sync: pick up a file at its original path.
    src = _write_file(tmp_path, 'MV-1_2025-12-01.txt', content='abr-data-payload')
    with app.app_context():
        first = sync_locations()
        gui_db.session.commit()
    assert first['added'] == 1
    assert first['missing'] == 0

    db_session.expire_all()
    row = db_session.scalars(select(AnimalEventData)).one()
    assert row.relative_path == 'MV-1_2025-12-01.txt'
    assert row.status == DataStatus.UNREVIEWED
    original_id = row.id
    original_hash = row.file_hash
    assert original_hash, 'file_hash should be populated by the hashing fake'

    # Rename the file on disk to a new path (same content → same hash).
    new_path = tmp_path / 'subdir' / 'MV-1_2025-12-01.txt'
    new_path.parent.mkdir(parents=True, exist_ok=True)
    src.rename(new_path)

    # Second sync: detect MOVE, update the existing row, do NOT flag
    # missing.
    with app.app_context():
        second = sync_locations()
        gui_db.session.commit()
    assert second['moved'] == 1
    assert second['missing'] == 0, (
        f'expected 0 missing after intra-location move, got '
        f'{second["missing"]}: {second}'
    )

    db_session.expire_all()
    row = db_session.get(AnimalEventData, original_id)
    assert row is not None
    assert row.relative_path == 'subdir/MV-1_2025-12-01.txt'
    assert row.status == DataStatus.UNREVIEWED  # not 'missing'!
    assert row.file_hash == original_hash


def test_sync_recovers_missing_row_when_file_reappears(
    db_session, app, tmp_path,
):
    """Regression: a Data row stuck in ``status='missing'`` from a
    previous sync should flip back to ``'unreviewed'`` when the file
    is found on disk at the same ``relative_path`` again.

    Before the fix, the walk's "relative_path in existing_by_path"
    branch did ``counts['skipped'] += 1; continue`` without inspecting
    the row's status. The missing-pass at the end of _sync_location
    also skipped the row because the file exists now — its condition
    is ``not os.path.exists(full) and status != 'missing'``. Result:
    rows were never auto-recovered.
    """
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event'
    db_session.commit()
    location = make_data_location(
        db_session, datatype=dtype, base_path=tmp_path,
    )

    # File exists on disk at the path the row claims.
    _write_file(tmp_path, 'REC-1_2025-12-08.txt', content='whatever')

    # Pre-seed a Data row in 'missing' state pointing at that file
    # (this is the steady-state any pre-fix sync left behind for
    # files that had been MOVE'd then re-flagged by the bad
    # missing-pass).
    from colony_manager.models import AnimalEventData
    stuck = AnimalEventData(
        datatype_id=dtype.id,
        location_id=location.id,
        relative_path='REC-1_2025-12-08.txt',
        name='REC-1_2025-12-08.txt',
        status=DataStatus.MISSING,
    )
    db_session.add(stuck)
    db_session.commit()
    stuck_id = stuck.id

    with app.app_context():
        totals = sync_locations()
        gui_db.session.commit()

    assert totals['recovered'] == 1
    assert totals['missing'] == 0

    db_session.expire_all()
    refreshed = db_session.get(AnimalEventData, stuck_id)
    assert refreshed.status == 'unreviewed'


def test_sync_does_not_recover_when_file_actually_missing(
    db_session, app, tmp_path,
):
    """A row marked 'missing' whose file is NOT on disk stays missing."""
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    procedure = make_procedure(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event'
    db_session.commit()
    location = make_data_location(
        db_session, datatype=dtype, base_path=tmp_path,
    )

    # Row claims a path that does NOT exist on disk.
    from colony_manager.models import AnimalEventData
    stuck = AnimalEventData(
        datatype_id=dtype.id,
        location_id=location.id,
        relative_path='GONE-1_2025-12-08.txt',
        name='GONE-1_2025-12-08.txt',
        status=DataStatus.MISSING,
    )
    db_session.add(stuck)
    db_session.commit()
    stuck_id = stuck.id

    with app.app_context():
        totals = sync_locations()
        gui_db.session.commit()

    # No recovery; row stays missing. Missing-pass also doesn't re-
    # increment 'missing' because status is already 'missing'.
    assert totals['recovered'] == 0
    assert totals['missing'] == 0

    db_session.expire_all()
    refreshed = db_session.get(AnimalEventData, stuck_id)
    assert refreshed.status == DataStatus.MISSING


def test_move_re_resolves_targets_when_animal_id_changes(
    db_session, app, tmp_path,
):
    """A hash-matched rename whose new filename parses to a different
    animal must re-link the row to the new animal's event, refresh
    parsed_metadata, and update the file-stat timestamps.

    Real-world: an admin renames ``G011-1 abr_io`` to ``G011-4 abr_io``
    because the original animal label was wrong. The Data row should
    no longer be associated with G011-1's event.
    """
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    dtype.description_class = 'fake_animal_event_hashed'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)

    species = make_species(db_session)
    old_animal = make_animal(db_session, species=species, custom_id='OLD-1')
    new_animal = make_animal(db_session, species=species, custom_id='NEW-1')

    from datetime import date as _date
    on = _date(2025, 12, 5)
    old_event = AnimalEvent(
        animal_id=old_animal.id,
        procedure_id=procedure.id,
        procedure_target_id=target.id,
        scheduled_date=on, completion_date=on,
    )
    new_event = AnimalEvent(
        animal_id=new_animal.id,
        procedure_id=procedure.id,
        procedure_target_id=target.id,
        scheduled_date=on, completion_date=on,
    )
    db_session.add_all([old_event, new_event])
    db_session.commit()
    old_event_id, new_event_id = old_event.id, new_event.id

    # First sync: file named after OLD-1.
    src = _write_file(tmp_path, 'OLD-1_2025-12-05.txt', content='abr-payload')
    with app.app_context():
        sync_locations()
        gui_db.session.commit()

    db_session.expire_all()
    row = db_session.scalars(select(AnimalEventData)).one()
    row_id = row.id
    assert row.parsed_metadata['animal_id'] == 'OLD-1'
    assert old_event_id in {e.id for e in row.events}
    assert new_event_id not in {e.id for e in row.events}
    initial_mtime = row.mtime

    # Rename the file (same content → same hash) so the new filename
    # parses to NEW-1.
    new_path = tmp_path / 'NEW-1_2025-12-05.txt'
    src.rename(new_path)

    # Bump the file's mtime so we can assert the row's mtime updates.
    import os
    import time as _time
    later = _time.time() + 60
    os.utime(new_path, (later, later))

    with app.app_context():
        totals = sync_locations()
        gui_db.session.commit()
    assert totals['moved'] == 1
    assert totals['missing'] == 0

    db_session.expire_all()
    row = db_session.get(AnimalEventData, row_id)
    # Path + name reflect the rename.
    assert row.relative_path == 'NEW-1_2025-12-05.txt'
    assert row.name == 'NEW-1_2025-12-05.txt'
    # parsed_metadata reflects the NEW animal id.
    assert row.parsed_metadata['animal_id'] == 'NEW-1'
    # Targets re-resolved: row is linked to NEW-1's event, not OLD-1's.
    linked = {e.id for e in row.events}
    assert new_event_id in linked
    assert old_event_id not in linked
    # mtime picked up the bump.
    assert row.mtime != initial_mtime


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


def test_animal_datatype_move_same_animal_no_integrity_error(
    db_session, app, tmp_path,
):
    """Regression: moving a surgery-photo file (AnimalDataType, hashed) where
    the new filename parses to the SAME animal must not raise a
    UniqueViolation on ``animal_data_targets_version``.

    Real-world: a file is renamed (e.g. directory reorganization) but
    still belongs to the same animal. The MOVE branch in ``_sync_location``
    calls ``match_targets`` (which triggers an autoflush), then assigns
    ``hash_match.animals = list(new_targets)``.  When the animals list is
    unchanged (old == new), ``bulk_replace`` should detect no diff and emit
    no version events — avoiding a duplicate-key insert into
    ``animal_data_targets_version``.
    """
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='SRG-1')
    db_session.commit()

    dtype = make_animal_data_type(db_session)
    dtype.description_class = 'fake_animal_hashed'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)

    # First sync: file named for animal SRG-1.
    src = _write_file(tmp_path, 'SRG-1.jpg', content='surgery-photo-content')

    with app.app_context():
        sync_locations()
        gui_db.session.commit()

    db_session.expire_all()
    row = db_session.scalars(select(AnimalData)).one()
    assert row.relative_path == 'SRG-1.jpg'
    assert animal in row.animals
    row_id = row.id
    original_hash = row.file_hash
    assert original_hash

    # Rename the file to a new path/name — same content (same hash), same
    # animal id embedded in the filename.
    new_src = tmp_path / 'subdir' / 'SRG-1.jpg'
    new_src.parent.mkdir(parents=True, exist_ok=True)
    src.rename(new_src)

    # Second sync must not raise IntegrityError.
    with app.app_context():
        totals = sync_locations()
        gui_db.session.commit()

    assert totals['moved'] == 1

    db_session.expire_all()
    row = db_session.get(AnimalData, row_id)
    assert row.relative_path == 'subdir/SRG-1.jpg'
    assert animal in row.animals


def test_animal_datatype_move_different_animal_no_integrity_error(
    db_session, app, tmp_path,
):
    """Regression: moving a surgery-photo file where the new filename parses
    to a DIFFERENT animal must re-link the AnimalData row and not raise a
    UniqueViolation on ``animal_data_targets_version``.
    """
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    species = make_species(db_session)
    old_animal = make_animal(db_session, species=species, custom_id='SRG-OLD')
    new_animal = make_animal(db_session, species=species, custom_id='SRG-NEW')
    db_session.commit()

    dtype = make_animal_data_type(db_session)
    dtype.description_class = 'fake_animal_hashed'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)

    # First sync: file for SRG-OLD.
    src = _write_file(tmp_path, 'SRG-OLD.jpg', content='surgery-photo-payload')

    with app.app_context():
        sync_locations()
        gui_db.session.commit()

    db_session.expire_all()
    row = db_session.scalars(select(AnimalData)).one()
    assert old_animal in row.animals
    row_id = row.id

    # Rename to SRG-NEW (same content/hash, different animal in filename).
    new_src = tmp_path / 'SRG-NEW.jpg'
    src.rename(new_src)

    with app.app_context():
        totals = sync_locations()
        gui_db.session.commit()

    assert totals['moved'] == 1

    db_session.expire_all()
    row = db_session.get(AnimalData, row_id)
    assert new_animal in row.animals
    assert old_animal not in row.animals


def test_animal_datatype_move_with_other_new_files_no_integrity_error(
    db_session, app, tmp_path,
):
    """Regression: when a MOVE is processed and other new files follow in the
    same scan, the autoflush triggered by the next file's ``match_targets``
    call must not fail with UniqueViolation on ``animal_data_targets_version``.

    Setup:
    - Animal SRG-2 has a previously synced photo (AnimalData row exists).
    - The photo file is moved to a subdirectory.
    - A second unrelated photo (SRG-3) is NEW (never synced).
    - Second sync must process the MOVE for SRG-2 and then add SRG-3 without
      hitting a PK violation when SRG-3's ``match_targets`` triggers the
      deferred autoflush that writes the MOVE's version records.
    """
    from colony_manager_gui.sync import sync_locations
    from colony_manager_gui import db as gui_db

    species = make_species(db_session)
    animal2 = make_animal(db_session, species=species, custom_id='SRG-2')
    animal3 = make_animal(db_session, species=species, custom_id='SRG-3')
    db_session.commit()

    dtype = make_animal_data_type(db_session)
    dtype.description_class = 'fake_animal_hashed'
    db_session.commit()
    make_data_location(db_session, datatype=dtype, base_path=tmp_path)

    # First sync: SRG-2 photo only.
    src2 = _write_file(tmp_path, 'SRG-2.jpg', content='srg2-unique-payload')

    with app.app_context():
        sync_locations()
        gui_db.session.commit()

    db_session.expire_all()
    row2 = db_session.scalars(select(AnimalData)).one()
    assert animal2 in row2.animals
    row2_id = row2.id

    # Move SRG-2 photo into a subdirectory (same content → same hash).
    moved_src2 = tmp_path / 'archive' / 'SRG-2.jpg'
    moved_src2.parent.mkdir(parents=True, exist_ok=True)
    src2.rename(moved_src2)

    # Add a new SRG-3 photo that will appear AFTER the MOVE in the scan order.
    # The naming ensures SRG-3 sorts after archive/SRG-2 alphabetically
    # in os.walk results; if it doesn't, the test is still valid (just
    # exercises the reverse order — both orders should work).
    _write_file(tmp_path, 'SRG-3.jpg', content='srg3-unique-payload')

    # Second sync: MOVE of SRG-2 + new file SRG-3.  Must not raise.
    with app.app_context():
        totals = sync_locations()
        gui_db.session.commit()

    assert totals['moved'] == 1
    assert totals['added'] == 1

    db_session.expire_all()
    row2 = db_session.get(AnimalData, row2_id)
    assert row2.relative_path == 'archive/SRG-2.jpg'
    assert animal2 in row2.animals

    rows3 = db_session.scalars(
        select(AnimalData).where(AnimalData.id != row2_id)
    ).all()
    assert len(rows3) == 1
    assert animal3 in rows3[0].animals
