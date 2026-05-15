"""Initial smoke coverage for the most-used routes.

Validates that the ``logged_in_client`` fixture works end-to-end and
that the highest-traffic list views return without server error.
Once this baseline is green, more comprehensive per-blueprint smoke
files cover the rest of the routes.
"""
import pytest


# ---------------------------------------------------------------------------
# Public routes (no login required)
# ---------------------------------------------------------------------------

def test_unauth_root_redirects_to_login(client):
    """Unauthenticated GET / should redirect to the login page."""
    response = client.get('/', follow_redirects=False)
    assert response.status_code == 302
    assert '/auth/login' in response.headers['Location']


def test_login_page_renders_for_anonymous(client):
    """``/auth/login`` is decorated ``@public`` — must work without auth."""
    response = client.get('/auth/login')
    assert response.status_code == 200
    assert b'login' in response.data.lower()


# ---------------------------------------------------------------------------
# Authenticated routes (require login)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('path', [
    '/',
    '/cages/',
    '/animals/',
    '/breeding/',
    '/histology/',
    '/studies/',
])
def test_list_views_return_ok_when_logged_in(logged_in_client, path):
    """Every blueprint's primary list view should render against an empty DB.

    The clones start with the schema only (no seed data), so any 500
    here means a route is exploding on an empty result set — that's
    a real regression worth catching before refactoring.
    """
    response = logged_in_client.get(path)
    assert response.status_code == 200, (
        f'GET {path} returned {response.status_code}; first 500 bytes: '
        f'{response.get_data(as_text=True)[:500]}'
    )


def test_calendar_view_returns_ok(logged_in_client):
    response = logged_in_client.get('/calendar')
    assert response.status_code == 200
