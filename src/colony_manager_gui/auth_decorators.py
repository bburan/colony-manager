"""Auth-related view decorators.

The global ``check_login`` hook in :mod:`colony_manager_gui` defaults to
rejecting anonymous requests. Views that should remain reachable without
a login (the login form itself, the bootstrap-user page) opt in via
``@public``. Tagging the view function instead of maintaining a string
allowlist eliminates the typo footgun and surfaces "is this endpoint
reachable while logged out?" right next to the view.
"""
import functools


def public(view_func):
    """Mark a view function as reachable without authentication.

    The marker attribute name is namespaced (``_colony_public``) so it
    won't collide with anything Flask, Flask-Login, or werkzeug attaches
    to view functions.
    """
    view_func._colony_public = True

    @functools.wraps(view_func)
    def wrapper(*args, **kwargs):
        return view_func(*args, **kwargs)

    wrapper._colony_public = True
    return wrapper
