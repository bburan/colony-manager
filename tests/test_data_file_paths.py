"""Tests for ``Data.full_path`` and the hover titles it feeds.

The UI lists files by ``name``, which does not say where the file lives.
Every listing therefore carries the full path as a hover title so a file
can be found on disk without opening its detail panel.
"""
import os

from colony_manager.models import EarData

from .factories import (
    make_animal, make_data_location, make_ear, make_ear_data_type,
)


def _ear_file(db_session, *, ear=None, animal=None, base='/data/ears',
              relative='2026/G100-1 Left.jpg'):
    dtype = make_ear_data_type(db_session)
    location = make_data_location(db_session, datatype=dtype, base_path=base)
    row = EarData(
        datatype_id=dtype.id, location_id=location.id, target_type='ear',
        relative_path=relative, name=os.path.basename(relative),
    )
    db_session.add(row)
    if ear is not None:
        row.ears = [ear]
    if animal is not None:
        row.candidate_animals = [animal]
    db_session.commit()
    return row


def test_full_path_joins_location_base_and_relative_path(db_session):
    row = _ear_file(db_session)
    assert row.full_path == os.path.join('/data/ears', '2026/G100-1 Left.jpg')


def test_full_path_survives_a_row_with_no_location(db_session):
    """Display-only, so it must not raise on a half-built row.

    Upload rows are constructed before their location is attached, and a
    template that touched ``full_path`` mid-flight would 500 the page.
    """
    assert EarData(relative_path='a/b.txt').full_path == 'a/b.txt'


def test_ear_page_shows_the_full_path_on_hover(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='FP-1')
    ear = make_ear(db_session, animal=animal, side='Left')
    row = _ear_file(db_session, ear=ear)

    response = logged_in_client.get(f'/histology/ears/{ear.id}')
    assert response.status_code == 200
    assert f'title="{row.full_path}"'.encode() in response.data


def test_unmatched_data_page_shows_the_full_path_on_hover(
    logged_in_client, db_session,
):
    animal = make_animal(db_session, custom_id='FP-2')
    row = _ear_file(db_session, animal=animal, relative='2026/FP-2 Right.jpg')

    response = logged_in_client.get('/animals/unmatched-data?target_type=ear')
    assert response.status_code == 200
    assert f'title="{row.full_path}"'.encode() in response.data
