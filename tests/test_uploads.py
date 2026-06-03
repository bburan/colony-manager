"""Tests for the user-driven file upload flow.

Two layers:

* **Service-level** — ``services.uploads`` directly, against a
  ``tmp_path``-backed ``DataLocation``. These cover the renaming,
  collision-suffix, parsed_metadata seeding, m2m linking, and
  candidate-filtering rules.
* **Route-level** — one happy-path HTTP integration test against
  ``logged_in_client`` so the form-validation + redirect wiring is
  exercised end-to-end.

All upload-flow fakes live in ``tests._description_fakes``; this module
just points the registry env var at it via the ``description_registry``
autouse fixture (copy of the one in test_sync_orchestration.py — the
fixture sets state both before and after to avoid registry-cache
crosstalk).
"""
import io
import os
from datetime import date

import pytest
from sqlalchemy import select

from colony_manager.datatypes import (
    DataTypeDescription, is_upload_capable, reset_registry_cache,
)
from colony_manager.models import (
    AnimalData, Data, EarData,
)

from ._description_fakes import (
    _FilenameAnimalDescription,
    _HashingUploadableAnimalDescription,
    _UploadableAnimalDescription,
    _UploadableAnimalDescriptionSubclass,
    _UploadableEarDescription,
)
from .factories import (
    make_animal, make_animal_data_type, make_data_location,
    make_ear, make_ear_data_type, make_species,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def description_registry(monkeypatch):
    """Point the description-class registry at the test fakes."""
    monkeypatch.setenv(
        'COLONY_MANAGER_DESCRIPTION_REGISTRY', 'tests._description_fakes',
    )
    reset_registry_cache()
    yield
    reset_registry_cache()


def _make_uploadable_animal_dt(session, *, tmp_path, key='fake_animal_upload'):
    """Animal DataType + matching DataLocation rooted at *tmp_path*."""
    dt = make_animal_data_type(session)
    dt.description_class = key
    session.commit()
    location = make_data_location(session, datatype=dt, base_path=tmp_path)
    return dt, location


# ---------------------------------------------------------------------------
# is_upload_capable
# ---------------------------------------------------------------------------

def test_is_upload_capable_false_for_base_class():
    # The abstract base must never count as upload-capable.
    assert is_upload_capable(DataTypeDescription) is False


def test_is_upload_capable_false_for_non_uploadable_subclass():
    assert is_upload_capable(_FilenameAnimalDescription) is False


def test_is_upload_capable_true_for_class_with_upload_filename():
    assert is_upload_capable(_UploadableAnimalDescription) is True


def test_is_upload_capable_walks_mro():
    # Subclass inherits without redefining.
    assert is_upload_capable(_UploadableAnimalDescriptionSubclass) is True


# ---------------------------------------------------------------------------
# candidate_datatypes
# ---------------------------------------------------------------------------

def test_candidate_datatypes_excludes_no_description_class(db_session, tmp_path):
    from colony_manager_gui.services.uploads import candidate_datatypes

    dt = make_animal_data_type(db_session)
    # Has a location but no description_class → excluded.
    make_data_location(db_session, datatype=dt, base_path=tmp_path)

    assert candidate_datatypes(db_session, 'animal') == []


def test_candidate_datatypes_excludes_non_upload_capable(db_session, tmp_path):
    from colony_manager_gui.services.uploads import candidate_datatypes

    dt = make_animal_data_type(db_session)
    dt.description_class = 'fake_animal'  # no upload_filename
    db_session.commit()
    make_data_location(db_session, datatype=dt, base_path=tmp_path)

    assert candidate_datatypes(db_session, 'animal') == []


def test_candidate_datatypes_excludes_locationless(db_session):
    from colony_manager_gui.services.uploads import candidate_datatypes

    dt = make_animal_data_type(db_session)
    dt.description_class = 'fake_animal_upload'
    db_session.commit()
    # No location → excluded even though the desc class is upload-capable.

    assert candidate_datatypes(db_session, 'animal') == []


def test_candidate_datatypes_excludes_wrong_target_type(db_session, tmp_path):
    from colony_manager_gui.services.uploads import candidate_datatypes

    dt = make_ear_data_type(db_session)
    dt.description_class = 'fake_ear_upload'
    db_session.commit()
    make_data_location(db_session, datatype=dt, base_path=tmp_path)

    # The ear DataType should not surface when asking for animal candidates.
    assert candidate_datatypes(db_session, 'animal') == []
    assert [d.id for d in candidate_datatypes(db_session, 'ear')] == [dt.id]


def test_candidate_datatypes_includes_qualifying_type(db_session, tmp_path):
    from colony_manager_gui.services.uploads import candidate_datatypes

    dt, _ = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)
    result = candidate_datatypes(db_session, 'animal')
    assert [d.id for d in result] == [dt.id]


