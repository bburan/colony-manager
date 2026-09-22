"""OpenID Connect (SSO) client wiring.

The deployment points this at the institution's OIDC provider (for the
reference deployment, OHSU's) and users get a "Sign in with ..." button
next to the local password form. Everything here is optional: with no
``OIDC_CLIENT_ID`` in the environment the app boots and behaves exactly
as it did before, SSO button included nowhere.

Configuration is env-driven, read once in :func:`load_oidc_config` and
stashed on ``app.config['OIDC']``:

``OIDC_CLIENT_ID`` / ``OIDC_CLIENT_SECRET``
    Credentials issued by the identity provider when the application is
    registered with them. Both required to enable SSO.
``OIDC_DISCOVERY_URL``
    Full URL of the provider's ``.well-known/openid-configuration``
    document. Alternatively set ``OIDC_ISSUER`` and the discovery URL is
    derived from it. Everything else (authorization, token, userinfo,
    JWKS, end-session endpoints) is read from that document at runtime,
    so endpoint churn on the IdP side needs no redeploy.
``OIDC_PROVIDER_NAME``
    Label on the sign-in button. Default ``"Single Sign-On"``.
``OIDC_SCOPES``
    Default ``"openid email profile"``. ``openid`` is always included.
``OIDC_AUTO_PROVISION`` (default off)
    Create a local account the first time an unrecognised SSO identity
    signs in. Off means SSO can only sign in to accounts that already
    exist — the admin-approval model the local signup flow already uses.
``OIDC_AUTO_ACTIVATE`` (default off)
    Auto-provisioned accounts start ``active`` instead of waiting for an
    admin. Only meaningful with ``OIDC_AUTO_PROVISION`` on; combined they
    mean "anyone the IdP vouches for may use the app".
``OIDC_ALLOWED_DOMAINS``
    Comma-separated email domains permitted to sign in (e.g.
    ``ohsu.edu``). Empty means any domain the IdP hands us.
``OIDC_REQUIRE_VERIFIED_EMAIL`` (default on)
    Reject logins whose ``email_verified`` claim is explicitly false.
    Accounts are matched by email on first login, so an unverified
    address is an account-takeover primitive — leave this on unless the
    IdP is known not to emit the claim at all.
``OIDC_RP_LOGOUT`` (default off)
    On logout, also redirect to the provider's ``end_session_endpoint``
    so the session is dropped at the IdP, not just locally.
"""
import os

# Registered name of the OAuth client. Used as the attribute on the
# Authlib registry (``oauth.sso``) and in session keys.
CLIENT_NAME = 'sso'


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def load_oidc_config():
    """Read the OIDC settings out of the environment.

    Returns a dict that is always safe to consult; ``enabled`` is False
    when the deployment hasn't configured a provider.
    """
    client_id = os.environ.get('OIDC_CLIENT_ID', '').strip()
    client_secret = os.environ.get('OIDC_CLIENT_SECRET', '').strip()
    discovery_url = os.environ.get('OIDC_DISCOVERY_URL', '').strip()
    issuer = os.environ.get('OIDC_ISSUER', '').strip().rstrip('/')

    if not discovery_url and issuer:
        discovery_url = f'{issuer}/.well-known/openid-configuration'

    scopes = os.environ.get('OIDC_SCOPES', '').strip() or 'openid email profile'
    if 'openid' not in scopes.split():
        scopes = f'openid {scopes}'

    domains = [
        d.strip().lower().lstrip('@')
        for d in os.environ.get('OIDC_ALLOWED_DOMAINS', '').split(',')
        if d.strip()
    ]

    return {
        'enabled': bool(client_id and client_secret and discovery_url),
        'client_id': client_id,
        'client_secret': client_secret,
        'discovery_url': discovery_url,
        'issuer': issuer,
        'scopes': scopes,
        'provider_name': (
            os.environ.get('OIDC_PROVIDER_NAME', '').strip() or 'Single Sign-On'
        ),
        'auto_provision': _env_flag('OIDC_AUTO_PROVISION'),
        'auto_activate': _env_flag('OIDC_AUTO_ACTIVATE'),
        'allowed_domains': domains,
        'require_verified_email': _env_flag('OIDC_REQUIRE_VERIFIED_EMAIL', True),
        'rp_logout': _env_flag('OIDC_RP_LOGOUT'),
    }


def init_oidc(app):
    """Register the OIDC client on ``app`` if the env configures one.

    Stores the resolved config at ``app.config['OIDC']`` and the Authlib
    registry at ``app.extensions['authlib.integrations.flask_client']``
    (Authlib's own convention). A misconfiguration — provider credentials
    set but Authlib not installed — is a boot-time crash rather than a
    sign-in button that 500s, matching how the description registry is
    validated.
    """
    config = load_oidc_config()
    app.config['OIDC'] = config
    if not config['enabled']:
        return None

    try:
        from authlib.integrations.flask_client import OAuth
    except ImportError as exc:  # pragma: no cover - depends on install extras
        # Name the module that actually failed: Authlib's Flask client
        # pulls in ``requests`` as its HTTP backend, so "no module named
        # requests" is the more common of the two failures here.
        raise RuntimeError(
            f'OIDC is configured but its dependencies are missing ({exc}). '
            'Install the gui extra (`pip install -e ".[gui]"`) or unset the '
            'OIDC_* variables to disable SSO.'
        ) from exc

    oauth = OAuth(app)
    oauth.register(
        name=CLIENT_NAME,
        client_id=config['client_id'],
        client_secret=config['client_secret'],
        server_metadata_url=config['discovery_url'],
        client_kwargs={
            'scope': config['scopes'],
            # PKCE. Harmless for a confidential client, and required by a
            # growing number of institutional IdPs.
            'code_challenge_method': 'S256',
        },
    )
    return oauth


def get_oidc_client():
    """Return the registered Authlib client, or None when SSO is off."""
    from flask import current_app

    if not current_app.config.get('OIDC', {}).get('enabled'):
        return None
    oauth = current_app.extensions.get('authlib.integrations.flask_client')
    if oauth is None:
        return None
    return getattr(oauth, CLIENT_NAME, None)


def oidc_config():
    """The resolved OIDC settings for the current app."""
    from flask import current_app

    return current_app.config.get('OIDC') or {'enabled': False}


def oidc_enabled():
    return bool(oidc_config().get('enabled'))


def end_session_url(post_logout_redirect_uri=None, id_token=None):
    """Build the provider's RP-initiated logout URL, or None.

    Returns None when RP logout is switched off or the provider's
    discovery document advertises no ``end_session_endpoint`` — callers
    then fall back to a purely local logout.
    """
    from urllib.parse import urlencode

    config = oidc_config()
    if not config.get('enabled') or not config.get('rp_logout'):
        return None
    client = get_oidc_client()
    if client is None:
        return None
    try:
        metadata = client.load_server_metadata()
    except Exception:  # pragma: no cover - network/IdP failure
        return None
    endpoint = metadata.get('end_session_endpoint')
    if not endpoint:
        return None

    params = {}
    if post_logout_redirect_uri:
        params['post_logout_redirect_uri'] = post_logout_redirect_uri
    if id_token:
        params['id_token_hint'] = id_token
    else:
        # Without an id_token_hint most providers need to be told which
        # client is asking before they'll honour the redirect.
        params['client_id'] = config['client_id']
    return f'{endpoint}?{urlencode(params)}' if params else endpoint
