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

from colony_manager.enums import ConfocalImageStatus
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
        frequency=8000.0, status=ConfocalImageStatus.IMAGED,
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
        frequency=8000.0, status=ConfocalImageStatus.IMAGED,
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
        frequency=8000.0, status=ConfocalImageStatus.IMAGED,
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


# ---------------------------------------------------------------------------
# Regression: _update_ear_response dispatch + histology-grid-reload sentinel
#
# These tests cover the htmx:targetError bug where the grid edit-modal
# POST was silently aborted by HTMX because #histology-grid-reload did
# not exist in the DOM.  Two layers are tested:
#
#   1. Server: the three _update_ear_response dispatch paths return the
#      correct status / headers / body depending on hx_target.
#   2. Template: the grid page HTML always contains the sentinel element;
#      the modal HTML puts hx-post on the button (not the <form>) when
#      hx_target is supplied.
# ---------------------------------------------------------------------------

def test_update_ear_histology_grid_target_returns_204_refresh(
    logged_in_client, db_session
):
    """hx_target=#histology-grid-reload → 204 + HX-Refresh: true.

    Regression: ensures the server-side response is correct when HTMX
    reaches the route with the grid's sentinel as its target.  Prior to
    the fix the request never reached the server because HTMX aborted on
    htmx:targetError (the sentinel element was missing from the DOM).
    """
    animal = make_animal(db_session, custom_id='GRD-1')
    ear = make_ear(db_session, animal=animal, side='Left')

    response = logged_in_client.post(
        f'/histology/ears/{ear.id}/histology/update',
        query_string={'hx_target': '#histology-grid-reload'},
        headers={'HX-Request': 'true'},
        data={},
    )
    assert response.status_code == 204
    assert response.headers.get('HX-Refresh') == 'true'
    assert response.headers.get('HX-Trigger') == 'closeModal'


def test_update_ear_histology_row_target_returns_row_html(
    logged_in_client, db_session
):
    """hx_target=#ear-row-N → 200 with the ear-row partial HTML."""
    animal = make_animal(db_session, custom_id='GRD-2')
    ear = make_ear(db_session, animal=animal, side='Right')

    response = logged_in_client.post(
        f'/histology/ears/{ear.id}/histology/update',
        query_string={'hx_target': f'#ear-row-{ear.id}'},
        headers={'HX-Request': 'true'},
        data={},
    )
    assert response.status_code == 200
    assert response.headers.get('HX-Trigger') == 'closeModal'
    assert b'GRD-2' in response.data


def test_update_ear_histology_default_target_returns_card_html(
    logged_in_client, db_session
):
    """No hx_target → 200 with the histology-card partial HTML."""
    animal = make_animal(db_session, custom_id='GRD-3')
    ear = make_ear(db_session, animal=animal, side='Left')

    response = logged_in_client.post(
        f'/histology/ears/{ear.id}/histology/update',
        headers={'HX-Request': 'true'},
        data={},
    )
    assert response.status_code == 200
    assert response.headers.get('HX-Trigger') == 'closeModal'
    # The default response renders the ear-histology-card partial.
    assert b'id="ear-histology-card"' in response.data


def test_edit_ear_histology_modal_grid_target_renders_htmx_button(
    logged_in_client, db_session
):
    """Modal GET with hx_target → Confirm button carries hx-post, not type=submit.

    Regression: form_modal.html must put HTMX attrs on the <button> (not
    the <form>) so forms loaded via innerHTML into a Bootstrap modal still
    fire.  A plain type=submit button inside an innerHTML-swapped form can
    miss HTMX's submit listener.
    """
    animal = make_animal(db_session, custom_id='GRD-4')
    ear = make_ear(db_session, animal=animal, side='Left')

    response = logged_in_client.get(
        f'/histology/ears/{ear.id}/edit_histology_modal',
        query_string={'hx_target': '#histology-grid-reload'},
    )
    assert response.status_code == 200
    assert b'hx-post=' in response.data
    assert b'type="submit"' not in response.data


def test_grid_page_contains_reload_sentinel(logged_in_client, db_session):
    """The grid page HTML must always contain #histology-grid-reload.

    Regression: this hidden sentinel element was absent, causing
    htmx:targetError to abort the POST from the grid's edit-ear modal
    before it ever reached the server.
    """
    response = logged_in_client.get('/histology/grid')
    assert response.status_code == 200
    assert b'id="histology-grid-reload"' in response.data
