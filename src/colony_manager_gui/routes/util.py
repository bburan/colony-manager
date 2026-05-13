from flask import flash, render_template, request, redirect, url_for
from markupsafe import Markup, escape

from werkzeug.exceptions import NotFound
from sqlalchemy.orm import Query


def is_htmx():
    return bool(request.headers.get('HX-Request'))


def render_error_alert(message=None, form=None, alert_class='py-2 small', oob_id=None):
    """Render the standard HTMX error alert partial."""
    return render_template(
        'partials/error_alert.html',
        message=message, form=form,
        alert_class=alert_class, oob_id=oob_id,
    )


def render_modal(form, *, label, submit_url, item=None,
                 partial='partials/form_modal.html', **extra):
    """Render a standard form-modal partial.

    Every modal-render route in the app follows the same shape: load
    object, build a form, then call ``render_template('partials/form_modal.html',
    form=..., item=..., label=..., submit_url=...)``. This consolidates the
    call. Pass ``partial`` to override the template (e.g. ``form_event_modal.html``)
    and any additional kwargs in ``extra`` flow through unchanged
    (``hx_target``, ``hx_swap``, ``target_requires_side``, etc).
    """
    return render_template(
        partial, form=form, item=item, label=label, submit_url=submit_url,
        **extra,
    )


def htmx_or_redirect(*, partial=None, context=None, body=None,
                     trigger=None, oob_clear_id=None,
                     flash_message=None, flash_category='success',
                     redirect_to=None):
    """Success branch for an HTMX-aware mutation.

    HTMX → return the rendered partial (or pre-rendered ``body``), optionally
    with an OOB swap that clears an error region (``oob_clear_id``) and/or an
    ``HX-Trigger`` event header.

    Non-HTMX → flash ``flash_message`` (if given) and redirect to
    ``redirect_to`` or ``request.referrer``.
    """
    if is_htmx():
        if body is None:
            body = render_template(partial, **(context or {})) if partial else ''
        if oob_clear_id:
            body = body + f'<div id="{oob_clear_id}" hx-swap-oob="true"></div>'
        headers = {'HX-Trigger': trigger} if trigger else {}
        return body, 200, headers
    if flash_message:
        flash(flash_message, flash_category)
    target = redirect_to or request.referrer
    return redirect(target or url_for('main.view_dashboard'))


def htmx_error(message=None, *, form=None, retarget=None, oob_id=None,
               alert_class='small py-1', flash_title=None,
               redirect_to=None, status=400):
    """Failure branch for an HTMX-aware mutation.

    HTMX → render an error alert (retargeted via ``HX-Retarget`` or marked OOB
    via ``oob_id``) with ``status`` (base.html forces swap on >=400).

    Non-HTMX → flash form errors (when ``form`` has them) or ``message``, then
    redirect to ``redirect_to`` or ``request.referrer``.
    """
    if is_htmx():
        headers = {}
        if retarget:
            headers['HX-Retarget'] = retarget
        body = render_error_alert(message=message, form=form,
                                  alert_class=alert_class, oob_id=oob_id)
        return body, status, headers
    if form is not None and form.errors:
        flash_form_errors(form, title=flash_title or message or 'Please correct the errors')
    elif message:
        flash(message, 'danger')
    target = redirect_to or request.referrer
    return redirect(target or url_for('main.view_dashboard'))


class AppQuery(Query):
    def get_or_404(self, ident, description=None):
        rv = self.get(ident)
        if rv is None:
            # Raising Werkzeug's native 404 exception
            raise NotFound(description=description or f"Record {ident} not found")
        return rv


def flash_form_errors(form, title="Please correct the following errors:"):
    """
    Extracts errors from a WTForm and flashes them as a single,
    formatted HTML message.
    """
    if not form.errors:
        return

    # Start the message with the title and an unordered list. Field labels and
    # error messages can echo user input (e.g. "Cage ID 'X' already exists"),
    # so escape every interpolated value before marking the result as safe.
    html_parts = [f"<strong>{escape(title)}</strong><ul class='mb-0'>"]

    for field_name, error_messages in form.errors.items():
        field_obj = getattr(form, field_name, None)
        label = field_obj.label.text if field_obj else field_name.replace('_', ' ').title()

        for error in error_messages:
            html_parts.append(
                f"<li><strong>{escape(label)}:</strong> {escape(error)}</li>"
            )

    html_parts.append("</ul>")

    combined_message = Markup("".join(html_parts))

    # Flash using the 'danger' category (standard Bootstrap red alert)
    flash(combined_message, 'danger')
