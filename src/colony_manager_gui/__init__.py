import os
import datetime
from flask import Flask, session
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from colony_manager import models  # noqa: F401  (imported for side effects)
from colony_manager import db as _cm_db
from colony_manager.datatypes import cache_root
from colony_manager_gui.oidc import init_oidc


class _DBProxy:
    """Thin shim exposing the unified scoped session as ``db.session``.

    Routes, forms, sync, and worker code historically reached into a
    Flask-SQLAlchemy ``db.session``. We've moved the single source of
    truth to :mod:`colony_manager.db`, but keep this proxy so the
    ``db.session.xxx`` call shape works unchanged. ``.session`` is a
    property (not a cached attribute) so each access goes through the
    scoped registry — that's what makes it safe in both request
    threads and forked RQ workers.
    """

    @property
    def session(self):
        return _cm_db.get_session()


db = _DBProxy()

login_manager = LoginManager()
csrf = CSRFProtect()


def _configure_rq(app):
    """Build the RQ Queue and attach it to ``app.rq_queue``.

    Reads ``REDIS_URL`` from the environment. If unset, drops to
    fakeredis + synchronous execution so the Flask app can boot
    on a dev machine (or in pytest) without a live Redis service.
    """
    import redis as redis_lib
    from rq import Queue

    redis_url = os.environ.get('REDIS_URL')
    if redis_url:
        connection = redis_lib.from_url(redis_url)
        is_async = True
    else:
        try:
            import fakeredis
        except ImportError as exc:
            raise RuntimeError(
                'REDIS_URL is required when fakeredis is not installed. '
                'Set REDIS_URL or `pip install fakeredis` (test extras).'
            ) from exc
        connection = fakeredis.FakeStrictRedis()
        is_async = False
        app.logger.info(
            'REDIS_URL not set; using fakeredis + synchronous RQ '
            '(jobs run inline in the request thread).'
        )

    app.rq_queue = Queue('sync', connection=connection, is_async=is_async)


def _configure_https(app):
    """Canonical-URL redirect and transport-security headers.

    The app never terminates TLS itself — a reverse proxy in front does
    that (see ``docs/https.md``) — so "supporting https" here means three
    narrower things: building https URLs when there's no request to take
    a scheme from, not leaving the plain-http door quietly usable, and
    telling the browser to stay on https.

    ``CANONICAL_BASE_URL`` (e.g. ``https://mmm.ohsu.edu:9001``) is the one
    worth setting. Any request arriving over plain http is redirected to
    it, which matters more than it first looks: the
    container publishes its own port, and that stays reachable over
    plain http after a proxy goes in front. A user on the old URL would
    otherwise hit a thoroughly confusing failure — the session cookie is
    ``Secure``, so the browser never sends it, so the OIDC state never
    comes back, so every sign-in dies with ``mismatching_state``.
    Redirecting is much kinder than diagnosing that.

    ``HSTS_SECONDS`` is off by default on purpose. Once a browser has
    seen that header it refuses plain http to the host for the whole
    max-age and the server cannot retract it, so it's the last switch to
    flip, after https is known good.
    """
    from urllib.parse import urlsplit

    canonical = os.environ.get('CANONICAL_BASE_URL', '').strip().rstrip('/')
    hsts_seconds = int(os.environ.get('HSTS_SECONDS', '0'))

    # Only consulted when a URL is built outside a request context (CLI
    # commands, RQ jobs); inside a request the real scheme wins.
    app.config['PREFERRED_URL_SCHEME'] = (
        urlsplit(canonical).scheme if canonical
        else os.environ.get('PREFERRED_URL_SCHEME', 'https')
    )

    if canonical:
        @app.before_request
        def _redirect_to_canonical():
            from flask import redirect, request

            # Deliberately keyed on the scheme alone, not on host or port.
            #
            # The tempting version compares ``request.host`` against the
            # canonical netloc, and it loops. Whether the app can even see
            # the public host:port depends on what the proxy puts in
            # ``Host``/``X-Forwarded-Host`` — nginx's ``$host`` drops the
            # port, and some configurations forward the *backend* address
            # instead. Any of those makes a host comparison mismatch
            # forever: redirect to the canonical URL, proxy forwards it
            # back with the same unexpected Host, redirect again.
            #
            # Keying on the scheme is loop-proof, because the canonical URL
            # is https and a proxied https request reports is_secure once
            # X-Forwarded-Proto is read. It also still does the job that
            # matters: moving anyone on plain http onto https, whatever
            # host or port they arrived on.
            if request.is_secure:
                return
            # 308 rather than 301: it preserves the method and body, so a
            # POST landing on the wrong origin isn't silently turned into
            # a GET of the same path.
            path = request.full_path
            if path.endswith('?'):
                path = path[:-1]
            return redirect(f'{canonical}{path}', code=308)

    @app.after_request
    def _security_headers(response):
        from flask import request

        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'same-origin')
        if hsts_seconds and request.is_secure:
            response.headers.setdefault(
                'Strict-Transport-Security',
                f'max-age={hsts_seconds}; includeSubDomains',
            )
        return response


