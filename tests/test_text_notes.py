"""Tests for text notes — Markdown files written in the app.

A text note rides the upload pipeline (``services.uploads.handle_upload``),
so naming / collision / linking are covered by ``test_uploads.py``; these
cover what is specific to notes: the DataType opt-in, the ``note N``
auto-numbering, line-ending normalisation, and the read / edit / preview
routes.
"""
import pytest
from sqlalchemy import select

from colony_manager.datatypes import is_text_note_capable, reset_registry_cache
from colony_manager.models import AnimalData

from ._description_fakes import (
    _LabelledUploadableAnimalDescription, _TextNoteAnimalDescription,
)
from .factories import (
    make_animal, make_animal_data_type, make_data_location, make_species,
)


@pytest.fixture(autouse=True)
def description_registry(monkeypatch):
    monkeypatch.setenv(
        'COLONY_MANAGER_DESCRIPTION_REGISTRY', 'tests._description_fakes',
    )
    reset_registry_cache()
    yield
    reset_registry_cache()


@pytest.fixture
def tmp_path(tmp_path):
    """``tmp_path`` with an ``a/`` subdirectory as the default location root,
    leaving room for a second location beside it."""
    (tmp_path / 'a').mkdir()
    return tmp_path


def _make_dt(session, tmp_path, key='fake_animal_text_note'):
    dt = make_animal_data_type(session)
    dt.description_class = key
    session.commit()
    location = make_data_location(session, datatype=dt, base_path=tmp_path)
    return dt, location


