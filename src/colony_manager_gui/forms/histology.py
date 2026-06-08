from flask_wtf import FlaskForm
from markupsafe import Markup
from wtforms import DateField, SelectMultipleField, TextAreaField
from wtforms.validators import DataRequired, Optional
from wtforms.widgets import CheckboxInput
from wtforms_sqlalchemy.fields import QuerySelectField, QuerySelectMultipleField

from colony_manager import models

from .. import db
from .common import confocal_image_type_factory, panel_factory


class HistologyForm(FlaskForm):
    cryoprotection_date = DateField('Cryoprotection date', validators=[Optional()])
    dissection_date = DateField('Dissection date', validators=[Optional()])
    immunolabel_date = DateField('Immunolabel date', validators=[Optional()])
    panel = QuerySelectField(
        'Immunolabeling Panel', query_factory=panel_factory,
        get_label='name', allow_blank=True, validators=[Optional()],
    )
    notes = TextAreaField('Notes', validators=[Optional()])
    tags = QuerySelectMultipleField(
        'Tags',
        query_factory=lambda: models.EarTag.get_ordered(db.session),
        get_label='display_name',
    )


class _ButtonGroupWidget:
    """Renders a SelectMultipleField as a Bootstrap checkbox button-group."""

    def __call__(self, field, **kwargs):
        html = ['<div class="row g-2" role="group">']
        for subfield in field:
            btn_id = subfield.id
            html.append(f'''
                <div class="col-2">
                <input type="checkbox" class="btn-check" name="{field.name}"
                       id="{btn_id}" value="{subfield.data}"
                       {"checked" if subfield.checked else ""}>
                <label class="btn btn-outline-primary btn-sm w-100 h-100 mb-1" for="{btn_id}">
                    {subfield.label.text}
                </label>
                </div>
            ''')
        html.append('</div>')
        return Markup(''.join(html))


class ConfocalImageForm(FlaskForm):
    FREQUENCIES = [0.5, 0.7, 1, 1.4, 2, 2.8, 4, 5.7, 8, 11.3, 16, 22.6, 32, 45.3, 64]
    frequencies = SelectMultipleField(
        'Frequencies (kHz)',
        choices=[(str(f), str(f)) for f in FREQUENCIES],
        option_widget=CheckboxInput(),
        widget=_ButtonGroupWidget(),
    )
    image_type = QuerySelectField(
        'Image Type', query_factory=confocal_image_type_factory,
        get_label='name', validators=[DataRequired()],
    )
    notes = TextAreaField('Notes', validators=[Optional()])