# ---------------------------------------------------------------------------
# search_targets
# ---------------------------------------------------------------------------

def test_search_targets_empty_query_returns_empty(db_session):
    from colony_manager_gui.services.uploads import search_targets
    species = make_species(db_session)
    make_animal(db_session, species=species, custom_id='A001')

    assert search_targets(db_session, 'animal', '') == []
    assert search_targets(db_session, 'animal', '   ') == []


def test_search_targets_matches_animal_substring(db_session):
    from colony_manager_gui.services.uploads import search_targets
    species = make_species(db_session)
    a1 = make_animal(db_session, species=species, custom_id='A001')
    a2 = make_animal(db_session, species=species, custom_id='A002')
    make_animal(db_session, species=species, custom_id='B500')

    matches = search_targets(db_session, 'animal', 'A0')
    ids = [mid for mid, _ in matches]
    assert a1.id in ids
    assert a2.id in ids
    assert len(matches) == 2


def test_search_targets_case_insensitive(db_session):
    from colony_manager_gui.services.uploads import search_targets
    species = make_species(db_session)
    make_animal(db_session, species=species, custom_id='Abc-123')

    matches = search_targets(db_session, 'animal', 'abc')
    assert len(matches) == 1


def test_search_targets_respects_limit(db_session):
    from colony_manager_gui.services.uploads import search_targets
    species = make_species(db_session)
    for i in range(20):
        make_animal(db_session, species=species, custom_id=f'A{i:03d}')

    matches = search_targets(db_session, 'animal', 'A', limit=5)
    assert len(matches) == 5


def test_search_targets_ear_includes_side(db_session):
    from colony_manager_gui.services.uploads import search_targets
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A777')
    make_ear(db_session, animal=animal, side='Left')
    make_ear(db_session, animal=animal, side='Right')

    matches = search_targets(db_session, 'ear', 'A77')
    labels = [lbl for _, lbl in matches]
    assert 'A777 Left' in labels
    assert 'A777 Right' in labels


# ---------------------------------------------------------------------------
# resolve_targets
# ---------------------------------------------------------------------------

def test_resolve_targets_raises_on_unknown_target_type(db_session):
    from colony_manager_gui.services.uploads import UploadError, resolve_targets

    with pytest.raises(UploadError):
        resolve_targets(db_session, 'not_a_type', [1])


def test_resolve_targets_raises_on_missing_id(db_session):
    from colony_manager_gui.services.uploads import UploadError, resolve_targets

    with pytest.raises(UploadError):
        resolve_targets(db_session, 'animal', [999999])


def test_resolve_targets_dedups_and_preserves_order(db_session):
    from colony_manager_gui.services.uploads import resolve_targets

    species = make_species(db_session)
    a1 = make_animal(db_session, species=species, custom_id='A001')
    a2 = make_animal(db_session, species=species, custom_id='A002')

    out = resolve_targets(db_session, 'animal', [a2.id, a1.id, a2.id])
    assert [t.id for t in out] == [a2.id, a1.id]


# ---------------------------------------------------------------------------
# handle_upload — single target
# ---------------------------------------------------------------------------

