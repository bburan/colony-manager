"""Regression test for the XSS-via-flash fix shipped in PR1.

Validation errors that echo user-supplied input (e.g. ``Cage ID
"<script>" already exists``) used to be concatenated into HTML and
wrapped in ``Markup(...)``, executing in the browser. The fix routes
labels and error messages through ``markupsafe.escape`` first.
"""
from flask import get_flashed_messages
from wtforms import Form, StringField


class _SampleForm(Form):
    custom_id = StringField('User ID')


def test_flash_form_errors_escapes_user_input(request_ctx):
    from colony_manager_gui.routes.util import flash_form_errors

    form = _SampleForm()
    form.custom_id.errors = ['<script>alert(1)</script> already exists']
    form.custom_id.label.text = 'User <img src=x>'

    flash_form_errors(form, title='Error <script>x</script>')

    messages = get_flashed_messages(with_categories=True)
    assert len(messages) == 1
    category, body = messages[0]
    assert category == 'danger'

    rendered = str(body)
    # Raw script tag must not survive into the flashed HTML.
    assert '<script>' not in rendered
    assert '<img src=x>' not in rendered
    # Escaped form must be present.
    assert '&lt;script&gt;' in rendered


def test_flash_form_errors_noop_on_clean_form(request_ctx):
    from colony_manager_gui.routes.util import flash_form_errors
    form = _SampleForm()
    flash_form_errors(form)
    assert get_flashed_messages() == []