def _post_note(client, animal, dt, location, *, content, name=''):
    return client.post(
        f'/data/note/animal/{animal.id}',
        data={
            'datatype': str(dt.id),
            'location': str(location.id),
            'date': '2026-04-15',
            'name': name,
            'content': content,
        },
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Opt-in
# ---------------------------------------------------------------------------

def test_is_text_note_capable_needs_suffix_and_upload_filename():
    assert is_text_note_capable(_TextNoteAnimalDescription) is True
    assert is_text_note_capable(_LabelledUploadableAnimalDescription) is False


def test_candidate_datatypes_text_notes_filter(db_session, tmp_path):
    from colony_manager_gui.services.uploads import candidate_datatypes

    note_dt, _ = _make_dt(db_session, tmp_path / 'a')
    (tmp_path / 'b').mkdir()
    photo_dt, _ = _make_dt(db_session, tmp_path / 'b',
                           key='fake_animal_upload_labelled')

    assert {d.id for d in candidate_datatypes(db_session, 'animal')} == {
        note_dt.id, photo_dt.id}
    assert [d.id for d in candidate_datatypes(
        db_session, 'animal', text_notes=True)] == [note_dt.id]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_note_modal_lists_only_text_capable_types(logged_in_client, db_session, tmp_path):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    note_dt, _ = _make_dt(db_session, tmp_path / 'a')
    (tmp_path / 'b').mkdir()
    photo_dt, _ = _make_dt(db_session, tmp_path / 'b',
                           key='fake_animal_upload_labelled')

    response = logged_in_client.get(f'/data/note/animal/{animal.id}/modal')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert note_dt.name in body
    assert photo_dt.name not in body
    assert 'colonyTextNoteEditor' in body
    assert '@paste="onPaste($event)"' in body


def test_note_modal_empty_state_without_capable_type(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    response = logged_in_client.get(f'/data/note/animal/{animal.id}/modal')
    assert response.status_code == 200
    assert 'text_note_suffix' in response.get_data(as_text=True)


def test_create_note_writes_markdown_file(logged_in_client, db_session, tmp_path):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_dt(db_session, tmp_path / 'a')

    response = _post_note(logged_in_client, animal, dt, location,
                          content='# Surgery\r\n\r\n- sutured\r\n',
                          name='surgery')
    assert response.status_code in (302, 303)
    assert f'/animals/{animal.id}' in response.headers['Location']

    row = db_session.scalars(select(AnimalData)).one()
    assert row.name == 'A001_2026-04-15 - surgery.md'
    assert [a.id for a in row.animals] == [animal.id]
    assert row.file_hash is not None
    # CRLF from the textarea is normalised.
    assert (tmp_path / 'a' / row.name).read_bytes() == b'# Surgery\n\n- sutured\n'


def test_create_note_blank_name_auto_numbers_as_note(logged_in_client, db_session, tmp_path):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_dt(db_session, tmp_path / 'a')

    for _ in range(2):
        _post_note(logged_in_client, animal, dt, location, content='text')

    names = sorted(r.name for r in db_session.scalars(select(AnimalData)))
    assert names == ['A001_2026-04-15 - note 1.md', 'A001_2026-04-15 - note 2.md']


def test_create_note_refuses_non_text_type(logged_in_client, db_session, tmp_path):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_dt(db_session, tmp_path / 'a',
                            key='fake_animal_upload_labelled')

    _post_note(logged_in_client, animal, dt, location, content='text')

    assert db_session.scalars(select(AnimalData)).all() == []
    assert list((tmp_path / 'a').iterdir()) == []


def test_create_note_refuses_blank_text(logged_in_client, db_session, tmp_path):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_dt(db_session, tmp_path / 'a')

    _post_note(logged_in_client, animal, dt, location, content='   ')

    assert db_session.scalars(select(AnimalData)).all() == []


# ---------------------------------------------------------------------------
# Read / edit / preview
# ---------------------------------------------------------------------------

def _create(client, db_session, tmp_path, content='Some **bold** text'):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_dt(db_session, tmp_path / 'a')
    _post_note(client, animal, dt, location, content=content, name='n')
    return db_session.scalars(select(AnimalData)).one()


def test_view_note_renders_markdown(logged_in_client, db_session, tmp_path):
    row = _create(logged_in_client, db_session, tmp_path,
                  content='Some **bold** <script>x</script>')
    response = logged_in_client.get(f'/data/{row.id}/note')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '<strong>bold</strong>' in body
    assert '<script>x' not in body
    assert f'/data/{row.id}/note/edit_modal' in body


def test_view_note_404_for_non_text_file(logged_in_client, db_session, tmp_path):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_dt(db_session, tmp_path / 'a')
    row = AnimalData(datatype_id=dt.id, location_id=location.id,
                     relative_path='x.jpg', name='x.jpg')
    row.animals = [animal]
    db_session.add(row)
    db_session.commit()
    assert logged_in_client.get(f'/data/{row.id}/note').status_code == 404


def test_txt_file_of_other_type_is_viewable_not_editable(logged_in_client, db_session, tmp_path):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='A001')
    dt, location = _make_dt(db_session, tmp_path / 'a', key='fake_animal')
    (tmp_path / 'a' / 'A001.txt').write_text('plain')
    row = AnimalData(datatype_id=dt.id, location_id=location.id,
                     relative_path='A001.txt', name='A001.txt')
    row.animals = [animal]
    db_session.add(row)
    db_session.commit()

    response = logged_in_client.get(f'/data/{row.id}/note')
    assert response.status_code == 200
    assert 'edit_modal' not in response.get_data(as_text=True)
    assert logged_in_client.get(f'/data/{row.id}/note/edit_modal').status_code == 404
    response = logged_in_client.post(f'/data/{row.id}/note', data={'content': 'x'})
    assert response.status_code == 404
    assert (tmp_path / 'a' / 'A001.txt').read_text() == 'plain'


def test_edit_note_overwrites_file_and_rehashes(logged_in_client, db_session, tmp_path):
    row = _create(logged_in_client, db_session, tmp_path, content='old')
    old_hash = row.file_hash

    modal = logged_in_client.get(f'/data/{row.id}/note/edit_modal')
    assert modal.status_code == 200
    assert 'old' in modal.get_data(as_text=True)

    response = logged_in_client.post(
        f'/data/{row.id}/note', data={'content': 'new text, longer'},
        headers={'Referer': '/animals/1'})
    assert response.status_code in (302, 303)
    db_session.refresh(row)
    assert (tmp_path / 'a' / row.name).read_text() == 'new text, longer\n'
    assert row.file_hash != old_hash


def test_preview_renders_posted_text(logged_in_client):
    response = logged_in_client.post('/data/note/preview',
                                     data={'content': '- one\n- two'})
    assert response.status_code == 200
    assert '<ul><li>one</li><li>two</li></ul>' in response.get_data(as_text=True)


def test_file_row_gets_read_button(logged_in_client, db_session, tmp_path):
    row = _create(logged_in_client, db_session, tmp_path)
    animal_id = row.animals[0].id
    response = logged_in_client.get(f'/animals/{animal_id}')
    assert response.status_code == 200
    assert f'/data/{row.id}/note' in response.get_data(as_text=True)
