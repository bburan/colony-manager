import os

from markupsafe import Markup
from flask import Flask, render_template, request, redirect, url_for, flash, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, func
from flask_migrate import Migrate
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, DateField, SelectField, SelectMultipleField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional, ValidationError, Length
from wtforms.widgets import ListWidget, CheckboxInput
from wtforms_sqlalchemy.fields import QuerySelectField, QuerySelectMultipleField
from datetime import date, timedelta

# --- Association Tables ---
study_animals = db.Table('study_animals',
    db.Column('study_id', db.Integer, db.ForeignKey('study.id'), primary_key=True),
    db.Column('animal_id', db.Integer, db.ForeignKey('animal.id'), primary_key=True)
)

# --- Models ---
class TimestampModel(db.Model):
    """Base model that automatically adds created and updated timestamps."""
    __abstract__ = True  # Prevents SQLAlchemy from creating a 'timestamp_model' table
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), default=func.now(), onupdate=func.now())

class Species(TimestampModel):
    # Species available
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    animals = db.relationship('Animal', backref='species', lazy=True)
    cages = db.relationship('Cage', backref='species', lazy=True)

class Source(TimestampModel):
    # Source for a particular animal
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    animals = db.relationship('Animal', backref='source', lazy=True)

class AnimalProcedure(TimestampModel):
    # Any sort of procedure that might be performed on an animal in a systemic fashion (e.g., noise-exposure, injection, etc.).
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    events = db.relationship('AnimalEvent', backref='procedure', lazy=True)

class AnimalProcedureTarget(TimestampModel):
    # Any sort of target for a procedure (e.g., right ear, left ear, animal, etc.)
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    events = db.relationship('AnimalEvent', backref='procedure_target', lazy=True)

