import os
import datetime
from flask import Flask, session
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import MetaData

# Setup versioning
from sqlalchemy_continuum import make_versioned
from sqlalchemy_continuum.plugins import FlaskPlugin
make_versioned(user_cls='User', plugins=[FlaskPlugin()])

# Import extensions
from flask_sqlalchemy import SQLAlchemy

# Must come last
from colony_manager import models
from colony_manager.datatypes import cache_root

# Hack to emulate Flask session and query properties.
db = SQLAlchemy(metadata=models.Base.metadata)

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
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    # ``pool_pre_ping`` validates a connection before handing it out.
    # Important for the RQ worker: after ``fork()`` the child inherits
    # the parent's pool, and the parent's TCP connections are no longer
    # safe in the child. pre_ping detects + recycles those silently.
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
    app.config['THUMBNAIL_CACHE_DIR'] = os.environ.get(
        'THUMBNAIL_CACHE_DIR',
    ) or str(cache_root('thumbnails'))
    app.config['THUMBNAIL_MAX_SIZE'] = int(os.environ.get('THUMBNAIL_MAX_SIZE', '300'))

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
    from colony_manager_gui.routes.util import AppQuery

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(cages_bp, url_prefix='/cages')
    app.register_blueprint(animals_bp, url_prefix='/animals')
    app.register_blueprint(breeding_bp, url_prefix='/breeding')
    app.register_blueprint(histology_bp, url_prefix='/histology')
    app.register_blueprint(studies_bp, url_prefix='/studies')
    app.register_blueprint(data_files_bp)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    @app.context_processor
    def inject_global_vars():
        from sqlalchemy import select
        from colony_manager.models import Species
        from colony_manager_gui.forms import CSRFOnlyForm
        species_id = int(session.get('selected_species', -1))
        if species_id != -1:
            selected_species = db.get_or_404(Species, species_id).name
        else:
            selected_species = 'All'
        return {
            'datetime': datetime,
            'species': db.session.scalars(select(Species)).all(),
            'selected_species': selected_species,
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

    return app