def _fs(name='photo.jpg', content=b'jpegbytes'):
    """Build a Werkzeug ``FileStorage`` for tests."""
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(content), filename=name)


def test_handle_upload_writes_renamed_file(db_session, app, tmp_path):
    from colony_manager_gui import db as gui_db
    from colony_manager_gui.services.uploads import handle_upload

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    with app.app_context():
        result = handle_upload(
            gui_db.session,
            target_type='animal',
            targets=[gui_db.session.get(type(animal), animal.id)],
            datatype_id=dt.id,
            location_id=location.id,
            date=date(2025, 6, 15),
            notes=None,
            file_storage=_fs('snap.JPG'),
        )
        gui_db.session.commit()

    expected = tmp_path / 'A001_2025-06-15.jpg'
    assert expected.exists()
    assert result.full_path == os.path.realpath(str(expected))


def test_handle_upload_creates_animal_data_row(db_session, app, tmp_path):
    from colony_manager_gui import db as gui_db
    from colony_manager_gui.services.uploads import handle_upload

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    with app.app_context():
        handle_upload(
            gui_db.session,
            target_type='animal',
            targets=[gui_db.session.get(type(animal), animal.id)],
            datatype_id=dt.id,
            location_id=location.id,
            date=date(2025, 6, 15),
            notes='handled by Dr. Smith',
            file_storage=_fs('snap.jpg'),
        )
        gui_db.session.commit()

    rows = db_session.scalars(select(AnimalData)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.name == 'A001_2025-06-15.jpg'
    assert row.relative_path == 'A001_2025-06-15.jpg'
    assert row.status == 'reviewed'
    assert row.notes == 'handled by Dr. Smith'
    assert row.date == date(2025, 6, 15)
    assert row.discovered_at is not None
    assert row.mtime is not None
    # parsed_metadata seeded from the target list (animal_id) + date
    assert row.parsed_metadata.get('animal_id') == ['A001']
    assert row.parsed_metadata.get('date') == '2025-06-15'
    # Linked to the animal via the m2m collection.
    assert [a.id for a in row.animals] == [animal.id]


def test_handle_upload_skips_hash_when_hash_files_empty(db_session, app, tmp_path):
    """``_UploadableAnimalDescription.hash_files()`` returns [] → file_hash stays None."""
    from colony_manager_gui import db as gui_db
    from colony_manager_gui.services.uploads import handle_upload

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    with app.app_context():
        handle_upload(
            gui_db.session,
            target_type='animal',
            targets=[gui_db.session.get(type(animal), animal.id)],
            datatype_id=dt.id, location_id=location.id,
            date=date(2025, 6, 15), notes=None,
            file_storage=_fs('snap.jpg'),
        )
        gui_db.session.commit()

    row = db_session.scalars(select(AnimalData)).one()
    assert row.file_hash is None


def test_handle_upload_computes_hash_for_hashing_description(db_session, app, tmp_path):
    from colony_manager_gui import db as gui_db
    from colony_manager_gui.services.uploads import handle_upload

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(
        db_session, tmp_path=tmp_path, key='fake_animal_upload_hashed',
    )

    with app.app_context():
        handle_upload(
            gui_db.session,
            target_type='animal',
            targets=[gui_db.session.get(type(animal), animal.id)],
            datatype_id=dt.id, location_id=location.id,
            date=date(2025, 6, 15), notes=None,
            file_storage=_fs('snap.jpg', content=b'identifiable content'),
        )
        gui_db.session.commit()

    row = db_session.scalars(select(AnimalData)).one()
    assert row.file_hash is not None
    assert len(row.file_hash) == 32  # xxh3_128 hex


# ---------------------------------------------------------------------------
# handle_upload — multi-target
# ---------------------------------------------------------------------------

def test_handle_upload_links_all_targets(db_session, app, tmp_path):
    from colony_manager_gui import db as gui_db
    from colony_manager.models import Animal as AnimalModel
    from colony_manager_gui.services.uploads import handle_upload

    species = make_species(db_session)
    a1 = make_animal(db_session, species=species, custom_id='A001')
    a2 = make_animal(db_session, species=species, custom_id='A002')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    with app.app_context():
        handle_upload(
            gui_db.session,
            target_type='animal',
            targets=[
                gui_db.session.get(AnimalModel, a1.id),
                gui_db.session.get(AnimalModel, a2.id),
            ],
            datatype_id=dt.id, location_id=location.id,
            date=date(2025, 6, 15), notes=None,
            file_storage=_fs('group.jpg'),
        )
        gui_db.session.commit()

    row = db_session.scalars(select(AnimalData)).one()
    # Filename joined both ids (so round-trip sync re-parses correctly).
    assert row.name == 'A001 A002_2025-06-15.jpg'
    # Linked to both animals.
    assert sorted(a.id for a in row.animals) == sorted([a1.id, a2.id])
    # parsed_metadata carries both ids in order.
    assert row.parsed_metadata.get('animal_id') == ['A001', 'A002']


# ---------------------------------------------------------------------------
# handle_upload — collisions
# ---------------------------------------------------------------------------

def test_handle_upload_supports_subdirectory_paths(db_session, app, tmp_path):
    """Description classes returning ``A001/photo.jpg`` write into an
    auto-created subdirectory; ``Data.relative_path`` keeps the full
    path while ``Data.name`` is just the filename."""
    from colony_manager_gui import db as gui_db
    from colony_manager.models import Animal as AnimalModel
    from colony_manager_gui.services.uploads import handle_upload

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')

    # Register a one-off description class on the test registry that
    # produces a subdirectory path. (Done inline rather than in
    # _description_fakes.py because this is the only test that needs it.)
    from colony_manager.datatypes import DataTypeDescription, reset_registry_cache
    from tests import _description_fakes
    from pathlib import Path as _Path

    class _SubdirAnimalDescription(DataTypeDescription):
        def parse(self):
            return None

        def hash_files(self):
            return []

        @classmethod
        def upload_filename(cls, targets, original_filename, *, date, notes):
            ext = _Path(original_filename).suffix.lower() or '.bin'
            ids = ' '.join(t.custom_id for t in targets)
            return f'{ids}/{date:%Y-%m-%d}{ext}'

    _description_fakes.DESCRIPTION_CLASSES['fake_animal_subdir'] = (
        _SubdirAnimalDescription
    )
    reset_registry_cache()
    try:
        dt, location = _make_uploadable_animal_dt(
            db_session, tmp_path=tmp_path, key='fake_animal_subdir',
        )

        with app.app_context():
            handle_upload(
                gui_db.session, target_type='animal',
                targets=[gui_db.session.get(AnimalModel, animal.id)],
                datatype_id=dt.id, location_id=location.id,
                date=date(2025, 6, 15), notes=None,
                file_storage=_fs('snap.jpg'),
            )
            gui_db.session.commit()

        row = db_session.scalars(select(AnimalData)).one()
        assert row.relative_path == 'A001/2025-06-15.jpg'
        # ``name`` is just the basename (sync's convention) so the
        # entity_data_files template's image-extension check works.
        assert row.name == '2025-06-15.jpg'
        # File landed in the auto-created subdirectory.
        assert (tmp_path / 'A001' / '2025-06-15.jpg').exists()
    finally:
        _description_fakes.DESCRIPTION_CLASSES.pop('fake_animal_subdir', None)
        reset_registry_cache()


def test_handle_upload_rejects_parent_directory_traversal(
    db_session, app, tmp_path,
):
    """A description class returning ``../escape.jpg`` must be sanitized
    to ``escape.jpg`` (no parent-dir escape)."""
    from colony_manager_gui import db as gui_db
    from colony_manager.models import Animal as AnimalModel
    from colony_manager_gui.services.uploads import handle_upload
    from colony_manager.datatypes import DataTypeDescription, reset_registry_cache
    from tests import _description_fakes

    class _EvilDescription(DataTypeDescription):
        def parse(self):
            return None

        def hash_files(self):
            return []

        @classmethod
        def upload_filename(cls, targets, original_filename, *, date, notes):
            return '../escape.jpg'

    _description_fakes.DESCRIPTION_CLASSES['fake_evil'] = _EvilDescription
    reset_registry_cache()
    try:
        species = make_species(db_session)
        animal = make_animal(db_session, species=species, custom_id='A001')
        dt, location = _make_uploadable_animal_dt(
            db_session, tmp_path=tmp_path, key='fake_evil',
        )
        with app.app_context():
            handle_upload(
                gui_db.session, target_type='animal',
                targets=[gui_db.session.get(AnimalModel, animal.id)],
                datatype_id=dt.id, location_id=location.id,
                date=date(2025, 6, 15), notes=None,
                file_storage=_fs('snap.jpg'),
            )
            gui_db.session.commit()
        # ``..`` segment stripped → file lands as ``escape.jpg`` inside
        # the base_path, not above it.
        row = db_session.scalars(select(AnimalData)).one()
        assert row.relative_path == 'escape.jpg'
        assert (tmp_path / 'escape.jpg').exists()
        # The parent dir does NOT have an ``escape.jpg`` — confirms the
        # ``..`` was stripped rather than honored.
        assert not (tmp_path.parent / 'escape.jpg').exists()
    finally:
        _description_fakes.DESCRIPTION_CLASSES.pop('fake_evil', None)
        reset_registry_cache()


def test_handle_upload_suffixes_on_collision(db_session, app, tmp_path):
    from colony_manager_gui import db as gui_db
    from colony_manager.models import Animal as AnimalModel
    from colony_manager_gui.services.uploads import handle_upload

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)
    a_target = lambda: gui_db.session.get(AnimalModel, animal.id)

    with app.app_context():
        # First upload — clean.
        handle_upload(
            gui_db.session, target_type='animal', targets=[a_target()],
            datatype_id=dt.id, location_id=location.id,
            date=date(2025, 6, 15), notes=None,
            file_storage=_fs('snap.jpg'),
        )
        gui_db.session.commit()
        # Second upload, same rename target → must suffix to _1.
        handle_upload(
            gui_db.session, target_type='animal', targets=[a_target()],
            datatype_id=dt.id, location_id=location.id,
            date=date(2025, 6, 15), notes=None,
            file_storage=_fs('snap.jpg'),
        )
        gui_db.session.commit()
        # Third — must suffix to _2.
        handle_upload(
            gui_db.session, target_type='animal', targets=[a_target()],
            datatype_id=dt.id, location_id=location.id,
            date=date(2025, 6, 15), notes=None,
            file_storage=_fs('snap.jpg'),
        )
        gui_db.session.commit()

    names = sorted(
        r.name for r in db_session.scalars(select(AnimalData)).all()
    )
    assert names == [
        'A001_2025-06-15.jpg',
        'A001_2025-06-15_1.jpg',
        'A001_2025-06-15_2.jpg',
    ]
    for name in names:
        assert (tmp_path / name).exists()


