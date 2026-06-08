from datetime import date

from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import DateField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import (
    DataRequired, InputRequired, Length, NumberRange, Optional, ValidationError,
)
from wtforms_sqlalchemy.fields import QuerySelectField

from colony_manager.models import Cage

from .. import db
from .common import source_factory, species_factory


class CageForm(FlaskForm):
    custom_id = StringField(
        'Cage ID (e.g., G001)',
        validators=[DataRequired(), Length(min=4, max=10)],
    )
    species = QuerySelectField(
        'Species', query_factory=species_factory, get_label='name',
        allow_blank=False, validators=[DataRequired()],
    )
    source = QuerySelectField(
        'Source', query_factory=source_factory, get_label='name', allow_blank=True,
    )
    sex = SelectField(
        'Sex', choices=[('male', 'male'), ('female', 'female')],
        validators=[DataRequired()],
    )
    number_of_animals = IntegerField(
        'Number of Animals', validators=[InputRequired(), NumberRange(min=0)],
    )
    dob = DateField('Date of Birth', default=date.today, validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])

    def validate_custom_id(self, field):
        if db.session.scalars(
            select(Cage).where(Cage.custom_id == field.data)
        ).first():
            raise ValidationError(f'Cage ID "{field.data}" already exists.')
