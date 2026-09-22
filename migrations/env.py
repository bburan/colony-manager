import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.engine import make_url

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# disable_existing_loggers=False: the default (True) silently disables
# every logger that already exists and isn't named in alembic.ini --
# including the app's own colony_manager_gui.* loggers whenever a
# migration runs in a process that has already imported them, which is
# how 'flask data ... -v' ends up printing nothing.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

from colony_manager import models

target_metadata = models.Base.metadata

def get_url():
    return os.environ['DATABASE_URL']


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section)
    configuration['sqlalchemy.url'] = get_url()
    # Which database is about to be migrated is worth saying out loud --
    # pointing this at the wrong one is the expensive mistake. The password
    # is not: this runs in terminals, CI logs and agent transcripts alike.
    print(make_url(configuration['sqlalchemy.url']).render_as_string(
        hide_password=True
    ))

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