# ---------------------------------------------------------------------------
# handle_upload — validation
# ---------------------------------------------------------------------------

def test_handle_upload_raises_for_unknown_target_type(db_session, app, tmp_path):
    from colony_manager_gui import db as gui_db
    from colony_manager.models import Animal as AnimalModel
    from colony_manager_gui.services.uploads import UploadError, handle_upload

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    with app.app_context():
        with pytest.raises(UploadError):
            handle_upload(
                gui_db.session, target_type='not_a_type',
                targets=[gui_db.session.get(AnimalModel, animal.id)],
                datatype_id=dt.id, location_id=location.id,
                date=date(2025, 6, 15), notes=None,
                file_storage=_fs('snap.jpg'),
            )


def test_handle_upload_raises_when_datatype_mismatches_target_type(
    db_session, app, tmp_path,
):
    """Posting an animal target to an ear DataType must fail."""
    from colony_manager_gui import db as gui_db
    from colony_manager.models import Animal as AnimalModel
    from colony_manager_gui.services.uploads import UploadError, handle_upload

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')

    ear_dt = make_ear_data_type(db_session)
    ear_dt.description_class = 'fake_ear_upload'
    db_session.commit()
    ear_location = make_data_location(db_session, datatype=ear_dt, base_path=tmp_path)

    with app.app_context():
        with pytest.raises(UploadError):
            handle_upload(
                gui_db.session, target_type='animal',
                targets=[gui_db.session.get(AnimalModel, animal.id)],
                datatype_id=ear_dt.id, location_id=ear_location.id,
                date=date(2025, 6, 15), notes=None,
                file_storage=_fs('snap.jpg'),
            )


