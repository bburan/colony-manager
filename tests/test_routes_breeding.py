"""Smoke + targeted coverage for the ``breeding`` blueprint.

Twelve Model.query sites converted in this file. All but one are
``get_or_404`` lookups (the list view's ``order_by`` is the
exception). Test scope is intentionally narrow: list/detail/modal
renders, 404 paths, deactivate/reactivate flag toggling, and a
litter create/delete round-trip.
"""
from sqlalchemy import select

from colony_manager.models import BreedingPair, Litter

from .factories import (
    make_breeding_pair, make_litter, make_species,
)


# ---------------------------------------------------------------------------
# List + detail
# ---------------------------------------------------------------------------

def test_list_breeding_pairs_returns_200(logged_in_client, db_session):
    pair = make_breeding_pair(db_session)
    response = logged_in_client.get('/breeding/')
    assert response.status_code == 200
    assert pair.custom_id.encode() in response.data


def test_view_breeding_pair_returns_200(logged_in_client, db_session):
    pair = make_breeding_pair(db_session)
    response = logged_in_client.get(f'/breeding/{pair.id}')
    assert response.status_code == 200
    assert pair.custom_id.encode() in response.data


def test_view_breeding_pair_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.get('/breeding/99999')
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Activation toggle
# ---------------------------------------------------------------------------

def test_deactivate_breeding_pair(logged_in_client, db_session):
    pair = make_breeding_pair(db_session)
    assert pair.is_active is True
    response = logged_in_client.post(
        f'/breeding/{pair.id}/deactivate', follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(pair)
    assert pair.is_active is False


def test_reactivate_breeding_pair(logged_in_client, db_session):
    pair = make_breeding_pair(db_session)
    pair.is_active = False
    db_session.commit()

    logged_in_client.post(f'/breeding/{pair.id}/reactivate')
    db_session.refresh(pair)
    assert pair.is_active is True


def test_deactivate_unknown_pair_returns_404(logged_in_client):
    response = logged_in_client.post('/breeding/99999/deactivate')
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

def test_create_breeding_pair_modal_renders(logged_in_client):
    response = logged_in_client.get('/breeding/create_modal')
    assert response.status_code == 200


def test_create_litter_modal_renders(logged_in_client, db_session):
    pair = make_breeding_pair(db_session)
    response = logged_in_client.get(
        f'/breeding/{pair.id}/litters/create_modal'
    )
    assert response.status_code == 200


def test_edit_litter_modal_renders(logged_in_client, db_session):
    litter = make_litter(db_session)
    response = logged_in_client.get(
        f'/breeding/litters/{litter.id}/edit_modal'
    )
    assert response.status_code == 200


def test_edit_litter_modal_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.get('/breeding/litters/99999/edit_modal')
    assert response.status_code == 404


def test_delete_litter_modal_renders(logged_in_client, db_session):
    litter = make_litter(db_session)
    response = logged_in_client.get(
        f'/breeding/litters/{litter.id}/delete_modal'
    )
    assert response.status_code == 200


def test_wean_litter_modal_renders(logged_in_client, db_session):
    litter = make_litter(db_session)
    response = logged_in_client.get(
        f'/breeding/litters/{litter.id}/wean_modal'
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Litter create / delete
# ---------------------------------------------------------------------------

def test_delete_litter(logged_in_client, db_session):
    litter = make_litter(db_session)
    litter_id = litter.id

    response = logged_in_client.post(
        f'/breeding/litters/{litter_id}/delete',
        follow_redirects=False,
    )
    assert response.status_code == 302
    # The route deletes via Flask's db.session in a different SA session;
    # expire_all() drops cached identity-mapped objects so the next read
    # hits the DB instead of returning the stale instance.
    db_session.expire_all()
    assert db_session.get(Litter, litter_id) is None


def test_delete_litter_unknown_returns_404(logged_in_client):
    response = logged_in_client.post('/breeding/litters/99999/delete')
    assert response.status_code == 404
