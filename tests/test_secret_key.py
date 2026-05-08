"""Regression test for the SECRET_KEY hardening shipped in PR1.

The previous code shipped a hardcoded fallback key, so every install
booted with the same predictable session-signing key. The fix made
``SECRET_KEY`` a required env var.
"""
import pytest


def test_create_app_requires_secret_key(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from colony_manager_gui import create_app

    with pytest.raises(KeyError):
        create_app()
