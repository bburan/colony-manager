from flask import flash, render_template
from markupsafe import Markup

from werkzeug.exceptions import NotFound
from sqlalchemy.orm import Query


def render_error_alert(message=None, form=None, alert_class='py-2 small', oob_id=None):
    """Render the standard HTMX error alert partial."""
    return render_template(
        'partials/error_alert.html',
        message=message, form=form,
        alert_class=alert_class, oob_id=oob_id,
    )


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

    # Start the message with the title and an unordered list
    html_parts = [f"<strong>{title}</strong><ul class='mb-0'>"]

    for field_name, error_messages in form.errors.items():
        # Try to grab the human-readable label from the form field
        field_obj = getattr(form, field_name, None)
        label = field_obj.label.text if field_obj else field_name.replace('_', ' ').title()

        for error in error_messages:
            html_parts.append(f"<li><strong>{label}:</strong> {error}</li>")

    html_parts.append("</ul>")

    # Combine into a single string and mark as safe HTML
    combined_message = Markup("".join(html_parts))

    # Flash using the 'danger' category (standard Bootstrap red alert)
    flash(combined_message, 'danger')
