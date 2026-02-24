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

# --- App Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-very-secret-key-that-is-long-and-secure')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///colony.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- Naming Convention for Constraints ---
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# --- Database Setup ---
db = SQLAlchemy(app, metadata=MetaData(naming_convention=naming_convention))
migrate = Migrate(app, db, render_as_batch=True)

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

class EventForm(FlaskForm):
    procedure = QuerySelectField('Procedure', query_factory=animal_procedure_factory, get_label='name', allow_blank=False)
    procedure_target = QuerySelectField('Target', query_factory=animal_procedure_target_factory, get_label='name', allow_blank=False)
    scheduled_date = DateField('Scheduled Date', default=date.today, validators=[DataRequired()])
    completion_date = DateField('Completed Date', default=None, validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])

class EventDeleteForm(EventForm):

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

@app.route('/')
def index():
    today = date.today()

    # 1. Metrics for Top Cards
    active_cages_count = Cage.query.filter(Cage.animals.any()).count()
    active_animals_count = Animal.query.filter(Animal.termination_date == None).count()
    active_breeding_pairs_count = BreedingPair.query.filter_by(is_active=True).count()
    ears_for_processing_count = Ear.query.filter(Ear.immunolabel_date == None).count()

    # 2. Upcoming Events Table (Next 7 days + Overdue)
    upcoming_events = AnimalEvent.query.filter(
        AnimalEvent.completion_date == None,
        AnimalEvent.scheduled_date <= today + timedelta(days=7)
    ).order_by(AnimalEvent.scheduled_date.asc()).all()

    # Animals terminated in the last 30 days
    recent_terminations = Animal.query.filter(
        Animal.termination_date >= (date.today() - timedelta(days=30))
    )

    upcoming_litters = Litter.query.filter(Litter.wean_date == None).order_by(Litter.dob).all()

    active_males = db.session.query(BreedingPair.male_animal_id).filter_by(is_active=True)
    active_females = db.session.query(BreedingPair.female_animal_id).filter_by(is_active=True)
    active_parent_ids = active_males.union(active_females)
    unassigned_animals = Animal.query.filter(
        Animal.termination_date == None,
        ~Animal.studies.any(),
        Animal.custom_id != None,
        ~Animal.id.in_(active_parent_ids),
    )

    available_animals_n = Animal.query.filter(Animal.custom_id == None).count()

    image_analysis_pending = ConfocalImage.query.filter_by(status='pending')
    image_analysis_review = ConfocalImage.query.filter_by(status='need_review')

    return render_template(
        'index.html',
        # Card Metrics
        active_cages=active_cages_count,
        active_animals=active_animals_count,
        active_pairs=active_breeding_pairs_count,
        ears_to_process=ears_for_processing_count,

        # Schedule & Alerts
        upcoming_events=upcoming_events,

        # Additional information
        recent_terminations=recent_terminations,
        upcoming_litters=upcoming_litters,
        unassigned_animals=unassigned_animals,
        available_animals_n=available_animals_n,
        image_analysis_pending=image_analysis_pending,
        image_analysis_review=image_analysis_review,
        today=today,
   )
    
@app.route('/calendar')
def calendar():
    events = AnimalEvent.query.all()
    calendar_events = []
    for event in events:
        calendar_events.append({
            'title': f"{event.animal.custom_id}: {event.procedure.name}",
            'start': event.completion_date.isoformat() if event.completion_date is not None else event.scheduled_date.isoformat(),
            'url': url_for('view_animals'),
            'backgroundColor': '#198754' if event.completion_date is not None else '#0d6efd',
        })
    return render_template('calendar.html', calendar_events=calendar_events)

# --- Cage Routes ---
@app.route('/cages')
def view_cages():
    age_unit = request.args.get('age_unit', 'day')
    status_filter = request.args.get('status_filter', 'active')
    sort_by = request.args.get('sort_by', 'custom_id')

    if sort_by == 'custom_id':
        cages = Cage.query.order_by(Cage.custom_id).all()
    elif sort_by == 'age':
        cages = Cage.query \
            .outerjoin(Cage.animals) \
            .group_by(Cage.id) \
            .order_by(func.min(Animal.dob).desc()) \
            .all()

    if status_filter == 'active':
        cages = [c for c in cages if c.is_active]
    elif status_filter == 'inactive':
        cages = [c for c in cages if not c.is_active]

    return render_template(
        'cages.html',
        cages=cages,
        filters={
            'age_unit': age_unit,
            'status_filter': status_filter,
            'sort_by': sort_by,
        },
    )

