"""Coverage for OIDC single sign-on.

Three tiers, matching how the feature is layered:

* **Config** (no DB, no app) — the env-var parsing in
  :mod:`colony_manager_gui.oidc`.
* **Account resolution** (DB) — :func:`resolve_user`, which decides
  *which* local account a verified claim set maps onto. This is where
  the security-relevant policy lives, so it gets the most attention.
* **Routes** (DB + app) — that the flow is wired up and degrades
  sensibly with no provider configured.

The OAuth dance itself (redirect, state, token exchange, JWKS signature
and nonce validation) is Authlib's, and is not re-tested here; these
tests start from the claims it hands back.
"""
import pytest
from sqlalchemy import select

from colony_manager.models import User
from colony_manager_gui.oidc import load_oidc_config
from colony_manager_gui.services.sso import SSOError, resolve_user

from .factories import make_user


ISSUER = 'https://login.example.edu'


def claims(**overrides):
    """A plausible ID-token claim set, overridable per test."""
    base = {
        'iss': ISSUER,
        'sub': 'subject-abc-123',
        'email': 'alice@example.edu',
        'email_verified': True,
        'given_name': 'Alice',
        'family_name': 'Anderson',
    }
    base.update(overrides)
    return base


def config(**overrides):
    base = {
        'enabled': True,
        'issuer': ISSUER,
        'discovery_url': f'{ISSUER}/.well-known/openid-configuration',
        'auto_provision': False,
        'auto_activate': False,
        'allowed_domains': [],
        'require_verified_email': True,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Config parsing (unit — no DB)
# ---------------------------------------------------------------------------

def test_config_disabled_when_unset(monkeypatch):
    for var in ('OIDC_CLIENT_ID', 'OIDC_CLIENT_SECRET',
                'OIDC_DISCOVERY_URL', 'OIDC_ISSUER'):
        monkeypatch.delenv(var, raising=False)
    assert load_oidc_config()['enabled'] is False


def test_config_enabled_requires_all_three(monkeypatch):
    monkeypatch.setenv('OIDC_CLIENT_ID', 'cid')
    monkeypatch.setenv('OIDC_CLIENT_SECRET', 'secret')
    monkeypatch.delenv('OIDC_DISCOVERY_URL', raising=False)
    monkeypatch.delenv('OIDC_ISSUER', raising=False)
    assert load_oidc_config()['enabled'] is False

    monkeypatch.setenv('OIDC_ISSUER', ISSUER)
    cfg = load_oidc_config()
    assert cfg['enabled'] is True
    # Discovery URL is derived from the issuer when not given explicitly.
    assert cfg['discovery_url'] == f'{ISSUER}/.well-known/openid-configuration'


def test_config_always_requests_openid_scope(monkeypatch):
    monkeypatch.setenv('OIDC_SCOPES', 'email profile')
    assert load_oidc_config()['scopes'].split()[0] == 'openid'


def test_config_parses_domains_and_flags(monkeypatch):
    monkeypatch.setenv('OIDC_ALLOWED_DOMAINS', 'OHSU.edu, @example.edu ,')
    monkeypatch.setenv('OIDC_AUTO_PROVISION', 'yes')
    monkeypatch.setenv('OIDC_REQUIRE_VERIFIED_EMAIL', 'off')
    cfg = load_oidc_config()
    assert cfg['allowed_domains'] == ['ohsu.edu', 'example.edu']
    assert cfg['auto_provision'] is True
    assert cfg['require_verified_email'] is False


# ---------------------------------------------------------------------------
# Account resolution — matching an existing account
# ---------------------------------------------------------------------------

def test_first_login_links_existing_account_by_email(db_session):
    user = make_user(db_session, email='alice@example.edu', active=True)
    assert user.oidc_subject is None

    resolved = resolve_user(db_session, claims(), config())

    assert resolved.id == user.id
    assert resolved.oidc_subject == 'subject-abc-123'
    assert resolved.oidc_issuer == ISSUER


def test_email_match_is_case_insensitive(db_session):
    user = make_user(db_session, email='Alice@Example.edu', active=True)
    resolved = resolve_user(db_session, claims(email='ALICE@example.edu'), config())
    assert resolved.id == user.id


def test_linked_account_matches_by_subject_not_email(db_session):
    """The whole point of storing ``sub``: email churn can't orphan a user."""
    user = make_user(db_session, email='alice@example.edu', active=True)
    resolve_user(db_session, claims(), config())

    # The institution renames her. Same subject, different address.
    resolved = resolve_user(
        db_session, claims(email='alice.anderson@example.edu'), config(),
    )
    assert resolved.id == user.id
    # ...and the local record follows the directory.
    assert resolved.email == 'alice.anderson@example.edu'


def test_local_password_still_works_after_linking(db_session):
    user = make_user(db_session, email='alice@example.edu',
                     password='Local-Pass1!', active=True)
    resolve_user(db_session, claims(), config())
    assert user.check_password('Local-Pass1!')
    assert user.has_password
    assert user.is_sso_linked


def test_account_linked_to_another_subject_is_refused(db_session):
    """An address handed to a new person must not inherit the old account."""
    make_user(db_session, email='alice@example.edu', active=True)
    resolve_user(db_session, claims(), config())

    with pytest.raises(SSOError, match='different single sign-on identity'):
        resolve_user(db_session, claims(sub='somebody-else-999'), config())


def test_different_issuer_does_not_match_existing_link(db_session):
    """``sub`` is only unique within an issuer, so the pair is the identity."""
    make_user(db_session, email='alice@example.edu', active=True)
    resolve_user(db_session, claims(), config())

    other = config(issuer='https://evil.example.com')
    with pytest.raises(SSOError):
        # Same subject string, different issuer: falls through to the email
        # tier, finds an account already linked elsewhere, and refuses.
        resolve_user(
            db_session, claims(iss='https://evil.example.com'), other,
        )


# ---------------------------------------------------------------------------
# Account resolution — policy gates
# ---------------------------------------------------------------------------

def test_unverified_email_refused(db_session):
    make_user(db_session, email='alice@example.edu', active=True)
    with pytest.raises(SSOError, match='not a verified address'):
        resolve_user(db_session, claims(email_verified=False), config())


def test_absent_email_verified_claim_is_allowed(db_session):
    """Many IdPs simply don't emit it; only an explicit false is a refusal."""
    user = make_user(db_session, email='alice@example.edu', active=True)
    payload = claims()
    del payload['email_verified']
    assert resolve_user(db_session, payload, config()).id == user.id


def test_domain_outside_allowlist_refused(db_session):
    make_user(db_session, email='alice@example.edu', active=True)
    with pytest.raises(SSOError, match='not in a domain permitted'):
        resolve_user(db_session, claims(), config(allowed_domains=['ohsu.edu']))


def test_domain_allowlist_not_reapplied_to_linked_account(db_session):
    """Tightening the list later must not lock out already-linked users."""
    user = make_user(db_session, email='alice@example.edu', active=True)
    resolve_user(db_session, claims(), config())
    resolved = resolve_user(
        db_session, claims(), config(allowed_domains=['ohsu.edu']),
    )
    assert resolved.id == user.id


def test_missing_email_claim_refused(db_session):
    payload = claims()
    del payload['email']
    with pytest.raises(SSOError, match='did not return an email'):
        resolve_user(db_session, payload, config())


def test_preferred_username_used_as_email_fallback(db_session):
    user = make_user(db_session, email='alice@example.edu', active=True)
    payload = claims()
    del payload['email']
    payload['preferred_username'] = 'alice@example.edu'
    assert resolve_user(db_session, payload, config()).id == user.id


def test_missing_subject_refused(db_session):
    payload = claims()
    del payload['sub']
    with pytest.raises(SSOError, match='no subject claim'):
        resolve_user(db_session, payload, config())


# ---------------------------------------------------------------------------
# Account resolution — provisioning
# ---------------------------------------------------------------------------

def test_unknown_user_refused_without_auto_provision(db_session):
    with pytest.raises(SSOError, match='No Colony Manager account exists'):
        resolve_user(db_session, claims(), config())
    assert db_session.scalars(select(User)).all() == []


def test_auto_provision_creates_inactive_account(db_session):
    with pytest.raises(SSOError, match='awaiting administrator approval'):
        resolve_user(db_session, claims(), config(auto_provision=True))

    user = db_session.scalars(
        select(User).where(User.email == 'alice@example.edu')
    ).one()
    assert user.active is False
    assert user.admin is False
    assert user.oidc_subject == 'subject-abc-123'
    # SSO-only: no password hash, and the local form can't be used.
    assert user.has_password is False
    assert user.check_password('') is False
    assert user.check_password('anything') is False


def test_auto_provision_with_auto_activate_signs_in(db_session):
    user = resolve_user(
        db_session, claims(), config(auto_provision=True, auto_activate=True),
    )
    assert user.active is True
    assert user.first_name == 'Alice'
    assert user.last_name == 'Anderson'


def test_auto_provision_falls_back_to_name_claim(db_session):
    payload = claims()
    del payload['given_name']
    del payload['family_name']
    payload['name'] = 'Alice Q Anderson'
    user = resolve_user(
        db_session, payload, config(auto_provision=True, auto_activate=True),
    )
    assert (user.first_name, user.last_name) == ('Alice', 'Q Anderson')


def test_auto_provision_survives_no_name_claims_at_all(db_session):
    payload = claims()
    for key in ('given_name', 'family_name'):
        del payload[key]
    user = resolve_user(
        db_session, payload, config(auto_provision=True, auto_activate=True),
    )
    assert user.first_name == 'alice'
    assert user.last_name == ''


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def test_login_page_hides_sso_button_when_disabled(client, db_session):
    response = client.get('/auth/login')
    assert response.status_code == 200
    assert b'Sign in with' not in response.data


def test_sso_login_redirects_to_login_when_disabled(client, db_session):
    """No provider configured: a bookmarked /auth/sso/login must not 500."""
    response = client.get('/auth/sso/login', follow_redirects=False)
    assert response.status_code == 302
    assert '/auth/login' in response.headers['Location']


def test_sso_endpoints_are_public(app):
    """They must be reachable while logged out, or nobody can ever log in."""
    for endpoint in ('auth.sso_login', 'auth.sso_callback'):
        view = app.view_functions[endpoint]
        assert getattr(view, '_colony_public', False) is True


@pytest.fixture
def sso_app(test_db, monkeypatch):
    """An app booted with a provider configured, bound to the test DB.

    The plain ``app`` fixture deliberately has no OIDC env, so it covers
    the SSO-disabled half; this covers the enabled half. No network is
    touched — Authlib fetches the discovery document lazily, on the first
    request that actually needs an endpoint.
    """
    from colony_manager_gui import create_app

    monkeypatch.setenv('OIDC_CLIENT_ID', 'colony-manager')
    monkeypatch.setenv('OIDC_CLIENT_SECRET', 'shhh')
    monkeypatch.setenv('OIDC_ISSUER', ISSUER)
    monkeypatch.setenv('OIDC_PROVIDER_NAME', 'Example Login')
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SESSION_COOKIE_SECURE'] = False
    return app


def test_configured_app_registers_client_and_shows_button(sso_app):
    from colony_manager_gui.oidc import CLIENT_NAME

    assert sso_app.config['OIDC']['enabled'] is True
    oauth = sso_app.extensions['authlib.integrations.flask_client']
    assert getattr(oauth, CLIENT_NAME) is not None

    page = sso_app.test_client().get('/auth/login')
    assert page.status_code == 200
    assert b'Sign in with Example Login' in page.data


def test_callback_uri_is_https_behind_proxy(sso_app):
    """The URI registered with the IdP is https; Flask must build it so.

    Without ProxyFix this comes out ``http://internal:5000/...`` and the
    provider rejects the whole flow with a redirect_uri mismatch.
    """
    from flask import url_for

    # ProxyFix is WSGI middleware, so the headers only take effect on a
    # request that actually goes through ``app.wsgi_app`` — a bare
    # test_request_context would bypass it and prove nothing.
    seen = {}

    @sso_app.before_request
    def _capture():
        seen['uri'] = url_for('auth.sso_callback', _external=True)

    sso_app.test_client().get(
        '/auth/login', base_url='http://internal:5000',
        headers={'X-Forwarded-Proto': 'https',
                 'X-Forwarded-Host': 'colony.example.edu'},
    )
    assert seen['uri'] == 'https://colony.example.edu/auth/sso/callback'


def test_sso_login_survives_an_unreachable_provider(sso_app, monkeypatch):
    """An IdP outage must not be a 500.

    Building the authorization redirect fetches the provider's discovery
    document, so a DNS failure or a 503 at the IdP lands in this route,
    not the callback. A 500 there tells the user nothing and generates a
    support call; the local password form still works, so the flash says
    so.
    """
    from colony_manager_gui.oidc import CLIENT_NAME

    oauth = sso_app.extensions['authlib.integrations.flask_client']
    client = getattr(oauth, CLIENT_NAME)

    def _boom(*args, **kwargs):
        raise OSError('[Errno -2] Name or service not known')

    monkeypatch.setattr(client, 'authorize_redirect', _boom)

    response = sso_app.test_client().get(
        '/auth/sso/login', follow_redirects=False,
    )
    assert response.status_code == 302
    assert '/auth/login' in response.headers['Location']

    page = sso_app.test_client().get('/auth/sso/login', follow_redirects=True)
    assert b'temporarily unavailable' in page.data
    assert b'password' in page.data


def test_sso_login_rejects_offsite_next(client, db_session):
    """``next`` is attacker-supplied; it's host-checked before being parked."""
    response = client.get(
        '/auth/sso/login?next=https://evil.example.com/steal',
        follow_redirects=False,
    )
    assert response.status_code == 400