def _validate_description_registry():
    """Fail fast at startup if the description registry is misconfigured.

    When ``COLONY_MANAGER_DESCRIPTION_REGISTRY`` is set, eagerly import the
    registry — and therefore every ``DataTypeDescription`` subclass it lists —
    so a broken/renamed dependency surfaces as a boot-time crash rather than a
    silently empty data-files/rating page. The env var is optional by design
    (the non-data parts of the app run without it), so an *unset* var is not an
    error; anything else (bad module, a description class that fails to import,
    a malformed registry) raises and stops the app from booting.
    """
    from colony_manager.datatypes import get_description_class_registry

    if not os.environ.get('COLONY_MANAGER_DESCRIPTION_REGISTRY', '').strip():
        return
    get_description_class_registry()  # raises RuntimeError on any load failure


def create_app():
    app = Flask(__name__)

    # Refuse to boot with a broken description registry (see docstring).
    _validate_description_registry()

    app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
    # ``DATABASE_URL`` is read inside :mod:`colony_manager.db` — both the
    # engine binding and ``pool_pre_ping`` live there now, so the web,
    # workers, and standalone scripts all share one configuration path.
    app.config['THUMBNAIL_CACHE_DIR'] = os.environ.get(
        'THUMBNAIL_CACHE_DIR',
    ) or str(cache_root('thumbnails'))
    app.config['THUMBNAIL_MAX_SIZE'] = int(os.environ.get('THUMBNAIL_MAX_SIZE', '300'))
    # Cap multipart upload bodies. Flask short-circuits with 413 when a
    # request exceeds this; the upload route catches that and flashes a
    # friendly message. Default 100 MiB; override via env for sites that
    # need to accept larger videos.
    app.config['MAX_CONTENT_LENGTH'] = (
        int(os.environ.get('COLONY_MANAGER_MAX_UPLOAD_MB', '100')) * 1024 * 1024
    )
    # In debug mode the navbar is tinted so a dev instance is never
    # mistaken for production (or another local site). Override the colour
    # per deployment via env so each site can be told apart at a glance;
    # default is an amber "caution" tint.
    app.config['NAVBAR_DEBUG_COLOR'] = os.environ.get(
        'NAVBAR_DEBUG_COLOR', '#ffda6a'
    )

    # Session cookie hardening. The OIDC round trip bounces the browser
    # out to the identity provider and back, and the state/nonce that
    # secures that exchange rides in this cookie — SameSite=Strict would
    # drop it on the return leg, so Lax is the tightest setting the flow
    # allows. ``Secure`` defaults on and is only worth clearing for a
    # plain-http dev instance.
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = (
        os.environ.get('SESSION_COOKIE_SECURE', 'true').strip().lower()
        not in ('0', 'false', 'no', 'off')
    )

    # --- HTTPS posture ---
    # Registered before the blueprints so the canonical-URL redirect runs
    # ahead of ``check_login`` — a user on the wrong origin should be moved
    # to the right one, not bounced to a login page there first.
    _configure_https(app)

    # --- Single sign-on (OIDC) ---
    # No-op unless the deployment sets OIDC_CLIENT_ID/SECRET + a discovery
    # URL; see colony_manager_gui/oidc.py and docs/sso.md.
    init_oidc(app)

    # Behind the reverse proxy that terminates TLS, Flask otherwise sees
    # plain http on an internal hostname and builds an ``http://`` redirect
    # URI — which the identity provider rejects, because the registered one
    # is ``https://``. ProxyFix makes url_for(_external=True) honour the
    # X-Forwarded-* headers the proxy sets. Count how many proxies are in
    # front of the app; 0 disables the shim entirely for a direct-exposure
    # deployment (trusting these headers unconditionally would let a client
    # forge them).
    proxy_hops = int(os.environ.get('TRUSTED_PROXY_COUNT', '1'))
    if proxy_hops:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=proxy_hops, x_proto=proxy_hops,
            x_host=proxy_hops, x_port=proxy_hops,
        )

    # --- RQ queue wiring ---
    # REDIS_URL points at a real Redis in prod (set by docker-compose);
    # if unset, fall back to fakeredis with synchronous execution so
    # local dev / unit tests don't require a running Redis or worker.
    _configure_rq(app)

    # Register Blueprints
    from colony_manager_gui.routes.main import main_bp
    from colony_manager_gui.routes.auth import auth_bp
    from colony_manager_gui.routes.cages import cages_bp
    from colony_manager_gui.routes.animals import animals_bp
    from colony_manager_gui.routes.breeding import breeding_bp
    from colony_manager_gui.routes.histology import histology_bp
    from colony_manager_gui.routes.studies import studies_bp
    from colony_manager_gui.routes.data_files import data_files_bp
    from colony_manager_gui.routes.help import help_bp
    from colony_manager_gui.routes.util import get_or_404

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(cages_bp, url_prefix='/cages')
    app.register_blueprint(animals_bp, url_prefix='/animals')
    app.register_blueprint(breeding_bp, url_prefix='/breeding')
    app.register_blueprint(histology_bp, url_prefix='/histology')
    app.register_blueprint(studies_bp, url_prefix='/studies')
    app.register_blueprint(data_files_bp)
    app.register_blueprint(help_bp, url_prefix='/help')

    login_manager.init_app(app)
    csrf.init_app(app)

    # Lets any template ask "does this kind of data document itself?" —
    # the answer comes from the description class's ``help_topic``, which
    # for this deployment is supplied by the data-plugin registry rather
    # than by colony-manager. Returns None (render no button) for anything
    # unresolvable, so templates need no guard beyond a truthiness check.
    from colony_manager_gui.helpdocs import topic_for_description_class
    app.jinja_env.globals['help_topic_for'] = topic_for_description_class

    # Return the scoped session to the registry at the end of each
    # request. Mirrors what Flask-SQLAlchemy used to do for us, but
    # against the unified ``colony_manager.db`` session.
    @app.teardown_appcontext
    def _remove_session(exception=None):
        _cm_db.get_session().remove()

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    @app.context_processor
    def inject_global_vars():
        from sqlalchemy import select
        from colony_manager.models import Species
        from colony_manager_gui.forms.common import CSRFOnlyForm
        species_id = int(session.get('selected_species', -1))
        if species_id != -1:
            selected_species = get_or_404(Species, species_id).name
        else:
            selected_species = 'All'
        age_unit = session.get('age_unit', 'day')
        if age_unit not in ('day', 'week', 'month'):
            age_unit = 'day'
        oidc = app.config.get('OIDC') or {'enabled': False}
        return {
            'datetime': datetime,
            'oidc_enabled': bool(oidc.get('enabled')),
            'oidc_provider_name': oidc.get('provider_name', 'Single Sign-On'),
            'species': db.session.scalars(select(Species)).all(),
            'selected_species': selected_species,
            'selected_species_id': species_id,
            'age_unit': age_unit,
            'csrf_only_form': CSRFOnlyForm(),
        }

    @app.context_processor
    def datetime_processor():
        return dict(datetime=datetime)

    @app.before_request
    def check_login():
        from flask_login import current_user, logout_user
        from flask import request, redirect, url_for, current_app

        # Static files are always allowed — they ship CSS/JS that the
        # login page itself depends on.
        if request.endpoint == 'static':
            return

        if current_user.is_authenticated:
            # A user who was deactivated after logging in must lose access on
            # the next request. ``is_active`` reads the live ``active`` flag.
            if not current_user.is_active:
                logout_user()
                return redirect(url_for('auth.login_user', next=request.url))
            return

        view = current_app.view_functions.get(request.endpoint)
        if view is not None and getattr(view, '_colony_public', False):
            return
        return redirect(url_for('auth.login_user', next=request.url))

    from colony_manager_gui.commands import data_cli
    app.cli.add_command(data_cli, name='data')

    return app
