"""Standalone SQLAlchemy session for non-Flask consumers.

Importing this module gives analysis scripts and notebooks a
``scoped_session`` bound to ``DATABASE_URL`` without standing up a
Flask app. Use it like::

    from colony_manager.db import Session
    from colony_manager.models import Animal
    from sqlalchemy import select

    session = Session()
    animals = session.scalars(select(Animal)).all()

The engine and session are built lazily on first access so tests can
rebind ``DATABASE_URL`` (via ``monkeypatch.setenv``) before the
bindings freeze.
"""
import os

from colony_manager import models  # noqa: F401  (imported for side effects)

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker


_engine = None
_Session = None


def _ensure_bound():
    """Build the engine + scoped session on first use.

    Idempotent — subsequent calls are no-ops. ``DATABASE_URL`` is read
    here (not at import) so test fixtures can set it after importing
    the package.
    """
    global _engine, _Session
    if _engine is not None:
        return
    # ``pool_pre_ping`` validates a connection before handing it out.
    # Important for the RQ worker: after ``fork()`` the child inherits
    # the parent's pool, and the parent's TCP connections are no longer
    # safe in the child. pre_ping detects + recycles those silently.
    _engine = create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)
    _Session = scoped_session(sessionmaker(bind=_engine))


def get_engine():
    _ensure_bound()
    return _engine


def get_session():
    _ensure_bound()
    return _Session


def reset_bindings():
    """Drop the cached engine/session so the next access re-reads env.

    Test-only — production callers never need this. Disposes the
    existing engine's pool to avoid leaking connections.
    """
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def __getattr__(name):
    """Lazy module-level attributes (PEP 562).

    Lets ``from colony_manager.db import engine, Session`` work without
    forcing an eager bind at import time when ``DATABASE_URL`` isn't
    set (tests).
    """
    if name == 'engine':
        _ensure_bound()
        return _engine
    if name == 'Session':
        _ensure_bound()
        return _Session
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


# Preserve eager-bind behavior for scripts that have ``DATABASE_URL`` set
# at import time. When it's unset (test runs), we stay lazy so fixtures
# can supply the URL per-test before the bind happens.
if os.environ.get('DATABASE_URL'):
    _ensure_bound()
