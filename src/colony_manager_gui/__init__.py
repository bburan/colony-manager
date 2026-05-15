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


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['THUMBNAIL_CACHE_DIR'] = os.environ.get(
        'THUMBNAIL_CACHE_DIR',
    ) or str(cache_root('thumbnails'))
    app.config['THUMBNAIL_MAX_SIZE'] = int(os.environ.get('THUMBNAIL_MAX_SIZE', '300'))

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

    # Make ``Model.query`` / ``cls.session`` work across the
    # ``colony_manager`` package. The library doesn't subclass
    # ``flask_sqlalchemy.Model`` — it has its own declarative ``Base`` —
    # so Flask-SQLAlchemy's auto-attached query property doesn't apply.
    # ``bind_models`` is the public entry point; non-Flask callers
    # (scripts, tests) call it themselves before issuing queries.
    with app.app_context():
        models.bind_models(db.session)

    return app