@app.route('/cage/rename/<int:cage_id>', methods=['GET', 'POST'])
def rename_cage(cage_id):
    pass

@app.route('/cage/delete/<int:cage_id>', methods=['GET', 'POST'])
def delete_cage(cage_id):
    pass

@app.route('/cage/<int:cage_id>', methods=['GET', 'POST'])
def cage_detail(cage_id):
    cage = Cage.query.get_or_404(cage_id)
    form = NoteForm()
    if form.validate_on_submit():
        cage.notes = form.notes.data
        db.session.commit()
        flash('Cage notes updated successfully.', 'success')
        return redirect(url_for('cage_detail', cage_id=cage.id))
    animals = cage.animals.order_by('custom_id').all()
    return render_template(
        'cage_detail.html', cage=cage, form=form,
                           animals=animals, termination_form=TerminationForm(),
                           quick_add_form=QuickAddToStudyForm(),
                           note_form=NoteForm())


@app.route('/cage/note/<int:cage_id>', methods=['POST'])
def update_cage_note(cage_id):
    cage = Cage.query.get_or_404(cage_id)
    form = NoteForm()
    if form.validate_on_submit():
        form.populate_obj(cage)
        db.session.commit()
        flash(f'Notes for cage {cage.custom_id} updated.', 'success')
    return redirect(request.referrer or url_for('view_cages'))

@app.route('/cages/new', methods=['POST'])
def add_cage():
    form = CageForm()
    if form.validate_on_submit():
        cage = Cage(
            custom_id=form.custom_id.data,
            notes=form.notes.data,
            species_id=form.species.data.id,
        )
        for i in range(form.number_of_animals.data):
            animal = Animal(
                cage=cage,
                sex=form.sex.data,
                dob=form.dob.data,
                species=form.species.data,
                source=form.source.data,
            )
            db.session.add(animal)
        db.session.add(cage)
        db.session.commit()
        flash(f'Cage {cage.custom_id} with {form.number_of_animals.data} animals created.', 'success')
        return redirect(url_for('view_cages'))
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", 'danger')
    return render_template(request.referrer or url_for('view_cages'))

# --- Animal Routes ---
@app.route('/animals')
def view_animals():
    sort_by = request.args.get('sort_by', 'id')
    event_filter = request.args.get('event_filter', 'all')
    status_filter = request.args.get('status_filter', 'active')
    study_filter = request.args.get('study_filter', 'all')
    age_unit = request.args.get('age_unit', 'day')
    search_query = request.args.get('search_query', '')

    query = Animal.query.filter(Animal.custom_id.is_not(None))

    if search_query:
        # We join Events and Procedures to allow searching by procedure name
        # .ilike(f'%{search_query}%') handles the "partial match" requirement
        query = query.join(Animal.events, isouter=True).join(AnimalEvent.procedure, isouter=True).filter(
            db.or_(
                Animal.custom_id.ilike(f'%{search_query}%'),
                AnimalProcedure.name.ilike(f'%{search_query}%')
            )
        )

    if status_filter == 'active':
        query = query.filter(Animal.termination_date.is_(None))
    elif status_filter == 'terminated':
        query = query.filter(Animal.termination_date.is_not(None))
    if study_filter != 'all':
        query = query.join(Animal.studies).filter(Study.id == int(study_filter))

    animals = query.all()
    if sort_by == 'age':
        animals.sort(key=lambda a: a.age_in_days)
    elif sort_by == 'event_date':
        animals.sort(key=lambda a: a.last_event_date, reverse=True)
    else:
        animals.sort(key=lambda a: a.custom_id)

    if event_filter == 'all':
        pass
    elif event_filter == 'has_events':
        animals = [a for a in animals if a.has_events]
    elif event_filter == 'no_events':
        animals = [a for a in animals if not a.has_events]
    elif event_filter == 'due_overdue':
        animals = [a for a in animals if (a.event_due or a.event_overdue)]
    elif event_filter == 'overdue':
        animals = [a for a in animals if a.event_overdue]

    return render_template(
        'animals.html',
        animals=animals,
        quick_add_form=QuickAddToStudyForm(),
        filters={
            'sort_by': sort_by,
            'status_filter': status_filter,
            'event_filter': event_filter,
            'study_filter': study_filter,
            'age_unit': age_unit,
            'search_query': search_query,
        },
    )

