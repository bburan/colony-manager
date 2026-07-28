import os
import datetime
from flask import Flask, session
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from colony_manager import models  # noqa: F401  (imported for side effects)
from colony_manager import db as _cm_db
from colony_manager.datatypes import cache_root


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


def create_app():
    app = Flask(__name__)

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
    from colony_manager_gui.routes.util import get_or_404

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(cages_bp, url_prefix='/cages')
    app.register_blueprint(animals_bp, url_prefix='/animals')
    app.register_blueprint(breeding_bp, url_prefix='/breeding')
    app.register_blueprint(histology_bp, url_prefix='/histology')
    app.register_blueprint(studies_bp, url_prefix='/studies')
    app.register_blueprint(data_files_bp)

    login_manager.init_app(app)
    csrf.init_app(app)

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
        return {
            'datetime': datetime,
            'species': db.session.scalars(select(Species)).all(),
            'selected_species': selected_species,
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
