import os
import datetime
from flask import Flask, session
from flask_login import LoginManager
from sqlalchemy import MetaData

# Setup versioning
from sqlalchemy_continuum import make_versioned
from sqlalchemy_continuum.plugins import FlaskPlugin
make_versioned(user_cls='User', plugins=[FlaskPlugin()])

# Import extensions
from flask_sqlalchemy import SQLAlchemy

# Must come last
from colony_manager import models

# Hack to emulate Flask session and query properties.
db = SQLAlchemy(metadata=models.Base.metadata)

login_manager = LoginManager()


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-very-secret-key-that-is-long-and-secure')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Register Blueprints
    from colony_manager_gui.routes.main import main_bp
    from colony_manager_gui.routes.auth import auth_bp
    from colony_manager_gui.routes.cages import cages_bp
    from colony_manager_gui.routes.animals import animals_bp
    from colony_manager_gui.routes.breeding import breeding_bp
    from colony_manager_gui.routes.histology import histology_bp
    from colony_manager_gui.routes.studies import studies_bp
    from colony_manager_gui.routes.util import AppQuery

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(cages_bp, url_prefix='/cages')
    app.register_blueprint(animals_bp, url_prefix='/animals')
    app.register_blueprint(breeding_bp, url_prefix='/breeding')
    app.register_blueprint(histology_bp, url_prefix='/histology')
    app.register_blueprint(studies_bp, url_prefix='/studies')

    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    @app.context_processor
    def inject_global_vars():
        from colony_manager.models import Species
        species_id = int(session.get('selected_species', -1))
        if species_id != -1:
            selected_species = db.get_or_404(Species, species_id).name
        else:
            selected_species = 'All'
        return {
            'datetime': datetime,
            'species': db.session.query(Species).all(),
            'selected_species': selected_species,
        }

    @app.context_processor
    def datetime_processor():
        return dict(datetime=datetime)

    @app.before_request
    def check_login():
        from flask_login import current_user
        from flask import request, redirect, url_for
        if current_user.is_authenticated:
            return
        if request.endpoint in ('auth.login_user', 'auth.add_user'):
            return
        return redirect(url_for('auth.login_user', next=request.url))

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        models.Base.session.remove()

    with app.app_context():
        from flask_sqlalchemy.query import Query
        from sqlalchemy.orm import scoped_session, sessionmaker
        models.Base.session = scoped_session(sessionmaker())
        models.Base.session.configure(bind=db.engine)
        models.Base.query = models.Base.session.query_property(query_cls=Query)

    return app
