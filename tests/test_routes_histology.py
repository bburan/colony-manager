"""Smoke + targeted coverage for the ``histology`` blueprint.

17 Model.query sites converted (Ear.query × 8 lookups + 2 chain
starters, ConfocalImage.query × 3, ConfocalImageType.query × 2,
Study.query × 1, plus three ``db.session.query(...)`` projections).

The two shared helpers ``_apply_ear_filters`` and ``_apply_ear_sort``
continue to use ``.filter()`` / ``.order_by()`` — those methods exist
on both Query and Select, so the helpers stay compatible with both
callers' SQLAlchemy 2.0 select pipelines.
"""
from datetime import date

from sqlalchemy import select

from colony_manager.models import (
    ConfocalImage, ConfocalImageType, Ear, ImmunolabelingPanel,
)

from .factories import make_animal, make_ear


def _make_image_type(session, name='ImgType-1'):
    obj = ConfocalImageType(name=name)
    session.add(obj)
    session.commit()
    return obj


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def test_list_histology_returns_200(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='H-1')
    make_ear(db_session, animal=animal, side='Left')
    response = logged_in_client.get('/histology/')
    assert response.status_code == 200
    assert b'H-1' in response.data


def test_list_histology_immunolabel_filter(logged_in_client, db_session):
    """Exercises the .filter(Ear.immunolabel_date.is_not(None)) path."""
    animal = make_animal(db_session, custom_id='H-LBL')
    labeled = make_ear(db_session, animal=animal, side='Left')
    labeled.immunolabel_date = date.today()
    pending = make_ear(db_session, animal=animal, side='Right')
    db_session.commit()

    response = logged_in_client.get('/histology/?immunolabel_filter=labeled')
    assert response.status_code == 200


def test_list_histology_side_filter(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='H-SIDE')
    make_ear(db_session, animal=animal, side='Left')
    make_ear(db_session, animal=animal, side='Right')

    response = logged_in_client.get('/histology/?side_filter=Left')
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

def test_view_grid_with_no_image_types(logged_in_client, db_session):
    """The empty-image-types branch must not 500."""
    response = logged_in_client.get('/histology/grid')
    assert response.status_code == 200


def test_view_grid_with_seeded_image_type(logged_in_client, db_session):
    image_type = _make_image_type(db_session, name='Myo7a')
    animal = make_animal(db_session, custom_id='G-1')
    ear = make_ear(db_session, animal=animal, side='Left')
    db_session.add(ConfocalImage(
        ear_id=ear.id, image_type_id=image_type.id,
        frequency=8000.0, status='pending',
    ))
    db_session.commit()

    response = logged_in_client.get('/histology/grid')
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Ear detail + modals
# ---------------------------------------------------------------------------

def test_view_ear_returns_200(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='VEAR-1')
    ear = make_ear(db_session, animal=animal, side='Left')
    response = logged_in_client.get(f'/histology/ears/{ear.id}')
    assert response.status_code == 200


def test_view_ear_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.get('/histology/ears/99999')
    assert response.status_code == 404


def test_edit_ear_note_modal_renders(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='EN-1')
    ear = make_ear(db_session, animal=animal, side='Left')
    response = logged_in_client.get(
        f'/histology/ears/{ear.id}/edit_note_modal'
    )
    assert response.status_code == 200


def test_edit_ear_histology_modal_renders(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='EH-1')
    ear = make_ear(db_session, animal=animal, side='Left')
    response = logged_in_client.get(
        f'/histology/ears/{ear.id}/edit_histology_modal'
    )
    assert response.status_code == 200


