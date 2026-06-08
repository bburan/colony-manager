from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Optional, ValidationError
from wtforms.widgets import CheckboxInput, ListWidget
from wtforms_sqlalchemy.fields import QuerySelectField, QuerySelectMultipleField

from colony_manager.models import Study

from .. import db
from .common import active_animal_factory, study_factory


class StudyForm(FlaskForm):
    name = StringField('Study Name', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[Optional()])

    def __init__(self, *args, obj=None, **kwargs):
        super().__init__(*args, obj=obj, **kwargs)
        self.initial_name = obj.name if obj is not None else None

    def validate_name(self, field):
        if self.initial_name != field.data:
            if db.session.scalars(
                select(Study).where(Study.name == field.data)
            ).first():
                raise ValidationError(f'Study "{field.data}" already exists.')


class AddToStudyForm(FlaskForm):
    animals = QuerySelectMultipleField(
        'Select Animals',
        query_factory=active_animal_factory,
        get_label='custom_id',
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInput(),
    )
