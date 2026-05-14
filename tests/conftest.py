"""Shared pytest fixtures.

Two tiers of tests live here:

* **Unit tests** — no Postgres, no Flask app factory. Cover the
  security regressions shipped in PRs 1–7 and any other helper-level
  code (``is_safe_url``, escapes, public decorator, etc.).
* **Integration tests** — Postgres-backed, model + sync core + GUI
  routes. Use the fixtures from :mod:`tests.db_fixtures` (``db_session``,
  ``app``, ``client``) which clone a per-worker template database per
  test. See ``tests/README.md`` for setup.
"""
import pytest
from flask import Flask

# Re-export the Postgres fixtures so individual test modules don't have
# to import them explicitly. Tests that don't need a DB simply don't
# request ``db_session`` / ``app`` and pay zero startup cost. Plain
# imports (rather than ``pytest_plugins = ...``) sidestep pytest's
# deprecation warning for plugin declarations in non-rootdir conftests.
from .db_fixtures import (  # noqa: F401  (fixtures discovered by name)
    template_db,
    test_db,
    db_session,
    app,
    client,
)


@pytest.fixture
def request_ctx():
    """A Flask request context bound to a throwaway app.

    Enough to exercise helpers that touch ``flask.request`` (e.g.
    ``is_safe_url``) without running the colony_manager app factory.
    """
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test-key'
    with app.test_request_context('/', base_url='http://localhost'):
        yield app
