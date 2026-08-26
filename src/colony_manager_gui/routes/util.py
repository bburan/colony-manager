import re

from flask import abort, flash, render_template, request, redirect, url_for
from markupsafe import Markup, escape
from sqlalchemy import func, select

from colony_manager.db import get_session


class Pagination:
    """Flask-SQLAlchemy-compatible pagination over a SQLAlchemy 2.0 ``select()``.

    Exposes the attributes the unmatched-files template reads
    (``items``, ``page``, ``pages``, ``total``, ``has_prev``, ``has_next``,
    ``prev_num``, ``next_num``, ``iter_pages``) so the swap from
    ``db.paginate`` is template-transparent.
    """

    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total

    @property
    def pages(self):
        if self.per_page == 0 or self.total == 0:
            return 0
        return (self.total + self.per_page - 1) // self.per_page

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def prev_num(self):
        return self.page - 1 if self.has_prev else None

    @property
    def next_num(self):
        return self.page + 1 if self.has_next else None

    def iter_pages(self, left_edge=2, left_current=2, right_current=4, right_edge=2):
        last = 0
        for num in range(1, self.pages + 1):
            if (num <= left_edge
                    or (self.page - left_current - 1 < num < self.page + right_current)
                    or num > self.pages - right_edge):
                if last + 1 != num:
                    yield None
                yield num
                last = num


def paginate(stmt, page=1, per_page=20):
    """Run ``stmt`` with LIMIT/OFFSET and wrap the result in a :class:`Pagination`.

    Computes ``total`` via a separate ``COUNT(*)`` against the same
    statement so callers get the full result-set size without loading
    every row.
    """
    session = get_session()
    page = max(1, page)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = session.scalars(stmt.limit(per_page).offset((page - 1) * per_page)).all()
    return Pagination(items=items, page=page, per_page=per_page, total=total)


def get_or_404(model, ident, description=None):
    """Load ``model`` by primary key or abort with 404.

    Standalone replacement for the Flask-SQLAlchemy ``db.get_or_404``
    sugar. Loads through the unified ``colony_manager.db`` scoped
    session, so routes share one session with workers and scripts.
    """
    obj = get_session().get(model, ident)
    if obj is None:
        abort(404, description=description or f'{model.__name__} {ident} not found')
    return obj


def is_htmx():
    return bool(request.headers.get('HX-Request'))


_TARGET_AGE_UNITS = {
    'd': 'day', 'day': 'day', 'days': 'day',
    'w': 'week', 'wk': 'week', 'wks': 'week', 'week': 'week', 'weeks': 'week',
    'm': 'month', 'mo': 'month', 'mon': 'month',
    'month': 'month', 'months': 'month',
}

_TARGET_AGE_RE = re.compile(r'^\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z]+)\s*$')


def parse_target_age(raw):
    """Parse a ``target_age`` filter string like ``8w`` / ``8 weeks``.

    Returns ``(value, unit, error)``. On success ``error`` is None and
    ``value``/``unit`` are the numeric age and its normalized unit
    (``day``/``week``/``month``). On failure ``value``/``unit`` are None and
    ``error`` is a human-readable message. A blank string is not an error —
    it just hides the target-date column — and returns ``(None, None, None)``.

    A bare number with no unit (e.g. ``8``) is an error: the unit is
    required so the calculation isn't silently guessed.
    """
    if raw is None or not raw.strip():
        return None, None, None
    match = _TARGET_AGE_RE.match(raw)
    if not match:
        return None, None, (
            f"Could not parse target age '{raw.strip()}'. "
            "Include a unit, e.g. '8w' or '8 weeks'."
        )
    number, unit_text = match.groups()
    unit = _TARGET_AGE_UNITS.get(unit_text.lower())
    if unit is None:
        return None, None, (
            f"Unknown age unit '{unit_text}'. Use days, weeks, or months."
        )
    value = float(number)
    if value <= 0:
        return None, None, 'Target age must be greater than zero.'
    return value, unit, None


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
                     trigger=None, oob_id=None,
                     flash_message=None, flash_category='success',
                     redirect_to=None):
    """Success branch for an HTMX-aware mutation.

    HTMX → return the rendered partial (or pre-rendered ``body``), optionally
    with an OOB swap that clears the element with id ``oob_id`` and/or an
    ``HX-Trigger`` event header.

    Non-HTMX → flash ``flash_message`` (if given) and redirect to
    ``redirect_to`` or ``request.referrer``.
    """
    if is_htmx():
        if body is None:
            body = render_template(partial, **(context or {})) if partial else ''
        if oob_id:
            body = body + render_template('partials/oob_clear.html', oob_id=oob_id)
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
