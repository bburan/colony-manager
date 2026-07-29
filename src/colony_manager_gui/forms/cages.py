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


class CageDetailsForm(FlaskForm):
    """Edits the cage's own stored fields (ID, species).

    Sex and source, also shown on the cage detail page, aren't columns
    on ``Cage`` — they're aggregated from the cage's animals — so
    there's nothing here to edit for them.
    """
    custom_id = StringField(
        'Cage ID (e.g., G001)',
        validators=[DataRequired(), Length(min=4, max=10)],
    )
    species = QuerySelectField(
        'Species', query_factory=species_factory, get_label='name',
        allow_blank=False, validators=[DataRequired()],
    )

    def __init__(self, *args, obj=None, **kwargs):
        super().__init__(*args, obj=obj, **kwargs)
        self.initial_custom_id = obj.custom_id if obj is not None else None

    def validate_custom_id(self, field):
        if self.initial_custom_id != field.data:
            if db.session.scalars(
                select(Cage).where(Cage.custom_id == field.data)
            ).first():
                raise ValidationError(f'Cage ID "{field.data}" already exists.')


class SingleHousingForm(FlaskForm):
    cage_id = StringField(
        'New Cage ID',
        validators=[DataRequired(), Length(min=4, max=10)],
    )

    def validate_cage_id(self, field):
        if db.session.scalars(
            select(Cage).where(Cage.custom_id == field.data)
        ).first():
            raise ValidationError(f'Cage ID "{field.data}" already exists.')