def test_handle_upload_raises_when_description_is_non_uploadable(
    db_session, app, tmp_path,
):
    """A DataType whose description class lacks ``upload_filename`` must refuse."""
    from colony_manager_gui import db as gui_db
    from colony_manager.models import Animal as AnimalModel
    from colony_manager_gui.services.uploads import UploadError, handle_upload

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')

    dt = make_animal_data_type(db_session)
    dt.description_class = 'fake_animal'  # non-uploadable
    db_session.commit()
    location = make_data_location(db_session, datatype=dt, base_path=tmp_path)

    with app.app_context():
        with pytest.raises(UploadError):
            handle_upload(
                gui_db.session, target_type='animal',
                targets=[gui_db.session.get(AnimalModel, animal.id)],
                datatype_id=dt.id, location_id=location.id,
                date=date(2025, 6, 15), notes=None,
                file_storage=_fs('snap.jpg'),
            )


# ---------------------------------------------------------------------------
# handle_upload — ear targets (verifies ear m2m + parsed_metadata branch)
# ---------------------------------------------------------------------------

def test_handle_upload_ear_target_seeds_side_in_metadata(
    db_session, app, tmp_path,
):
    from colony_manager_gui import db as gui_db
    from colony_manager.models import Ear as EarModel
    from colony_manager_gui.services.uploads import handle_upload

    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    ear = make_ear(db_session, animal=animal, side='Left')

    dt = make_ear_data_type(db_session)
    dt.description_class = 'fake_ear_upload'
    db_session.commit()
    location = make_data_location(db_session, datatype=dt, base_path=tmp_path)

    with app.app_context():
        handle_upload(
            gui_db.session, target_type='ear',
            targets=[gui_db.session.get(EarModel, ear.id)],
            datatype_id=dt.id, location_id=location.id,
            date=date(2025, 6, 15), notes=None,
            file_storage=_fs('dissect.pdf'),
        )
        gui_db.session.commit()

    row = db_session.scalars(select(EarData)).one()
    assert row.parsed_metadata.get('animal_id') == ['A001']
    assert row.parsed_metadata.get('side') == ['Left']
    assert [e.id for e in row.ears] == [ear.id]


