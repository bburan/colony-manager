import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_migrate import Migrate

# --- Naming Convention for Constraints ---
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-very-secret-key-that-is-long-and-secure')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///colony.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)

    # Register Blueprints
    from app.routes.main import main_bp
    from app.routes.cages import cages_bp
    from app.routes.animals import animals_bp
    from app.routes.breeding import breeding_bp
    from app.routes.histology import histology_bp
    from app.routes.studies import studies_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(cages_bp, url_prefix='/cages')
    app.register_blueprint(animals_bp, url_prefix='/animals')
    app.register_blueprint(breeding_bp, url_prefix='/breeding')
    app.register_blueprint(histology_bp, url_prefix='/histology')
    app.register_blueprint(studies_bp, url_prefix='/studies')

    return app