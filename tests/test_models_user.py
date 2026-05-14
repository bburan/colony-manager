"""Tests for ``User`` model utility methods.

Pure Python paths (password hashing, identity, display name, admin
flag); no DB beyond persisting one row to confirm the column types
accept what ``set_password`` produces.
"""
from colony_manager.models import User, UserRole

from .factories import make_user


def test_set_password_then_check_password_roundtrip(db_session):
    user = make_user(db_session, password='correct horse battery staple')
    assert user.check_password('correct horse battery staple') is True
    assert user.check_password('wrong-guess') is False


def test_set_password_stores_hash_not_plaintext(db_session):
    user = make_user(db_session, password='plaintext-here')
    assert user.password_hash != 'plaintext-here'
    assert 'plaintext-here' not in user.password_hash


def test_check_password_uses_constant_time_comparison(db_session):
    """Different stored hashes for the same plaintext still verify.

    Werkzeug's ``generate_password_hash`` salts each call, so two
    users with the same password have different hashes — both must
    verify against the original plaintext.
    """
    a = make_user(db_session, email='a@example.com', password='same')
    b = make_user(db_session, email='b@example.com', password='same')
    assert a.password_hash != b.password_hash
    assert a.check_password('same') is True
    assert b.check_password('same') is True


def test_is_admin_default_false(db_session):
    user = make_user(db_session)
    assert user.is_admin() is False


def test_is_admin_true_when_admin_flag_set(db_session):
    user = make_user(db_session, admin=True)
    assert user.is_admin() is True


def test_is_active_mirrors_active_column(db_session):
    active_user = make_user(db_session, active=True)
    inactive_user = make_user(
        db_session, email='inactive@example.com', active=False,
    )
    assert active_user.is_active is True
    assert inactive_user.is_active is False


def test_display_name_joins_first_and_last(db_session):
    user = make_user(db_session, first_name='Ada', last_name='Lovelace')
    assert user.display_name == 'Ada Lovelace'


def test_get_id_returns_string(db_session):
    """Flask-Login requires ``get_id`` to return a str, not an int."""
    user = make_user(db_session)
    assert user.get_id() == str(user.id)
    assert isinstance(user.get_id(), str)


def test_user_equality_by_id(db_session):
    user = make_user(db_session)
    same = db_session.get(User, user.id)
    assert user == same
    assert user != 'not-a-user'  # NotImplemented branch
    other = make_user(db_session, email='other@example.com')
    assert user != other


def test_user_roles_relationship(db_session):
    """``roles`` is a many-to-many via ``user_roles``."""
    role_a = UserRole(name='editor')
    role_b = UserRole(name='viewer')
    db_session.add_all([role_a, role_b])
    db_session.commit()

    user = make_user(db_session)
    user.roles = [role_a, role_b]
    db_session.commit()
    db_session.refresh(user)

    assert sorted(r.name for r in user.roles) == ['editor', 'viewer']