# ---------------------------------------------------------------------------
# Route-level: happy path
# ---------------------------------------------------------------------------

def test_upload_modal_renders_with_target_chip(
    logged_in_client, db_session, tmp_path,
):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    response = logged_in_client.get(f'/data/upload/animal/{animal.id}/modal')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'A001' in body  # initial chip label
    assert 'Upload' in body


def test_upload_modal_404_for_unknown_target_type(logged_in_client):
    response = logged_in_client.get('/data/upload/not_a_type/1/modal')
    assert response.status_code == 404


def test_upload_modal_404_for_missing_animal(logged_in_client, db_session, tmp_path):
    response = logged_in_client.get('/data/upload/animal/999999/modal')
    assert response.status_code == 404


def test_upload_files_happy_path(
    logged_in_client, db_session, tmp_path,
):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    response = logged_in_client.post(
        f'/data/upload/animal/{animal.id}',
        data={
            'datatype': str(dt.id),
            'location': str(location.id),
            'date': '2025-06-15',
            'targets': [str(animal.id)],
            'file_notes': 'integration',
            'files': (io.BytesIO(b'jpegbytes'), 'snap.jpg'),
        },
        content_type='multipart/form-data',
        follow_redirects=False,
    )
    # Redirect back to the animal detail page on success.
    assert response.status_code in (302, 303)
    assert f'/animals/{animal.id}' in response.headers.get('Location', '')

    rows = db_session.scalars(select(AnimalData)).all()
    assert len(rows) == 1
    assert rows[0].name == 'A001_2025-06-15.jpg'
    assert rows[0].notes == 'integration'
    assert (tmp_path / 'A001_2025-06-15.jpg').exists()


