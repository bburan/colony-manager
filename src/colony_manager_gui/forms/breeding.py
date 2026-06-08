from datetime import date

from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import (
    DateField, FieldList, Form, FormField, IntegerField, SelectField,
    StringField, TextAreaField,
)
from wtforms.validators import (
    DataRequired, InputRequired, Length, NumberRange, Optional, ValidationError,
)
from wtforms_sqlalchemy.fields import QuerySelectField

from colony_manager.models import BreedingPair

from .. import db
from .common import (
    female_animal_factory, male_animal_factory, source_factory, species_factory,
)


class BreedingPairForm(FlaskForm):
    custom_id = StringField('Pair ID', validators=[DataRequired(), Length(min=1, max=50)])
    start_date = DateField('Pairing Start Date', default=date.today, validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])

    female_animal = QuerySelectField(
        'Female', query_factory=female_animal_factory, get_label='custom_id',
        allow_blank=True, validators=[Optional()], blank_text='Create new animal',
    )
    female_species = QuerySelectField('Species', query_factory=species_factory, get_label='name')
    female_dob = DateField('Date of Birth', default=date.today, validators=[DataRequired()])
    female_source = QuerySelectField(
        'Source', query_factory=source_factory, get_label='name', allow_blank=True,
    )
    female_notes = TextAreaField('Notes', validators=[Optional()])

    male_animal = QuerySelectField(
        'Male', query_factory=male_animal_factory, get_label='custom_id',
        allow_blank=True, validators=[Optional()], blank_text='Create new animal',
    )
    male_species = QuerySelectField('Species', query_factory=species_factory, get_label='name')
    male_dob = DateField('Date of Birth', default=date.today, validators=[DataRequired()])
    male_source = QuerySelectField(
        'Source', query_factory=source_factory, get_label='name', allow_blank=True,
    )
    male_notes = TextAreaField('Notes', validators=[Optional()])

    def validate_custom_id(self, field):
        if db.session.scalars(
            select(BreedingPair).where(BreedingPair.custom_id == field.data)
        ).first():
            raise ValidationError(f'Pair ID "{field.data}" already exists.')


class LitterForm(FlaskForm):
    dob = DateField('Litter Birth Date', default=date.today, validators=[DataRequired()])
    pup_count = IntegerField('Number of Pups', validators=[InputRequired(), NumberRange(min=1)])


class LitterDeleteForm(LitterForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self:
            if field.type not in ['CSRFTokenField', 'SubmitField']:
                if field.render_kw is None:
                    field.render_kw = {}
                field.render_kw['disabled'] = True


class WeanedCageForm(Form):
    custom_id = StringField('Cage ID', validators=[DataRequired(), Length(min=1, max=50)])
    sex = SelectField(
        'Sex', choices=[('male', 'male'), ('female', 'female')],
        validators=[DataRequired()],
    )
    count = IntegerField('Number of Pups', validators=[InputRequired(), NumberRange(min=1)])


class WeaningForm(FlaskForm):
    wean_date = DateField('Wean Date', default=date.today, validators=[DataRequired()])
    cages = FieldList(FormField(WeanedCageForm), min_entries=1)
