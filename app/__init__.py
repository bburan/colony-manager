import datetime
import os
import datetime
from flask import Flask, session
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_migrate import Migrate
from sqlalchemy_continuum import make_versioned
from sqlalchemy_continuum.plugins import FlaskPlugin

# --- Naming Convention for Constraints ---
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}


make_versioned(user_cls='User', plugins=[FlaskPlugin()])
db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))
migrate = Migrate()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-very-secret-key-that-is-long-and-secure')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Register Blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.cages import cages_bp
    from app.routes.animals import animals_bp
    from app.routes.breeding import breeding_bp
    from app.routes.histology import histology_bp
    from app.routes.studies import studies_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(cages_bp, url_prefix='/cages')
    app.register_blueprint(animals_bp, url_prefix='/animals')
    app.register_blueprint(breeding_bp, url_prefix='/breeding')
    app.register_blueprint(histology_bp, url_prefix='/histology')
    app.register_blueprint(studies_bp, url_prefix='/studies')

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(user_id)

    @app.context_processor
    def inject_global_vars():
        from app.models import Species
        species_id = int(session.get('selected_species', -1))
        if species_id != -1:
            selected_species = Species.query.get_or_404(species_id).name
        else:
            selected_species = 'All'
        return {
            'datetime': datetime,
            'species': Species.query.all(),
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

    return app