class TerminationReason(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    animals = db.relationship('Animal', backref='termination_reason', lazy=True)

class Cage(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(50), unique=True, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    species_id = db.Column(db.Integer, db.ForeignKey('species.id'), nullable=False)
    animals = db.relationship('Animal', backref='cage', lazy='dynamic', cascade="all, delete-orphan")

    @property
    def sources(self):
        return sorted({a.source for a in self.animals})

    @property
    def is_active(self):
        return self.animals.filter_by(termination_date=None).count() > 0

    @property
    def sex(self):
        return sorted(set(a.sex for a in self.animals))

    @property
    def sex_symbol(self):
        result = sorted(set(a.sex_symbol for a in self.animals))
        if len(result) == 2:
            return '⚥'
        elif len(result) == 1:
            return result[0]
        else:
            return ''

    def age_display(self, unit='day'):
        ages = sorted(set(getattr(a, f'age_in_{unit}s') for a in self.animals))
        if len(ages) == 0:
            return 'N/A'
        elif len(ages) == 1:
            return f'{ages[0]:.1f} {unit}s'
        else:
            return f'{ages[0]:.1f} to {ages[-1]:.1f} {unit}s'

    @property
    def source_display(self):
        sources = set(a.source_display for a in self.animals)
        if len(sources) == 0:
            return 'N/A'
        return ', '.join(sorted(sources))

class Animal(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(100), unique=True, nullable=True)
    cage_id = db.Column(db.Integer, db.ForeignKey('cage.id'), nullable=False)
    species_id = db.Column(db.Integer, db.ForeignKey('species.id'), nullable=False)
    sex = db.Column(db.String(10), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey('source.id'), nullable=True)
    breeding_pair_id = db.Column(db.Integer, db.ForeignKey('breeding_pair.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    termination_date = db.Column(db.Date, nullable=True)
    termination_reason_id = db.Column(db.Integer, db.ForeignKey('termination_reason.id'), nullable=True)
    events = db.relationship('AnimalEvent', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    ears = db.relationship('Ear', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    breeding_pair = db.relationship('BreedingPair', back_populates='offspring', foreign_keys=[breeding_pair_id])

    @property
    def events_by_date(self):
        groups = {}
        for e in self.events:
            groups.setdefault(e.date, []).append(e)
        dates = sorted(groups.keys())
        # Relies on ordering guarantee of dictionaries and ensures sorted by date.
        return dict((d, sorted(groups[d], key=lambda x: x.procedure.name)) for d in sorted(groups.keys()))

    @property
    def has_events(self):
        return self.events.count() > 0

    @property
    def event_due(self):
        return any(e.scheduled_date == date.today() and e.completion_date is None for e in self.events)

    @property
    def event_overdue(self):
        # Returns True if there are any incomplete events scheduled before today
        if self.events.count() > 0:
            print(self.events[0].completion_date)
        return any(e.scheduled_date < date.today() and e.completion_date is None for e in self.events)

    @property
    def last_event_date(self):
        last_event = self.events.filter_by(status='completed').order_by(AnimalEvent.completion_date.desc()).first()
        return last_event.completion_date if last_event else date.min

    @property
    def age_in_days(self):
        return (date.today() - self.dob).days

    @property
    def age_in_weeks(self):
        return self.age_in_days / 7

    @property
    def age_in_months(self):
        return self.age_in_days / 30

    @property
    def is_active(self):
        return self.termination_date is None

    @property
    def sex_symbol(self):
        return '♀' if self.sex == 'female' else '♂'

    @property
    def source_display(self):
        return 'N/A' if self.source is None else self.source.name

    @property
    def scheduled_events(self):
        scheduled = [e for e in self.events if e.completion_date is None]
        return sorted(scheduled, key=lambda x: x.scheduled_date)

    @property
    def completed_events(self):
        # Sorts by completion date
        completed = [e for e in self.events if e.completion_date is not None]
        return sorted(completed, key=lambda x: x.completion_date)

    def age_display(self, unit='day'):
        age = getattr(self, f'age_in_{unit}s')
        return f'{age:.1f} {unit}s'

class BreedingPair(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(50), unique=True, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    male_animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    male = db.relationship('Animal', foreign_keys=[male_animal_id])
    female_animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    female = db.relationship('Animal', foreign_keys=[female_animal_id])
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    litters = db.relationship('Litter', backref='breeding_pair', lazy='dynamic', cascade="all, delete-orphan")
    offspring = db.relationship(
        'Animal',
        back_populates='breeding_pair',
        foreign_keys='Animal.breeding_pair_id'
    )

class Litter(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    breeding_pair_id = db.Column(db.Integer, db.ForeignKey('breeding_pair.id'), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    pup_count = db.Column(db.Integer, nullable=False)
    wean_date = db.Column(db.Date, nullable=True)

    @property
    def age_in_days(self):
        return (date.today() - self.dob).days


class AnimalEvent(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    procedure_id = db.Column(db.Integer, db.ForeignKey('animal_procedure.id'), nullable=False)
    procedure_target_id = db.Column(db.Integer, db.ForeignKey('animal_procedure_target.id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    completion_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    @property
    def status(self):
        if self.completion_date is not None:
            return 'complete'
        if self.scheduled_date < date.today():
            return 'overdue'
        if self.scheduled_date == date.today():
            return 'due'
        return ''

    @property
    def date(self):
        if self.completion_date is None:
            return self.scheduled_date
        return self.completion_date

class ImmunolabelingPanel(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    reagents = db.relationship('Reagent', backref='panel', lazy='dynamic', cascade="all, delete-orphan")
    ears = db.relationship('Ear', backref='panel', lazy=True)

class Reagent(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    panel_id = db.Column(db.Integer, db.ForeignKey('immunolabeling_panel.id'), nullable=False)

class Ear(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    side = db.Column(db.String(5), nullable=False)
    cryoprotection_date = db.Column(db.Date, nullable=True)
    dissection_date = db.Column(db.Date, nullable=True)
    immunolabel_date = db.Column(db.Date, nullable=True)
    panel_id = db.Column(db.Integer, db.ForeignKey('immunolabeling_panel.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    confocal_images = db.relationship('ConfocalImage', backref='ear', lazy=True)

    @property
    def full_display(self):
        return f'{self.animal.custom_id} {self.side}'

    def __eq__(self, other):
        if not isinstance(other, Ear):
            return NotImplemented
        return self.id == other.id

    def __lt__(self, other):
        if not isinstance(other, Ear):
            return NotImplemented
        return (self.animal.custom_id, self.side) < (other.animal.custom_id, other.side)

class ConfocalImageType(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    confocal_images = db.relationship('ConfocalImage', backref='image_type', lazy=True)

class ConfocalImage(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    ear_id = db.Column(db.Integer, db.ForeignKey('ear.id'), nullable=False)
    frequency = db.Column(db.Integer, nullable=False)
    image_type_id = db.Column(db.Integer, db.ForeignKey('confocal_image_type.id'), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(150), nullable=True)

    @property
    def full_display(self):
        return f'{self.ear.full_display} {self.image_type.name} {self.frequency}'

class Study(TimestampModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    animals = db.relationship('Animal', secondary=study_animals, lazy='dynamic',
                              backref=db.backref('studies', lazy='dynamic'))
                              
# --- Forms ---
def species_factory(): return Species.query.order_by('name')
def source_factory(): return Source.query.order_by('name')
def study_factory(): return Study.query.order_by('name')
def cage_factory(): return Cage.query.order_by('custom_id')
def animal_procedure_factory(): return AnimalProcedure.query.order_by('name')
def animal_procedure_target_factory(): return AnimalProcedureTarget.query.order_by('name')
def panel_factory(): return ImmunolabelingPanel.query.order_by('name')
def termination_reason_factory(): return TerminationReason.query.order_by(TerminationReason.name)
def male_animal_factory(): return Animal.query.filter(Animal.termination_date == None, Animal.sex=='male').order_by(Animal.id)
def female_animal_factory(): return Animal.query.filter(Animal.termination_date == None, Animal.sex=='female').order_by(Animal.id)
def active_animal_factory(): return Animal.query.filter_by(is_terminated=False)
def confocal_image_type_factory(): return ConfocalImageType.query.order_by('name')

class SimpleAddForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])

class SimpleAddWithDescriptionForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    description = StringField('Description', validators=[Optional()])

class NoteForm(FlaskForm):
    notes = TextAreaField('Notes', validators=[Optional()])

class CageForm(FlaskForm):
    custom_id = StringField('Cage ID (e.g., G001)', validators=[DataRequired(), Length(min=4, max=4)])
    species = QuerySelectField('Species', query_factory=species_factory, get_label='name', allow_blank=False, validators=[DataRequired()])
    source = QuerySelectField('Source', query_factory=source_factory, get_label='name', allow_blank=True)
    sex = SelectField('Sex', choices=[('male', 'male'), ('female', 'female')], validators=[DataRequired()])
    number_of_animals = IntegerField('Number of Animals', validators=[InputRequired(), NumberRange(min=0)])
    dob = DateField('Date of Birth', default=date.today, validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])

    def validate_custom_id(self, field):
        if Cage.query.filter_by(custom_id=field.data).first():
            raise ValidationError(f'Cage ID "{field.data}" already exists.')

class HistologyForm(FlaskForm):
    cryoprotection_date = DateField('Cryoprotection date', validators=[Optional()])
    dissection_date = DateField('Dissection date', validators=[Optional()])
    immunolabel_date = DateField('Immunolabel date', validators=[Optional()])
    panel = QuerySelectField('Immunolabeling Panel', query_factory=panel_factory, get_label='name', allow_blank=True, validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])

class AnimalCustomIDForm(FlaskForm):
    custom_id = StringField('Animal ID', validators=[DataRequired()])

    def __init__(self, *args, obj=None, **kwargs):
        super().__init__(*args, obj=obj, **kwargs)
        if obj is not None:
            self.initial_custom_id = obj.custom_id
        else:
            self.initial_custom_id = None

    def validate_custom_id(self, field):
        if self.initial_custom_id != field.data:
            if Animal.query.filter_by(custom_id=field.data).first():
                raise ValidationError(f'Animal ID "{field.data}" already exists.')

class AnimalForm(AnimalCustomIDForm):
    cage = QuerySelectField('Cage', query_factory=cage_factory, get_label='custom_id')
    species = QuerySelectField('Species', query_factory=species_factory, get_label='name')
    sex = SelectField('Sex', choices=[('male', 'male'), ('female', 'female')], validators=[DataRequired()])
    dob = DateField('Date of Birth', default=date.today, validators=[DataRequired()])
    source = QuerySelectField('Source', query_factory=source_factory, get_label='name', allow_blank=True)
    notes = TextAreaField('Notes', validators=[Optional()])
    termination_date = DateField('Termination date', validators=[Optional()])
    termination_reason = QuerySelectField('Termination reason', query_factory=termination_reason_factory, get_label='name', validators=[Optional()])

class AnimalEventForm(FlaskForm):
    procedure = QuerySelectField('Procedure', query_factory=animal_procedure_factory, get_label='name', allow_blank=False)
    procedure_target = QuerySelectField('Target', query_factory=animal_procedure_target_factory, get_label='name', allow_blank=False)
    scheduled_date = DateField('Scheduled Date', default=date.today, validators=[DataRequired()])
    completion_date = DateField('Completed Date', default=None, validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])

class AnimalEventDeleteForm(EventForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self:
            if field.type not in ['CSRFTokenField', 'SubmitField']:
                if field.render_kw is None:
                    field.render_kw = {}
                field.render_kw['disabled'] = True

class BreedingPairForm(FlaskForm):
    custom_id = StringField('Pair ID', validators=[DataRequired(), Length(min=1, max=50)])
    start_date = DateField('Pairing Start Date', default=date.today, validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])

    female_animal = QuerySelectField('Female', query_factory=female_animal_factory, get_label='custom_id', allow_blank=True, validators=[Optional()], blank_text='Create new animal')
    female_species = QuerySelectField('Species', query_factory=species_factory, get_label='name')
    female_dob = DateField('Date of Birth', default=date.today, validators=[DataRequired()])
    female_source = QuerySelectField('Source', query_factory=source_factory, get_label='name', allow_blank=True)
    female_notes = TextAreaField('Notes', validators=[Optional()])

    male_animal = QuerySelectField('Male', query_factory=male_animal_factory, get_label='custom_id', allow_blank=True, validators=[Optional()], blank_text='Create new animal')
    male_species = QuerySelectField('Species', query_factory=species_factory, get_label='name')
    male_dob = DateField('Date of Birth', default=date.today, validators=[DataRequired()])
    male_source = QuerySelectField('Source', query_factory=source_factory, get_label='name', allow_blank=True)
    male_notes = TextAreaField('Notes', validators=[Optional()])


    def validate_custom_id(self, field):
        if BreedingPair.query.filter_by(custom_id=field.data).first():
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

from wtforms import FieldList, Form, FormField

class WeanedCageForm(Form):
    custom_id = StringField('Cage ID', validators=[DataRequired(), Length(min=1, max=50)])
    sex = SelectField('Sex', choices=[('male', 'male'), ('female', 'female')], validators=[DataRequired()])
    count = IntegerField('Number of Pups', validators=[InputRequired(), NumberRange(min=1)])

class WeaningForm(FlaskForm):
    wean_date = DateField('Wean Date', default=date.today, validators=[DataRequired()])
    cages = FieldList(FormField(WeanedCageForm), min_entries=1)

class TerminationForm(FlaskForm):
    termination_date = DateField('Date of Termination', default=date.today, validators=[DataRequired()])
    termination_reason = QuerySelectField('Reason', query_factory=termination_reason_factory, get_label='name', allow_blank=True)
    ears_extracted = SelectField('Ears Extracted', choices=[('None', 'None'), ('Left', 'Left'), ('Right', 'Right'), ('Both', 'Both')], validators=[DataRequired()])

class StudyForm(FlaskForm):
    name = StringField('Study Name', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[Optional()])

    def __init__(self, *args, obj=None, **kwargs):
        super().__init__(*args, obj=obj, **kwargs)
        if obj is not None:
            self.initial_name = obj.name
        else:
            self.initial_name = None

    def validate_name(self, field):
        if self.initial_name != field.data:
            if Study.query.filter_by(name=field.data).first():
                raise ValidationError(f'Study "{field.data}" already exists.')


class AddToStudyForm(FlaskForm):
    animals = QuerySelectMultipleField('Select Animals', query_factory=active_animal_factory, get_label='custom_id',
                                     widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())

class QuickAddToStudyForm(FlaskForm):
    study = QuerySelectField('Study', query_factory=study_factory, get_label='name', allow_blank=False)




class ButtonGroupWidget:
    def __call__(self, field, **kwargs):
        html = ['<div class="row g-2" role="group">']
        for subfield in field:
            # We use the subfield's ID for the 'for' attribute
            btn_id = subfield.id
            selected = 'active' if subfield.checked else ''

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
    # Frequencies: Octave spaced from 0.5 to 64
    FREQUENCIES = [0.5, 0.7, 1, 1.4, 2, 2.8, 4, 5.6, 8, 11.2, 16, 22.6, 32, 45.2, 64]

    frequencies = SelectMultipleField(
        'Frequencies (kHz)',
        choices=[(str(f), str(f)) for f in FREQUENCIES],
        option_widget=CheckboxInput(),
        widget=ButtonGroupWidget(),
    )
    image_type = QuerySelectField('Image Type', query_factory=confocal_image_type_factory, get_label='name', validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])



if __name__ == '__main__':
    app.run(debug=True)