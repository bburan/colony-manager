from flask import flash
from markupsafe import Markup


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