"""Regression tests for the open-redirect guard fixed in PR1.

``is_safe_url`` previously crashed with NameError because ``urlparse``,
``urljoin``, and ``abort`` weren't imported. PR1 added the imports and
this test pins the behavior so the guard can't silently rot again.
"""


def test_safe_url_accepts_relative_path(request_ctx):
    from colony_manager_gui.routes.auth import is_safe_url
    assert is_safe_url('/dashboard') is True


def test_safe_url_accepts_same_host_absolute(request_ctx):
    from colony_manager_gui.routes.auth import is_safe_url
    assert is_safe_url('http://localhost/dashboard') is True


def test_safe_url_rejects_cross_origin_http(request_ctx):
    from colony_manager_gui.routes.auth import is_safe_url
    assert is_safe_url('http://evil.example.com/login') is False


def test_safe_url_rejects_cross_origin_https(request_ctx):
    from colony_manager_gui.routes.auth import is_safe_url
    assert is_safe_url('https://evil.example.com/login') is False


def test_safe_url_rejects_javascript_scheme(request_ctx):
    from colony_manager_gui.routes.auth import is_safe_url
    # The scheme isn't in {'http', 'https'}, so the guard rejects.
    assert is_safe_url('javascript:alert(1)') is False