def test_upload_files_multi_file_per_file_notes(
    logged_in_client, db_session, tmp_path,
):
    """Two files uploaded together get independent notes — the route zips
    ``file_notes`` with ``files`` by position."""
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    response = logged_in_client.post(
        f'/data/upload/animal/{animal.id}',
        data={
            'datatype': str(dt.id),
            'location': str(location.id),
            'date': '2025-06-15',
            'targets': [str(animal.id)],
            'file_notes': ['first photo', 'second photo'],
            'files': [
                (io.BytesIO(b'a'), 'snap.jpg'),
                (io.BytesIO(b'b'), 'snap.jpg'),
            ],
        },
        content_type='multipart/form-data',
    )
    assert response.status_code in (302, 303)
    rows = sorted(
        db_session.scalars(select(AnimalData)).all(),
        key=lambda r: r.name,
    )
    assert [r.name for r in rows] == [
        'A001_2025-06-15.jpg', 'A001_2025-06-15_1.jpg',
    ]
    # File-order ↔ notes-order pairing held end-to-end.
    assert [r.notes for r in rows] == ['first photo', 'second photo']


def test_upload_files_pads_missing_file_notes(
    logged_in_client, db_session, tmp_path,
):
    """If fewer ``file_notes`` arrive than files, the remainder are NULL."""
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    response = logged_in_client.post(
        f'/data/upload/animal/{animal.id}',
        data={
            'datatype': str(dt.id),
            'location': str(location.id),
            'date': '2025-06-15',
            'targets': [str(animal.id)],
            'file_notes': ['only first'],
            'files': [
                (io.BytesIO(b'a'), 'snap.jpg'),
                (io.BytesIO(b'b'), 'snap.jpg'),
            ],
        },
        content_type='multipart/form-data',
    )
    assert response.status_code in (302, 303)
    rows = sorted(
        db_session.scalars(select(AnimalData)).all(),
        key=lambda r: r.name,
    )
    assert rows[0].notes == 'only first'
    assert rows[1].notes is None


def test_upload_target_search_endpoint(logged_in_client, db_session):
    species = make_species(db_session)
    make_animal(db_session, species=species, custom_id='A001')
    make_animal(db_session, species=species, custom_id='A002')

    response = logged_in_client.get('/data/upload/animal/search?q=A00')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'A001' in body
    assert 'A002' in body


def test_upload_locations_endpoint(logged_in_client, db_session, tmp_path):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    response = logged_in_client.get(
        f'/data/upload/animal/{animal.id}/locations?datatype={dt.id}'
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert str(tmp_path) in body or location.base_path in body


def test_upload_files_rejects_empty_target_list(
    logged_in_client, db_session, tmp_path,
):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_uploadable_animal_dt(db_session, tmp_path=tmp_path)

    response = logged_in_client.post(
        f'/data/upload/animal/{animal.id}',
        data={
            'datatype': str(dt.id),
            'location': str(location.id),
            'date': '2025-06-15',
            # No 'targets' key at all.
            'files': (io.BytesIO(b'a'), 'snap.jpg'),
        },
        content_type='multipart/form-data',
    )
    # Redirect back without persisting anything.
    assert response.status_code in (302, 303)
    assert db_session.scalars(select(AnimalData)).all() == []
    # File should not have been written, either.
    assert list(tmp_path.iterdir()) == []