@app.route('/animal/update/<int:animal_id>', methods=['POST'])
def update_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = AnimalForm(obj=animal)
    if form.validate_on_submit():
        form.populate_obj(animal)
        db.session.commit()
        flash(f'Successfully updated {animal.custom_id}', 'success')
    else:
        flash(f'Error updating {animal.custom_id}', 'danger')
        for error in form.errors:
            flash(error, 'danger')
    return redirect(request.referrer or url_for('animal_detail', animal_id=animal_id))


@app.route('/animal/create', methods=['POST'])
def create_animal():
    form = AnimalForm()
    if form.validate_on_submit():
        form.populate_obj(animal)
        db.session.commit()
        flash(f'Successfully created {animal.custom_id}', 'success')
    else:
        flash(f'Error creating {animal.custom_id}', 'danger')
        for error in form.errors:
            flash(error, 'danger')
    return redirect(request.referrer or url_for('animal_detail', animal_id=animal_id))


@app.route('/animal/detail/<int:animal_id>')
def animal_detail(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    return render_template(
        'animal_detail.html',
        animal=animal,
    )

@app.route('/animal/delete/<int:animal_id>', methods=['POST'])
def delete_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    if animal.breeding_pair_male or animal.breeding_pair_female:
        flash(f'Cannot delete animal {animal.custom_id} because it is part of a breeding pair.', 'danger')
        return redirect(request.referrer or url_for('view_animals'))
        
    db.session.delete(animal)
    db.session.commit()
    flash(f'Animal {animal.custom_id} has been deleted.', 'success')
    return redirect(request.referrer or url_for('view_animals'))

@app.route('/animal/activate/<int:animal_id>', methods=['POST'])
def activate_animal(animal_id):
    animal = db.session.get(Animal, animal_id)
    new_id = request.form.get('custom_id', '').strip()

    if animal and new_id:
        # Optional: Check if the ID is already taken
        exists = db.session.query(Animal).filter_by(custom_id=new_id).first()
        if exists:
            flash(f"Error: ID {new_id} is already assigned to another animal.", "danger")
        else:
            animal.custom_id = new_id
            db.session.commit()
            flash(f"Animal activated with ID: {new_id}", "success")

    # Redirect back to where they were
    return redirect(request.referrer or url_for('view_animals'))

@app.route('/animals/terminate/<int:animal_id>', methods=['POST'])
def terminate_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = TerminationForm()
    if form.validate_on_submit():
        animal.termination_date = form.termination_date.data
        animal.termination_reason = form.termination_reason.data
        animal.ears_extracted = form.ears_extracted.data
        if animal.ears_extracted in ['Left', 'Both']:
            db.session.add(Ear(animal_id=animal.id, side='Left'))
        if animal.ears_extracted in ['Right', 'Both']:
            db.session.add(Ear(animal_id=animal.id, side='Right'))
        db.session.commit()
        flash(f'Animal {animal.custom_id} has been marked as terminated.', 'success')
    else:
        flash('Error in termination form. A reason might be required if you added one.', 'danger')
    return redirect(request.referrer or url_for('view_animals'))

@app.route('/animal/event/<int:event_id>', methods=['POST'])
def update_event(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    form = EventForm()
    if form.validate_on_submit():
        form.populate_obj(event)
        db.session.commit()
        flash('Event updated successfully.', 'success')
    else:
        flash('Error updating event.', 'danger')
    return redirect(request.referrer or url_for('view_animals'))

@app.route('/animal/events/create/<int:animal_id>', methods=['POST'])
def create_event(animal_id):
    form = EventForm()
    if form.validate_on_submit():
        event = AnimalEvent(animal_id=animal_id)
        form.populate_obj(event)
        db.session.add(event)
        db.session.commit()
        flash('Event updated successfully.', 'success')
    else:
        flash('Error updating event.', 'danger')
    return redirect(request.referrer or url_for('view_animals'))

@app.route('/events/delete/<int:event_id>', methods=['POST'])
def delete_event(event_id):
    event = db.session.get(AnimalEvent, event_id)
    if event:
        animal_id = event.animal_id  # Grab this to redirect back to the right page
        db.session.delete(event)
        db.session.commit()
        # Flash messages are great for feedback
        flash("Event deleted successfully.", "success")
    else:
        flash("Event not found.", "danger")
    return redirect(request.referrer or url_for('view_animal', animal_id=animal_id))

# --- Breeding Routes ---
@app.route('/breeding')
def view_breeding_pairs():
    pairs = BreedingPair.query.order_by(BreedingPair.is_active.desc(), BreedingPair.id.desc()).all()
    form = BreedingPairForm()
    litter_form = LitterForm()
    return render_template('breeding.html', pairs=pairs, form=form, litter_form=litter_form)

@app.route('/breeding/<int:pair_id>')
def breeding_pair_detail(pair_id):
    pair = BreedingPair.query.get_or_404(pair_id)
    return render_template('breeding_pair_detail.html', pair=pair)

@app.route('/breeding/new', methods=['POST'])
def add_breeding_pair():
    form = BreedingPairForm()
    if form.validate_on_submit():
        if form.male_animal.data is None:
            male_animal = Animal(
                custom_id=f'{form.custom_id.data}-M',
                species=form.male_species.data,
                dob=form.male_dob.data,
                source=form.male_source.data,
                notes=form.male_notes.data,
                sex='male',
            )
            db.session.add(male_animal)
        else:
            male_animal = form.male_animal.data
        if form.female_animal.data is None:
            female_animal = Animal(
                custom_id=f'{form.custom_id.data}-F',
                species=form.female_species.data,
                dob=form.female_dob.data,
                source=form.female_source.data,
                notes=form.female_notes.data,
                sex='female',
            )
            db.session.add(female_animal)
        else:
            female_animal = form.female_animal.data

        if female_animal.species != male_animal.species:
            flash('Species of male and female must be the same.', 'danger')
            return redirect(request.referrer or url_for('view_breeding_pairs'))

        cage = Cage(
            custom_id=form.custom_id.data,
            species=form.male_species.data,
        )
        male_animal.cage = cage
        female_animal.cage = cage
        db.session.add(cage)

        pair = BreedingPair(
            custom_id=form.custom_id.data,
            male=male_animal,
            female=female_animal,
            start_date=form.start_date.data,
        )
        db.session.add(pair)
        db.session.commit()
        flash('New breeding pair created successfully.', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", 'danger')
    return redirect(request.referrer or url_for('view_breeding_pairs'))

@app.route('/breeding/litter/new/<int:pair_id>', methods=['POST'])
def add_litter(pair_id):
    pair = BreedingPair.query.get_or_404(pair_id)
    form = LitterForm()
    if form.validate_on_submit():
        litter = Litter(breeding_pair=pair)
        form.populate_obj(litter)
        db.session.add(litter)
        db.session.commit()
        flash(f'Litter recorded for breeding pair {pair.custom_id}.', 'success')
    else:
        flash('Error recording litter.', 'danger')
    return redirect(request.referrer or url_for('breeding_pair_detail', pair_id=pair.id))

@app.route('/breeding/litter/edit/<int:litter_id>', methods=['POST'])
def edit_litter(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    form = LitterForm()
    if form.validate_on_submit():
        form.populate_obj(litter)
        db.session.commit()
        flash('Litter updated successfully.', 'success')
    else:
        flash('Error updating litter.', 'danger')
    return redirect(url_for('breeding_pair_detail', pair_id=litter.breeding_pair_id))

@app.route('/breeding/litter/delete/<int:litter_id>', methods=['POST'])
def delete_litter(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    pair_id = litter.breeding_pair_id
    db.session.delete(litter)
    db.session.commit()
    flash('Litter has been removed.', 'success')
    return redirect(url_for('breeding_pair_detail', pair_id=pair_id))

@app.route('/breeding/wean/<int:litter_id>', methods=['GET', 'POST'])
def wean_litter(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    form = WeaningForm()
    if form.validate_on_submit():
        for cage_data in form.cages:
            cage = Cage(
                custom_id=cage_data['custom_id'].data,
                species=litter.breeding_pair.male.species,
            )
            for i in range(cage_data['count'].data):
                animal = Animal(
                    cage=cage,
                    sex=cage_data['sex'].data,
                    dob=litter.dob,
                    species=cage.species,
                    breeding_pair=litter.breeding_pair,
                )
                db.session.add(animal)
            db.session.add(cage)
        litter.wean_date = form.wean_date.data
        db.session.commit()
        flash(f'Litter weaned into {len(form.cages)} new cages.', 'success')
    flash(f'Error weaning litter.', 'danger')
    return redirect(request.referrer or url_for('breeding_pair_detail', pair_id=litter.breeding_pair_id))

@app.route('/breeding/deactivate/<int:pair_id>', methods=['POST'])
def deactivate_pair(pair_id):
    pair = BreedingPair.query.get_or_404(pair_id)
    pair.is_active = False
    db.session.commit()
    flash(f'Breeding pair {pair.custom_id} deactivated.', 'info')
    return redirect(url_for('view_breeding_pairs'))

@app.route('/breeding/reactivate/<int:pair_id>', methods=['POST'])
def reactivate_pair(pair_id):
    pair = BreedingPair.query.get_or_404(pair_id)
    pair.is_active = True
    db.session.commit()
    flash(f'Breeding pair {pair.custom_id} reactivated.', 'success')
    return redirect(url_for('view_breeding_pairs'))

# --- Histology Routes ---
@app.route('/histology')
def view_histology():
    analysis_filter = request.args.get('analysis_filter', 'all')
    immunolabel_filter = request.args.get('immunolabel_filter', 'all')
    sort_by = request.args.get('sort_by', 'id')  # New sort argument
    query = Ear.query.join(Animal)

    # Filter Logic
    if immunolabel_filter == 'labeled':
        query = query.filter(Ear.immunolabel_date != None)
    elif immunolabel_filter == 'not_labeled':
        query = query.filter(Ear.immunolabel_date == None)

    # Sort Logic
    if sort_by == 'euthanasia':
        query = query.order_by(Animal.termination_date.desc().nulls_last())
    else:
        query = query.order_by(Ear.id.desc())

    if analysis_filter != 'all':
        # Join the ConfocalImage table and filter by the status column
        query = query.join(ConfocalImage).filter(ConfocalImage.status == analysis_filter)

    ears = query.distinct().all()
    panels = ImmunolabelingPanel.query.all()

    return render_template(
        'histology.html',
        analysis_filter=analysis_filter,
        ears=ears,
        panels=panels,
        filters={
            'immunolabel_filter': immunolabel_filter,
            'sort_by': sort_by,
            'analysis_filter': analysis_filter,
        },
        histology_form=HistologyForm(),
        histology_note_form=NoteForm(),
        confocal_form=ConfocalImageForm(),
    )

@app.route('/ear/<int:ear_id>')
def ear_detail(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    # We pass the same forms used elsewhere for consistency
    return render_template('ear_detail.html',
                           ear=ear,
                           confocal_form=ConfocalImageForm(),
                           histology_note_form=NoteForm()
                           )

@app.route('/add_confocal_images/<int:ear_id>', methods=['POST'])
def add_confocal_images(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = ConfocalImageForm()
    # Populate choices for image type
    form.image_type.choices = [(t.id, t.name) for t in ConfocalImageType.query.all()]

    if form.validate_on_submit():
        for freq_str in form.frequencies.data:
            new_image = ConfocalImage(
                ear_id=ear.id,
                frequency=float(freq_str),
                image_type=form.image_type.data,
                notes=form.notes.data,
                status='pending',
            )
            db.session.add(new_image)

        db.session.commit()
        flash(f'Images added for {ear.animal.custom_id} {ear.side}', 'success')
    else:
        flash(f'Error adding images for {ear.animal.custom_id} {ear.side}', 'danger')

    return redirect(request.referrer or url_for('view_histology'))

@app.route('/update_confocal_image/<int:image_id>', methods=['POST'])
def update_confocal_image(image_id):
    img = ConfocalImage.query.get_or_404(image_id)
    img.status = request.form.get('status')
    img.notes = request.form.get('notes')
    db.session.commit()
    return redirect(request.referrer or url_for('view_histology'))


@app.route('/delete_confocal_image/<int:image_id>', methods=['POST'])
def delete_confocal_image(image_id):
    # Locate the specific image record
    image_record = ConfocalImage.query.get_or_404(image_id)

    try:
        db.session.delete(image_record)
        db.session.commit()
        # Using a category like 'info' or 'success' for your flash messages
        flash('Imaging record deleted successfully.', 'info')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting record.', 'danger')

    # Return the user to the histology pipeline
    return redirect(request.referrer or url_for('view_histology'))

@app.route('/ear/update/<int:ear_id>', methods=['POST'])
def update_ear(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = HistologyForm(obj=ear)
    if form.validate_on_submit():
        form.populate_obj(ear)
        db.session.commit()
        flash('Ear updated.', 'success')
    else:
        flash(f'Error updating ear. {form.errors}', 'danger')
    return redirect(request.referrer or url_for('view_histology'))

# --- Studies Routes ---
@app.route('/studies')
def view_studies():
    studies = Study.query.all()
    return render_template('studies.html', studies=studies, study_form=StudyForm())

@app.route('/study/update/<int:study_id>', methods=['POST'])
def update_study(study_id):
    study = Study.query.get_or_404(study_id)
    form = StudyForm(obj=study)
    if form.validate_on_submit():
        form.populate_obj(study)
        db.session.commit()
        flash('Study updated successfully.', 'success')
    else:
        flash('Study update failed.', 'danger')
    return redirect(request.referrer or url_for('view_studies'))

@app.route('/studies/new', methods=['POST'])
def add_study():
    form = StudyForm()
    if form.validate_on_submit():
        study = Study(name=form.name.data, description=form.description.data)
        db.session.add(study)
        db.session.commit()
        flash('Study created successfully.', 'success')
    else:
        flash(f'Study create failed. {form.errors}', 'danger')
    return redirect(url_for('view_studies'))

@app.route('/study/<int:study_id>', methods=['GET', 'POST'])
def study_detail(study_id):
    study = Study.query.get_or_404(study_id)
    edit_form = StudyForm(obj=study)
    add_form = AddToStudyForm()
    add_form.animals.query = Animal.query.filter(Animal.custom_id != None)

    if edit_form.data and edit_form.validate_on_submit():
        if edit_form.name.data != study.name and Study.query.filter_by(name=edit_form.name.data).first():
            flash('A study with this name already exists.', 'danger')
        else:
            study.name = edit_form.name.data
            study.description = edit_form.description.data
            db.session.commit()
            flash(f'Study "{study.name}" has been updated.', 'success')
        return redirect(url_for('study_detail', study_id=study.id))
        
    return render_template(
        'study_detail.html',
        study=study,
        edit_form=edit_form,
        add_form=add_form,
        note_form=NoteForm()
    )

@app.route('/study/<int:study_id>/add_animals', methods=['POST'])
def add_to_study(study_id):
    study = Study.query.get_or_404(study_id)
    form = AddToStudyForm()
    form.animals.query = Animal.query.all()
    if form.validate_on_submit():
        for animal in form.animals.data:
            study.animals.append(animal)
        db.session.commit()
        flash(f'{len(form.animals.data)} animals added to study "{study.name}".', 'success')
    return redirect(request.referrer or url_for('study_detail', study_id=study.id))

@app.route('/study/<int:study_id>/remove/<int:animal_id>', methods=['POST'])
def remove_from_study(study_id, animal_id):
    study = Study.query.get_or_404(study_id)
    animal = Animal.query.get_or_404(animal_id)
    if animal in study.animals.all():
        study.animals.remove(animal)
        db.session.commit()
        flash(f'Animal {animal.custom_id} removed from study.', 'success')
    return redirect(request.referrer or url_for('study_detail', study_id=study.id))

@app.route('/study/quick_add/<int:animal_id>', methods=['POST'])
def quick_add_to_study(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = QuickAddToStudyForm()
    if form.validate_on_submit():
        study = form.study.data
        if animal not in study.animals:
            study.animals.append(animal)
            db.session.commit()
            flash(f'Animal {animal.custom_id} added to study "{study.name}".', 'success')
        else:
            flash(f'Animal {animal.custom_id} is already in study "{study.name}".', 'warning')
    return redirect(request.referrer or url_for('view_animals'))

# --- Settings Routes ---
SETTINGS = {
    'species': {'model': Species, 'form': SimpleAddForm},
    'source': {'model': Source, 'form': SimpleAddForm},
    'animal_procedure': {'model': AnimalProcedure, 'form': SimpleAddWithDescriptionForm},
    'animal_procedure_target': {'model': AnimalProcedureTarget, 'form': SimpleAddWithDescriptionForm},
    'termination_reason': {'model': TerminationReason, 'form': SimpleAddWithDescriptionForm},
    'immunolabeling_panel': {'model': ImmunolabelingPanel, 'form': SimpleAddForm},
    'reagent': {'model': Reagent, 'form': SimpleAddWithDescriptionForm},
    'confocal_image_type': {'model': ConfocalImageType, 'form': SimpleAddForm},
}

@app.route('/settings')
def settings():
    return render_template(
        'settings.html',
        species=Species.query.all(),
        sources=Source.query.all(),
        animal_procedures=AnimalProcedure.query.all(),
        animal_procedure_targets=AnimalProcedureTarget.query.all(),
        termination_reasons=TerminationReason.query.all(),
        confocal_image_types=ConfocalImageType.query.all(),
        panels=ImmunolabelingPanel.query.all(),
        simple_add_form=SimpleAddForm(),
        simple_add_with_description_form=SimpleAddWithDescriptionForm(),
    )

@app.route('/settings/add/<item_type>', methods=['POST'])
def add_setting(item_type):
    Model = SETTINGS[item_type]['model']
    form = SETTINGS[item_type]['form']()
    if form.validate_on_submit():
        if Model.query.filter(Model.name == form.name.data).first():
            flash(f'Error adding {item_type.replace("_", " ")}. It might already exist.', 'danger')
        else:
            data = form.data.copy()
            data.pop('csrf_token')
            item = Model(**data)
            db.session.add(item)
            db.session.commit()
            flash(f'{item_type.replace("_", " ").title()} "{form.name.data}" added.', 'success')
    return redirect(url_for('settings'))

@app.route('/settings/update/<item_type>/<int:item_id>', methods=['POST'])
def update_setting(item_type, item_id):
    # Fetch the record
    item = SETTINGS[item_type]['model'].query.get_or_404(item_id)
    # Get the new name/reason from the form
    form = SETTINGS[item_type]['form']()
    try:
        for k, v in form.data.items():
            if k == 'csrf_token':
                continue
            setattr(item, k, v)
        db.session.commit()
        flash(f"Updated successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating: {str(e)}", "danger")
    return redirect(url_for('settings'))

@app.route('/settings/delete/<item_type>/<int:item_id>', methods=['POST'])
def delete_setting(item_type, item_id):
    item = SETTINGS[item_type]['model'].query.get_or_404(item_id)
    if (item_type == 'species' and item.animals) or \
       (item_type == 'source' and item.animals) or \
       (item_type == 'procedure' and item.events) or \
       (item_type == 'termination_reason' and item.animals):
        flash(f'Cannot delete {item.name} because it is currently in use.', 'danger')
        return redirect(url_for('settings'))
    db.session.delete(item)
    db.session.commit()
    flash(f'{item_type.replace("_", " ").title()} deleted.', 'success')
    return redirect(url_for('settings'))

@app.route('/settings/panel/delete/<int:panel_id>', methods=['POST'])
def delete_panel(panel_id):
    panel = ImmunolabelingPanel.query.get_or_404(panel_id)
    if panel.ears:
        flash(f'Cannot delete "{panel.name}" because it is in use on at least one ear.', 'danger')
        return redirect(url_for('settings'))
    db.session.delete(panel)
    db.session.commit()
    flash(f'Panel "{panel.name}" deleted.', 'success')
    return redirect(url_for('settings'))

@app.route('/settings/reagent/new/<int:panel_id>', methods=['POST'])
def add_reagent(panel_id):
    form = SimpleAddWithDescriptionForm()
    panel = ImmunolabelingPanel.query.get_or_404(panel_id)
    if form.validate_on_submit():
        reagent = Reagent(name=form.name.data, description=form.description.data, panel_id=panel.id)
        db.session.add(reagent)
        db.session.commit()
        flash(f'Reagent "{reagent.name}" added to panel "{panel.name}".', 'success')
    else:
        flash('Could not add reagent. Please check the form.', 'danger')
    return redirect(url_for('settings'))

@app.route('/ajax/form/<item_type>/<int:item_id>')
def modal_form(item_type, item_id):
    # Can be overridden if needed
    template = 'partials/form_modal.html'
    if item_type == 'Animal':
        item = Animal.query.get_or_404(item_id)
        form = AnimalForm(obj=item)
        label = f'Edit {item.custom_id}'
        submit_url = url_for('update_animal', animal_id=item.id)
    elif item_type == 'NewAnimal':
        item = None
        form = AnimalForm(obj=item)
        label = f'Create new animal'
        submit_url = url_for('create_animal')
    elif item_type == 'AnimalID':
        item = Animal.query.get_or_404(item_id)
        form = AnimalCustomIDForm(custom_id=f'{item.cage.custom_id}-')
        label = f'Assign id for {item.custom_id}'
        submit_url = url_for('update_animal', animal_id=item.id)
    elif item_type == 'AnimalEvent':
        item = AnimalEvent.query.get_or_404(item_id)
        form = EventForm(obj=item)
        label = f'Edit event for {item.animal.custom_id}'
        submit_url = url_for('update_event', event_id=item.id)
    elif item_type == 'NewAnimalEvent':
        item = Animal.query.get_or_404(item_id)
        form = EventForm(animal=item)
        label = f'Create event for {item.custom_id}'
        submit_url = url_for('create_event', animal_id=item.id)
    elif item_type == 'DeleteAnimalEvent':
        item = AnimalEvent.query.get_or_404(item_id)
        form = EventDeleteForm(obj=item)
        label = f'Remove event for {item.animal.custom_id}'
        submit_url = url_for('delete_event', event_id=item.id)
    elif item_type == 'AnimalNote':
        item = Animal.query.get_or_404(item_id)
        form = NoteForm(obj=item)
        label = f'Edit note for {item.custom_id}'
        submit_url = url_for('update_animal', animal_id=item_id)
    elif item_type == 'CageNote':
        item = Cage.query.get_or_404(item_id)
        form = NoteForm(obj=item)
        label = f'Edit note for {item.custom_id}'
        submit_url = url_for('update_cage_note', cage_id=item_id)
    elif item_type == 'TerminationReason':
        item = Animal.query.get_or_404(item_id)
        form = TerminationForm(obj=item)
        label = f'Remove {item.custom_id}'
        submit_url = url_for('terminate_animal', animal_id=item_id)
    elif item_type == 'NewCage':
        form = CageForm()
        label = 'Add Cage'
        submit_url = url_for('add_cage')
        item = None
    elif item_type == 'NewStudy':
        form = StudyForm()
        label = 'Add Study'
        submit_url = url_for('add_study')
        item = None
    elif item_type == 'Study':
        item = Study.query.get_or_404(item_id)
        form = StudyForm(obj=item)
        label = f'Edit Study {item.name}'
        submit_url = url_for('update_study', study_id=item.id)
    elif item_type == 'EarNote':
        item = Ear.query.get_or_404(item_id)
        form = NoteForm(obj=item)
        label = f'Edit note for {item.animal.custom_id} {item.side}'
        submit_url = url_for('update_ear', ear_id=item.id)
    elif item_type == 'EarHistology':
        item = Ear.query.get_or_404(item_id)
        form = HistologyForm(obj=item)
        label = f'Edit histology for {item.animal.custom_id} {item.side}'
        submit_url = url_for('update_ear', ear_id=item.id)
    elif item_type == 'AddConfocalImages':
        item = Ear.query.get_or_404(item_id)
        form = ConfocalImageForm()
        label = f'Add images for {item.animal.custom_id} {item.side}'
        submit_url = url_for('add_confocal_images', ear_id=item.id)
    elif item_type == 'UpdateStudyList':
        item = Animal.query.get_or_404(item_id)
        form = QuickAddToStudyForm()
        label = f'Add study for {item.custom_id}'
        submit_url = url_for('quick_add_to_study', animal_id=item.id)
    elif item_type == 'NewBP':
        item = None
        form = BreedingPairForm()
        label = 'Add Breeding Pair'
        submit_url = url_for('add_breeding_pair')
        template = 'partials/bp_form_modal.html'
    elif item_type == "AddLitter":
        item = BreedingPair.query.get_or_404(item_id)
        form = LitterForm()
        label = f'Add litter for {item.custom_id}'
        submit_url = url_for('add_litter', pair_id=item.id)
    elif item_type == "EditLitter":
        item = Litter.query.get_or_404(item_id)
        form = LitterForm(obj=item)
        label = f'Edit litter for {item.breeding_pair.custom_id}'
        submit_url = url_for('edit_litter', litter_id=item.id)
    elif item_type == "DeleteLitter":
        item = Litter.query.get_or_404(item_id)
        form = LitterDeleteForm(obj=item)
        label = f'Delete litter from {item.breeding_pair.custom_id}'
        submit_url = url_for('delete_litter', litter_id=item.id)
    elif item_type == 'WeanLitter':
        item = Litter.query.get_or_404(item_id)
        form = WeaningForm()
        submit_url = url_for('wean_litter', litter_id=item.id)
        label = f'Wean litter from {item.breeding_pair.custom_id}'
        template = 'partials/bp_wean_form_modal.html'

    return render_template(
        template,
        form=form,
        item=item,
        label=label,
        submit_url=submit_url,
    )

@app.route('/ajax/event/<int:animal_id>')
def ajax_animal_events(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    return render_template(
        'partials/event_popover.html',
        animal=animal,
    )

@app.route('/ajax/ear_images/<int:ear_id>')
def ajax_ear_images(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    return render_template(
        'partials/ear_images_popover.html',
        ear=ear,
    )


if __name__ == '__main__':
    app.run(debug=True)