"""Coverage for the HTTPS posture: canonical redirect and security headers.

The app never terminates TLS — a reverse proxy does (docs/https.md) — so
what's testable here is how the app behaves *given* that proxy: does it
notice the forwarded scheme, does it move users off the plain-http
origin, and does it emit the right headers.
"""
import pytest


# A non-default port, matching the real deployment: DSM's reverse proxy
# listens on 9001 because 443 is taken by DSM's own UI. The port is what
# makes the loop-safety tests below worth having.
CANONICAL = 'https://mmm.example.edu:9001'


@pytest.fixture
def https_app(test_db, monkeypatch):
    """An app booted with a canonical HTTPS origin configured."""
    from colony_manager_gui import create_app

    monkeypatch.setenv('CANONICAL_BASE_URL', CANONICAL)
    monkeypatch.setenv('TRUSTED_PROXY_COUNT', '1')
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    return app


def _get(app, path, **kwargs):
    return app.test_client().get(path, **kwargs)


# ---------------------------------------------------------------------------
# Canonical-origin redirect
# ---------------------------------------------------------------------------

def test_plain_http_is_redirected_to_canonical(https_app):
    response = _get(https_app, '/auth/login', base_url='http://mmm.example.edu:9001')
    assert response.status_code == 308
    assert response.headers['Location'] == f'{CANONICAL}/auth/login'


def test_redirect_preserves_query_string(https_app):
    response = _get(
        https_app, '/auth/login?next=%2Fanimals',
        base_url='http://mmm.example.edu:9001',
    )
    assert response.status_code == 308
    assert response.headers['Location'] == f'{CANONICAL}/auth/login?next=%2Fanimals'


def test_no_redirect_when_already_canonical(https_app):
    """A request the proxy forwarded from the canonical origin passes through."""
    response = _get(
        https_app, '/auth/login', base_url='http://internal:5000',
        headers={'X-Forwarded-Proto': 'https',
                 'X-Forwarded-Host': 'mmm.example.edu:9001'},
    )
    assert response.status_code == 200


@pytest.mark.parametrize('forwarded_host', [
    'mmm.example.edu',        # nginx $host — drops the non-default port
    'localhost:9002',         # proxy forwarded its own backend address
    'internal:5000',          # no X-Forwarded-Host at all
])
def test_https_never_redirects_whatever_host_the_proxy_reports(
        https_app, forwarded_host):
    """The redirect must not loop when the proxy's Host isn't the public one.

    With a non-default port in the canonical URL this is the failure that
    matters: comparing ``request.host`` to the canonical netloc mismatches
    forever in all three of these shapes, so each request redirects, comes
    back through the proxy with the same unexpected Host, and redirects
    again. Keying the check on the scheme alone makes it impossible.
    """
    response = _get(
        https_app, '/auth/login', base_url='http://internal:5000',
        headers={'X-Forwarded-Proto': 'https',
                 'X-Forwarded-Host': forwarded_host},
    )
    assert response.status_code != 308, (
        f'redirect loop: an https request reporting Host={forwarded_host!r} '
        'was redirected back to the canonical URL'
    )


def test_redirect_runs_before_the_login_gate(https_app):
    """Wrong origin + not logged in must redirect to the right origin.

    If ``check_login`` ran first the user would be bounced to the login
    page on the *wrong* host, and only then redirected — two hops, and the
    ``next`` they came in with points at the plain-http origin.
    """
    response = _get(https_app, '/animals/', base_url='http://mmm.example.edu:9001')
    assert response.status_code == 308
    assert response.headers['Location'].startswith(CANONICAL)


def test_no_redirect_configured_without_canonical_base_url(app):
    """The plain ``app`` fixture sets no canonical origin: nothing redirects."""
    response = app.test_client().get('/auth/login', base_url='http://localhost')
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

def test_security_headers_present(client, db_session):
    response = client.get('/auth/login')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert response.headers['Referrer-Policy'] == 'same-origin'


def test_hsts_absent_by_default(https_app):
    response = _get(
        https_app, '/auth/login', base_url='http://internal:5000',
        headers={'X-Forwarded-Proto': 'https',
                 'X-Forwarded-Host': 'mmm.example.edu:9001'},
    )
    assert 'Strict-Transport-Security' not in response.headers


def test_hsts_sent_over_https_when_enabled(test_db, monkeypatch):
    from colony_manager_gui import create_app

    monkeypatch.setenv('CANONICAL_BASE_URL', CANONICAL)
    monkeypatch.setenv('HSTS_SECONDS', '3600')
    app = create_app()
    app.config['TESTING'] = True

    response = app.test_client().get(
        '/auth/login', base_url='http://internal:5000',
        headers={'X-Forwarded-Proto': 'https',
                 'X-Forwarded-Host': 'mmm.example.edu:9001'},
    )
    assert response.headers['Strict-Transport-Security'] == \
        'max-age=3600; includeSubDomains'


def test_hsts_not_sent_over_plain_http(test_db, monkeypatch):
    """Never advertise HSTS on a connection that isn't actually secure."""
    from colony_manager_gui import create_app

    monkeypatch.setenv('HSTS_SECONDS', '3600')
    monkeypatch.delenv('CANONICAL_BASE_URL', raising=False)
    app = create_app()
    app.config['TESTING'] = True

    response = app.test_client().get('/auth/login', base_url='http://localhost')
    assert 'Strict-Transport-Security' not in response.headers


# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------

def test_preferred_scheme_follows_canonical_base_url(https_app):
    assert https_app.config['PREFERRED_URL_SCHEME'] == 'https'


def test_preferred_scheme_defaults_to_https(app):
    """Out-of-request URL building (CLI, RQ jobs) shouldn't emit http://."""
    assert app.config['PREFERRED_URL_SCHEME'] == 'https'


def test_proxy_fix_can_be_disabled(test_db, monkeypatch):
    """A directly-exposed deployment must be able to stop trusting headers."""
    from colony_manager_gui import create_app
    from flask import url_for

    monkeypatch.setenv('TRUSTED_PROXY_COUNT', '0')
    monkeypatch.delenv('CANONICAL_BASE_URL', raising=False)
    app = create_app()
    app.config['TESTING'] = True

    seen = {}

    @app.before_request
    def _capture():
        seen['uri'] = url_for('auth.login_user', _external=True)

    app.test_client().get(
        '/auth/login', base_url='http://internal:5000',
        headers={'X-Forwarded-Proto': 'https',
                 'X-Forwarded-Host': 'evil.example.com'},
    )
    # The forged headers were ignored: the URI reflects the real request.
    assert seen['uri'] == 'http://internal:5000/auth/login'
