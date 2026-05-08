"""Shared pytest fixtures.

The tests in this directory cover the security regressions shipped in
PRs 1–7. They're deliberately unit-style: no Postgres, no Flask app
factory, no real DB. The wider integration suite (CSRF on the raw-form
endpoints, admin-only routes returning 403, etc.) needs a real Postgres
because of ``pg_advisory_xact_lock`` in the bootstrap-user flow and is
tracked as a follow-up.
"""
import pytest
from flask import Flask


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