def test_create_confocal_images_modal_renders(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='CC-1')
    ear = make_ear(db_session, animal=animal, side='Left')
    response = logged_in_client.get(
        f'/histology/ears/{ear.id}/confocal_images/create_modal'
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Delete paths
# ---------------------------------------------------------------------------

def test_delete_ear_without_images(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='D-1')
    ear = make_ear(db_session, animal=animal, side='Left')
    ear_id = ear.id

    response = logged_in_client.post(
        f'/histology/ears/{ear_id}/delete', follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()  # drop cached identity map; route used Flask's session
    assert db_session.get(Ear, ear_id) is None


def test_delete_ear_with_images_refuses(logged_in_client, db_session):
    image_type = _make_image_type(db_session)
    animal = make_animal(db_session, custom_id='D-2')
    ear = make_ear(db_session, animal=animal, side='Left')
    db_session.add(ConfocalImage(
        ear_id=ear.id, image_type_id=image_type.id,
        frequency=8000.0, status='pending',
    ))
    db_session.commit()
    ear_id = ear.id

    response = logged_in_client.post(
        f'/histology/ears/{ear_id}/delete', follow_redirects=False,
    )
    # The route flashes + redirects on the with-images guard.
    assert response.status_code == 302
    assert db_session.get(Ear, ear_id) is not None


def test_delete_confocal_image(logged_in_client, db_session):
    image_type = _make_image_type(db_session)
    animal = make_animal(db_session, custom_id='DC-1')
    ear = make_ear(db_session, animal=animal, side='Left')
    img = ConfocalImage(
        ear_id=ear.id, image_type_id=image_type.id,
        frequency=8000.0, status='pending',
    )
    db_session.add(img)
    db_session.commit()
    img_id = img.id

    response = logged_in_client.post(
        f'/histology/confocal_images/{img_id}/delete',
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()  # see test_delete_ear_without_images
    assert db_session.get(ConfocalImage, img_id) is None


def test_create_ear_for_terminated_animal(logged_in_client, db_session):
    """``histology.create_ear`` lets the user add a missing Left/Right
    ear after the animal was terminated without ``ears_extracted`` set.
    """
    from datetime import date
    animal = make_animal(db_session, custom_id='CE-1')
    animal.terminate(termination_date=date.today())
    db_session.commit()

    response = logged_in_client.post(
        f'/histology/animals/{animal.id}/ears/create',
        data={'side': 'Left'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    ears = db_session.scalars(
        select(Ear).where(Ear.animal_id == animal.id)
    ).all()
    assert [e.side for e in ears] == ['Left']


def test_create_ear_canonicalizes_lowercase_side(logged_in_client, db_session):
    """Accept ``left`` / ``right`` and store the canonical form."""
    from datetime import date
    animal = make_animal(db_session, custom_id='CE-2')
    animal.terminate(termination_date=date.today())
    db_session.commit()

    response = logged_in_client.post(
        f'/histology/animals/{animal.id}/ears/create',
        data={'side': 'right'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    ears = db_session.scalars(
        select(Ear).where(Ear.animal_id == animal.id)
    ).all()
    assert [e.side for e in ears] == ['Right']


def test_create_ear_rejects_invalid_side(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='CE-3')
    response = logged_in_client.post(
        f'/histology/animals/{animal.id}/ears/create',
        data={'side': 'Middle'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    ears = db_session.scalars(
        select(Ear).where(Ear.animal_id == animal.id)
    ).all()
    assert ears == []


def test_create_ear_refuses_duplicate_side(logged_in_client, db_session):
    animal = make_animal(db_session, custom_id='CE-4')
    make_ear(db_session, animal=animal, side='Left')

    response = logged_in_client.post(
        f'/histology/animals/{animal.id}/ears/create',
        data={'side': 'Left'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    ears = db_session.scalars(
        select(Ear).where(Ear.animal_id == animal.id)
    ).all()
    # Still only one Left ear; the duplicate request was a no-op.
    assert len(ears) == 1


def test_create_ear_404_for_unknown_animal(logged_in_client):
    response = logged_in_client.post(
        '/histology/animals/99999/ears/create',
        data={'side': 'Left'},
    )
    assert response.status_code == 404


def test_edit_confocal_image_modal_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.get(
        '/histology/confocal_images/99999/edit_modal'
    )
    assert response.status_code == 404
