"""Smoke + targeted coverage for the ``auth`` blueprint.

Six Model.query sites are converted in this file: login (POST handler
reads user by email), the first-user-bootstrap count, the admin-only
list_users / view_user / update_user_admin / edit_user_modal lookups.
"""
from sqlalchemy import select

from colony_manager.models import User

from .factories import make_user


# ---------------------------------------------------------------------------
# Login (public, exercises User.query.filter_by(email=...).first())
# ---------------------------------------------------------------------------

def test_login_post_with_valid_credentials_redirects(client, db_session):
    make_user(
        db_session, email='alice@example.com', password='correct',
        active=True, admin=False,
    )
    response = client.post(
        '/auth/login',
        data={'email': 'alice@example.com', 'password': 'correct'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    # After successful login the dashboard is the default redirect.
    assert response.headers['Location'] in ('/', 'http://localhost/')


def test_login_post_with_wrong_password_rerenders_form(client, db_session):
    make_user(
        db_session, email='bob@example.com', password='correct',
        active=True,
    )
    response = client.post(
        '/auth/login',
        data={'email': 'bob@example.com', 'password': 'WRONG'},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert b'Invalid email or password' in response.data


def test_login_post_with_unknown_email_rerenders_form(client, db_session):
    """The ``filter_by(email=...).first()`` returns None — must not crash."""
    response = client.post(
        '/auth/login',
        data={'email': 'nobody@example.com', 'password': 'whatever'},
        follow_redirects=False,
    )
    assert response.status_code == 200


def test_login_inactive_user_rejected(client, db_session):
    make_user(
        db_session, email='inactive@example.com', password='correct',
        active=False,
    )
    response = client.post(
        '/auth/login',
        data={'email': 'inactive@example.com', 'password': 'correct'},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert b'Not authorized' in response.data


# ---------------------------------------------------------------------------
# Bootstrap registration (exercises User.query.count())
# ---------------------------------------------------------------------------

def test_first_registered_user_becomes_admin(client, db_session):
    """First-user-to-register self-bootstraps to active+admin.

    Uses ``client`` (not ``logged_in_client``) so the DB has no
    pre-existing users when the POST hits.
    """
    response = client.post(
        '/auth/add',
        data={
            'first_name': 'First',
            'last_name': 'Admin',
            'email': 'first@example.com',
            'password': 'Sup3rStrong!',
            'confirm_password': 'Sup3rStrong!',
        },
        follow_redirects=False,
    )
    assert response.status_code == 200  # re-renders login.html with success

    user = db_session.scalars(
        select(User).where(User.email == 'first@example.com')
    ).one()
    assert user.active is True
    assert user.admin is True


def test_second_registered_user_is_inactive_non_admin(client, db_session):
    """Once a user already exists, subsequent self-registrations need
    admin approval (active=False, admin=False).
    """
    make_user(db_session, email='existing@example.com')

    client.post(
        '/auth/add',
        data={
            'first_name': 'Second',
            'last_name': 'User',
            'email': 'second@example.com',
            'password': 'Sup3rStrong!',
            'confirm_password': 'Sup3rStrong!',
        },
    )
    user = db_session.scalars(
        select(User).where(User.email == 'second@example.com')
    ).one()
    assert user.active is False
    assert user.admin is False


# ---------------------------------------------------------------------------
# Admin-only listing and detail views
# ---------------------------------------------------------------------------

def test_list_users_renders_with_seeded_users(logged_in_client, db_session):
    make_user(db_session, email='extra1@example.com')
    make_user(db_session, email='extra2@example.com')
    response = logged_in_client.get('/auth/')
    assert response.status_code == 200


def test_edit_user_modal_returns_200(logged_in_client, logged_in_user):
    response = logged_in_client.get(
        f'/auth/{logged_in_user.id}/edit_modal'
    )
    assert response.status_code == 200


def test_edit_user_modal_returns_404_for_unknown_id(logged_in_client):
    """Exercises ``db.get_or_404(User, ...)`` for the missing-id case."""
    response = logged_in_client.get('/auth/99999/edit_modal')
    assert response.status_code == 404


def test_admin_routes_forbid_non_admin(client, db_session):
    """Non-admin users get 403 on list_users (the ``_restrict_auth_to_admin``
    blueprint-level hook).
    """
    non_admin = make_user(
        db_session, email='peon@example.com', active=True, admin=False,
    )
    # Manually log in as non-admin.
    with client.session_transaction() as sess:
        sess['_user_id'] = str(non_admin.id)
        sess['_fresh'] = True
    response = client.get('/auth/')
    assert response.status_code == 403
