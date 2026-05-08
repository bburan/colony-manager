"""Regression tests for the @public decorator + check_login refactor in PR7.

The old check_login hardcoded a string allowlist (``auth.login_user``,
``auth.add_user``); a typo or a renamed endpoint would silently
gate-fail. PR7 replaced that with a ``@public`` view decorator the
before-request hook can introspect.
"""


def test_public_marks_view_function():
    from colony_manager_gui.auth_decorators import public

    @public
    def my_view():
        return 'ok'

    assert getattr(my_view, '_colony_public', False) is True


def test_public_preserves_metadata():
    from colony_manager_gui.auth_decorators import public

    @public
    def some_view():
        """Docstring."""
        return 'x'

    assert some_view.__name__ == 'some_view'
    assert some_view.__doc__ == 'Docstring.'


def test_login_and_add_user_are_marked_public():
    """The two endpoints check_login used to allowlist by string."""
    from colony_manager_gui.routes import auth

    assert getattr(auth.login_user, '_colony_public', False) is True
    assert getattr(auth.add_user, '_colony_public', False) is True


def test_admin_routes_are_not_public():
    """Sanity check: admin endpoints must NOT be flagged public."""
    from colony_manager_gui.routes import auth

    assert getattr(auth.list_users, '_colony_public', False) is False
    assert getattr(auth.update_user_admin, '_colony_public', False) is False
