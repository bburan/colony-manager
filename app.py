import os
from xml.sax.handler import property_declaration_handler

from flask import Flask, render_template, request, redirect, url_for, flash, g, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, desc
from flask_migrate import Migrate
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, DateField, SelectField, SelectMultipleField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional, ValidationError, Length
from wtforms.widgets import ListWidget, CheckboxInput
from wtforms_sqlalchemy.fields import QuerySelectField, QuerySelectMultipleField
from datetime import date, datetime

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
class Species(db.Model):
    # Species available
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    animals = db.relationship('Animal', backref='species', lazy=True)
    cages = db.relationship('Cage', backref='species', lazy=True)

class Source(db.Model):
    # Source for a particular animal
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    animals = db.relationship('Animal', backref='source', lazy=True)

class AnimalProcedure(db.Model):
    # Any sort of procedure that might be performed on an animal in a systemic fashion (e.g., noise-exposure, injection, etc.).
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    events = db.relationship('AnimalEvent', backref='procedure', lazy=True)

class EarProcedure(db.Model):
    # Any sort of procedure that might be performed on an animal ear in a systemic fashion (e.g., ABR, hydrogel application, etc.).
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    events = db.relationship('EarEvent', backref='procedure', lazy=True)

class TerminationReason(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    animals = db.relationship('Animal', backref='termination_reason', lazy=True)

class Cage(db.Model):
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

class Animal(db.Model):
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

class BreedingPair(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(50), unique=True, nullable=False)
    male_animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    female_animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    litters = db.relationship('Litter', backref='breeding_pair', lazy='dynamic', cascade="all, delete-orphan")

class Litter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    breeding_pair_id = db.Column(db.Integer, db.ForeignKey('breeding_pair.id'), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    pup_count = db.Column(db.Integer, nullable=False)
    is_weaned = db.Column(db.Boolean, default=False, nullable=False)

class AnimalEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    procedure_id = db.Column(db.Integer, db.ForeignKey('animal_procedure.id'), nullable=False)
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

class EarEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ear_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    procedure_id = db.Column(db.Integer, db.ForeignKey('ear_procedure.id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    completion_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)

class ImmunolabelingPanel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    reagents = db.relationship('Reagent', backref='panel', lazy='dynamic', cascade="all, delete-orphan")
    ears = db.relationship('Ear', backref='panel', lazy=True)

class Reagent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    panel_id = db.Column(db.Integer, db.ForeignKey('immunolabeling_panel.id'), nullable=False)

class Ear(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    side = db.Column(db.String(5), nullable=False)
    cryoprotection_date = db.Column(db.Date, nullable=True)
    dissection_date = db.Column(db.Date, nullable=True)
    immunolabel_date = db.Column(db.Date, nullable=True)
    panel_id = db.Column(db.Integer, db.ForeignKey('immunolabeling_panel.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    confocal_images = db.relationship('ConfocalImage', backref='ear', lazy=True)

class ConfocalImageType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    confocal_images = db.relationship('ConfocalImage', backref='image_type', lazy=True)

class ConfocalImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ear_id = db.Column(db.Integer, db.ForeignKey('ear.id'), nullable=False)
    #ear = db.relationship('Ear')
    frequency = db.Column(db.Integer, nullable=False)
    image_type_id = db.Column(db.Integer, db.ForeignKey('confocal_image_type.id'), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(150), nullable=True)

class Study(db.Model):
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
def ear_procedure_factory(): return EarProcedure.query.order_by('name')
def panel_factory(): return ImmunolabelingPanel.query.order_by('name')
def termination_reason_factory(): return TerminationReason.query.order_by(TerminationReason.name)
def male_animal_factory(): return Animal.query.filter(Animal.is_terminated==False, Animal.sex=='Male').order_by(Animal.id)
def female_animal_factory(): return Animal.query.filter(Animal.is_terminated==False, Animal.sex=='Female').order_by(Animal.id)
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

class AnimalForm(FlaskForm):
    custom_id = StringField('Animal ID', validators=[DataRequired()])
    cage = QuerySelectField('Cage', query_factory=cage_factory, get_label='custom_id')
    species = QuerySelectField('Species', query_factory=species_factory, get_label='name')
    sex = SelectField('Sex', choices=[('male', 'male'), ('female', 'female')], validators=[DataRequired()])
    dob = DateField('Date of Birth', default=date.today, validators=[DataRequired()])
    source = QuerySelectField('Source', query_factory=source_factory, get_label='name', allow_blank=True)
    notes = TextAreaField('Notes', validators=[Optional()])
    termination_date = DateField('Termination date', validators=[Optional()])
    termination_reason = QuerySelectField('Termination reason', query_factory=termination_reason_factory, get_label='name')

    def __init__(self, *args, obj=None, **kwargs):
        super(AnimalForm, self).__init__(*args, obj=obj, **kwargs)
        self.initial_custom_id = obj.custom_id

    def validate_custom_id(self, field):
        if self.initial_custom_id != field.data:
            if Animal.query.filter_by(custom_id=field.data).first():
                raise ValidationError(f'Animal ID "{field.data}" already exists.')

class EventForm(FlaskForm):
    procedure = QuerySelectField('Procedure', query_factory=animal_procedure_factory, get_label='name', allow_blank=False)
    scheduled_date = DateField('Scheduled Date', default=date.today, validators=[DataRequired()])
    completion_date = DateField('Completed Date', default=None, validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])

class BreedingPairForm(FlaskForm):
    custom_id = StringField('Pair ID', validators=[DataRequired(), Length(min=1, max=50)])
    male_animal = QuerySelectField('Male', query_factory=male_animal_factory, get_label='custom_id', allow_blank=False, validators=[DataRequired()])
    female_animal = QuerySelectField('Female', query_factory=female_animal_factory, get_label='custom_id', allow_blank=False, validators=[DataRequired()])
    start_date = DateField('Pairing Start Date', default=date.today, validators=[DataRequired()])

    def validate_custom_id(self, field):
        if BreedingPair.query.filter_by(custom_id=field.data).first():
            raise ValidationError(f'Pair ID "{field.data}" already exists.')

class LitterForm(FlaskForm):
    birth_date = DateField('Litter Birth Date', default=date.today, validators=[DataRequired()])
    pup_count = IntegerField('Number of Pups', validators=[InputRequired(), NumberRange(min=1)])

class TerminationForm(FlaskForm):
    termination_date = DateField('Date of Termination', default=date.today, validators=[DataRequired()])
    termination_reason = QuerySelectField('Reason', query_factory=termination_reason_factory, get_label='name', allow_blank=True)
    ears_extracted = SelectField('Ears Extracted', choices=[('None', 'None'), ('Left', 'Left'), ('Right', 'Right'), ('Both', 'Both')], validators=[DataRequired()])


class StudyForm(FlaskForm):
    name = StringField('Study Name', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[Optional()])

class AddToStudyForm(FlaskForm):
    animals = QuerySelectMultipleField('Select Animals', query_factory=active_animal_factory, get_label='custom_id',
                                     widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())

class QuickAddToStudyForm(FlaskForm):
    study = QuerySelectField('Study', query_factory=study_factory, get_label='name', allow_blank=False)

class ConfocalImageForm(FlaskForm):
    # Frequencies: Octave spaced from 0.5 to 64
    FREQUENCIES = [0.5, 0.7, 1, 1.4, 2, 2.8, 4, 5.6, 8, 11.2, 16, 22.6, 32, 45.2, 64]

    frequencies = SelectMultipleField(
        'Frequencies (kHz)',
        choices=[(str(f), str(f)) for f in FREQUENCIES],
        option_widget=CheckboxInput(),
        widget=ListWidget(prefix_label=False)
    )
    image_type = QuerySelectField('Image Type', query_factory=confocal_image_type_factory, get_label='name', validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])

# --- Context Processors and Before Request ---
@app.before_request
def before_request_func():
    g.event_form = EventForm()

# --- Routes ---
from datetime import date, timedelta
from sqlalchemy import or_


@app.route('/')
def index():
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    # 1. Metrics for Top Cards
    # Using .filter instead of list comprehension for performance
    active_cages_count = Cage.query.filter(Cage.animals.any()).count()

    # Active animals (assuming active means not yet terminated)
    active_animals_count = Animal.query.filter(Animal.termination_date == None).count()

    active_breeding_pairs_count = BreedingPair.query.filter_by(is_active=True).count()

    # Ears for processing (those not yet dissected)
    ears_for_processing_count = Ear.query.filter(Ear.dissection_date == None).count()

    # 2. Upcoming Events Table (Next 7 days + Overdue)
    upcoming_events = AnimalEvent.query.filter(
        AnimalEvent.completion_date == None,
        AnimalEvent.scheduled_date <= today + timedelta(days=7)
    ).order_by(AnimalEvent.scheduled_date.asc()).all()

    # 3. Action Required & Summary Logic
    overdue_events_count = AnimalEvent.query.filter(
        AnimalEvent.completion_date == None,
        AnimalEvent.scheduled_date <= today,
    ).count()

    active_studies_count = Study.query.count()

    # Animals terminated in the last 30 days
    recent_terminations = Animal.query.filter(
        Animal.termination_date >= thirty_days_ago
    ).count()

    return render_template('index.html',
                           # Card Metrics
                           active_cages=active_cages_count,
                           active_animals=active_animals_count,
                           active_pairs=active_breeding_pairs_count,
                           ears_to_process=ears_for_processing_count,

                           # Schedule & Alerts
                           upcoming_events=upcoming_events,
                           overdue_events_count=overdue_events_count,
                           today=today,

                           # Summary Stats
                           active_studies_count=active_studies_count,
                           recent_terminations=recent_terminations
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
    filter_by = request.args.get('filter', 'active')
    all_cages = Cage.query.all()
    if filter_by == 'active':
        cages = [c for c in all_cages if c.is_active]
    elif filter_by == 'inactive':
        cages = [c for c in all_cages if not c.is_active]
    else:
        cages = all_cages
    return render_template(
        'cages.html',
        cages=cages,
        form=CageForm(),
        age_unit=age_unit,
        filter_by=filter_by
    )

@app.route('/cage/rename/<int:cage_id>', methods=['GET', 'POST'])
def rename_cage(cage_id):
    pass

@app.route('/cage/delete/<int:cage_id>', methods=['GET', 'POST'])
def delete_cage(cage_id):
    pass

@app.route('/cage/update-notes/<int:cage_id>', methods=['GET', 'POST'])
def update_cage_notes(cage_id):
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

@app.route('/cages/new', methods=['GET', 'POST'])
def new_cage():
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
    return render_template('cage_add.html', form=CageForm())

# --- Animal Routes ---
@app.route('/animals')
def view_animals():
    sort_by = request.args.get('sort_by', 'id')
    event_filter = request.args.get('event_filter', 'all')
    status_filter = request.args.get('status_filter', 'active')
    procedure_filter = request.args.get('procedure_filter', 'all')
    study_filter = request.args.get('study_filter', 'all')
    age_unit = request.args.get('age_unit', 'day')
    event_status = request.args.get('event_status', 'all')
    search_query = request.args.get('search_query', '')

    query = Animal.query.filter(Animal.custom_id.is_not(None))

    if search_query:
        # We join Events and Procedures to allow searching by procedure name
        # .ilike(f'%{search_query}%') handles the "partial match" requirement
        query = query.join(Animal.events, isouter=True).join(AnimalEvent.procedure, isouter=True).filter(
            db.or_(
                Animal.custom_id.ilike(f'%{search_query}%'),
                Procedure.name.ilike(f'%{search_query}%')
            )
        )

    if status_filter == 'active':
        query = query.filter(Animal.termination_reason_id.is_(None))
    elif status_filter == 'terminated':
        query = query.filter(Animal.termination_reason_id.is_not(None))
    
    if procedure_filter != 'all':
        query = query.join(Animal.events).filter(AnimalEvent.procedure_id == int(procedure_filter))

    if study_filter != 'all':
        query = query.join(Animal.studies).filter(Study.id == int(study_filter))

    animals = query.all()
    if sort_by == 'age':
        animals.sort(key=lambda a: a.age_in_days)
    elif sort_by == 'event_date':
        animals.sort(key=lambda a: a.last_event_date, reverse=True)
    else:
        animals.sort(key=lambda a: a.custom_id)

    if event_filter == 'events':
        animals = [a for a in animals if a.has_events]
    elif event_filter == 'no_events':
        animals = [a for a in animals if not a.has_events]

    if event_status == 'due':
        animals = [a for a in animals if a.event_due]
    elif event_status == 'overdue':
        animals = [a for a in animals if a.event_overdue]

    return render_template(
        'animals.html',
        animals=animals,
        termination_form=TerminationForm(),
        note_form=NoteForm(),
        quick_add_form=QuickAddToStudyForm(),
        sort_by=sort_by,
        event_filter=event_filter,
        event_status=event_status,
        status_filter=status_filter,
        procedure_filter=procedure_filter,
        age_unit=age_unit,
        study_filter=study_filter,
        procedures=AnimalProcedure.query.all(),
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

@app.route('/animal/update_id/<int:animal_id>', methods=['POST'])
def update_animal_id(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    new_id = request.form.get('custom_id', '').strip()

    if not new_id:
        flash('Animal ID cannot be empty.', 'danger')
        return redirect(request.referrer or url_for('view_animals'))

    existing_animal = Animal.query.filter(Animal.id != animal_id, Animal.custom_id == new_id).first()
    if existing_animal:
        flash(f'Animal ID "{new_id}" is already in use.', 'danger')
    else:
        animal.custom_id = new_id
        db.session.commit()
        flash('Animal ID updated successfully.', 'success')
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
    form = EventForm()
    if form.validate_on_submit():
        event = AnimalEvent.query.get_or_404(event_id)
        event.procedure = form.procedure.data
        event.scheduled_date = form.scheduled_date.data
        event.completion_date = form.completion_date.data
        event.notes = form.notes.data
        db.session.commit()
        flash('Event updated successfully.', 'success')
    else:
        flash('Error updating event.', 'danger')
    return redirect(request.referrer or url_for('view_animals'))

@app.route('/animal/events/create/<int:animal_id>', methods=['POST'])
def create_event(animal_id):
    form = EventForm()
    if form.validate_on_submit():
        event = AnimalEvent(
            animal_id=animal_id,
            procedure_id=form.procedure.data.id,
            scheduled_date=form.scheduled_date.data,
            completion_date=form.completion_date.data,
            notes=form.notes.data,
        )
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

@app.route('/animal/note/<int:animal_id>', methods=['POST'])
def save_animal_note(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = NoteForm()
    if form.validate_on_submit():
        animal.notes = form.notes.data
        db.session.commit()
        flash(f'Notes for animal {animal.custom_id} updated.', 'success')
    return redirect(request.referrer or url_for('view_animals'))

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
        if form.male_animal.data.sex != 'Male' or form.female_animal.data.sex != 'Female':
            flash('Selected animals must be of the correct sex.', 'danger')
            return redirect(url_for('view_breeding_pairs'))
        if form.male_animal.data.species != form.female_animal.data.species:
            flash('Male and female must be of the same species.', 'danger')
            return redirect(url_for('view_breeding_pairs'))
        pair = BreedingPair(
            custom_id=form.custom_id.data,
            male_animal_id=form.male_animal.data.id, 
            female_animal_id=form.female_animal.data.id, 
            start_date=form.start_date.data
        )
        db.session.add(pair)
        db.session.commit()
        flash('New breeding pair created successfully.', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", 'danger')
    return redirect(url_for('view_breeding_pairs'))

@app.route('/breeding/litter/new/<int:pair_id>', methods=['POST'])
def add_litter(pair_id):
    pair = BreedingPair.query.get_or_404(pair_id)
    form = LitterForm()
    if form.validate_on_submit():
        litter = Litter(breeding_pair_id=pair.id, birth_date=form.birth_date.data, pup_count=form.pup_count.data)
        db.session.add(litter)
        db.session.commit()
        flash(f'Litter recorded for breeding pair {pair.custom_id}.', 'success')
    else:
        flash('Error recording litter.', 'danger')
    return redirect(url_for('breeding_pair_detail', pair_id=pair.id))

@app.route('/breeding/litter/edit/<int:litter_id>', methods=['POST'])
def edit_litter(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    form = LitterForm()
    if form.validate_on_submit():
        litter.birth_date = form.birth_date.data
        litter.pup_count = form.pup_count.data
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
    flash('Litter has been culled (deleted).', 'success')
    return redirect(url_for('breeding_pair_detail', pair_id=pair_id))

@app.route('/breeding/wean/<int:litter_id>', methods=['GET', 'POST'])
def wean_litter(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    if request.method == 'POST':
        counts = request.form.getlist('counts')
        sexes = request.form.getlist('sexes')
        species = litter.breeding_pair.male.species
        cages_created = 0
        for i, count_str in enumerate(counts):
            if count_str and int(count_str) > 0:
                count = int(count_str)
                sex = sexes[i]
                
                new_cage_id_base = f"L{litter.id}C{i+1}"
                new_cage_custom_id = new_cage_id_base
                suffix = 1
                while Cage.query.filter_by(custom_id=new_cage_custom_id).first():
                    new_cage_custom_id = f"{new_cage_id_base}-{suffix}"
                    suffix += 1

                new_cage = Cage(custom_id=new_cage_custom_id, species_id=species.id, breeding_pair_id=litter.breeding_pair_id, date_of_birth=litter.birth_date, sex=sex)
                db.session.add(new_cage)
                db.session.commit()
                for j in range(count):
                    animal = Animal(cage_id=new_cage.id, animal_number=j + 1, custom_id=f"{new_cage.custom_id}-{j+1}", sex=sex, date_of_birth=litter.birth_date, species_id=species.id)
                    db.session.add(animal)
                cages_created += 1
        if cages_created > 0:
            litter.is_weaned = True
            db.session.commit()
            flash(f'Litter weaned into {cages_created} new cages.', 'success')
        else:
            flash('No pups were weaned as no counts were provided.', 'warning')
        return redirect(url_for('breeding_pair_detail', pair_id=litter.breeding_pair_id))
    return render_template('wean_litter.html', litter=litter)

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
    labeled_filter = request.args.get('labeled_filter', 'all')
    sort_by = request.args.get('sort_by', 'id')  # New sort argument
    query = Ear.query.join(Animal)

    # Filter Logic
    if labeled_filter == 'labeled':
        query = query.filter(Ear.immunolabel_date != None)
    elif labeled_filter == 'not_labeled':
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
        labeled_filter=labeled_filter,
        sort_by=sort_by,  # Pass this back to keep buttons active
        histology_form=HistologyForm(),
        histology_note_form=NoteForm(),
        confocal_form=ConfocalImageForm(),
    )

@app.route('/histology/update/<int:ear_id>', methods=['POST'])
def update_ear(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = HistologyForm()
    if form.validate_on_submit():
        ear.cryoprotection_date = form.cryoprotection_date.data
        ear.dissection_date = form.dissection_date.data
        ear.immunolabel_date = form.immunolabel_date.data
        selected_panel = form.panel.data
        ear.panel_id = selected_panel.id if selected_panel else None
        print(form.data)
        db.session.commit()
        flash(f'Ear #{ear.id} ({ear.animal.custom_id} - {ear.side}) updated.', 'success')
    else:
        print(form.errors)
    return redirect(request.referrer or url_for('view_histology'))

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

    return redirect(url_for('view_histology'))

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

@app.route('/save_ear_note/<int:ear_id>', methods=['POST'])
def save_ear_note(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    ear.notes = request.form.get('note')
    db.session.commit()
    flash('Ear note updated.', 'success')
    return redirect(url_for('view_histology'))

# --- Studies Routes ---
@app.route('/studies')
def view_studies():
    studies = Study.query.all()
    return render_template('studies.html', studies=studies, study_form=StudyForm())

@app.route('/studies/new', methods=['POST'])
def add_study():
    form = StudyForm()
    if form.validate_on_submit():
        if Study.query.filter_by(name=form.name.data).first():
            flash('A study with this name already exists.', 'danger')
        else:
            study = Study(name=form.name.data, description=form.description.data)
            db.session.add(study)
            db.session.commit()
            flash('Study created successfully.', 'success')
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
    'ear_procedure': {'model': EarProcedure, 'form': SimpleAddWithDescriptionForm},
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
        ear_procedures=EarProcedure.query.all(),
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
    if item_type == 'Animal':
        item = Animal.query.get_or_404(item_id)
        form = AnimalForm(obj=item)
        label = f'Edit {item.custom_id}'
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
    elif item_type == 'AnimalNote':
        item = Animal.query.get_or_404(item_id)
        form = NoteForm(obj=item)
        label = f'Edit note for {item.custom_id}'
        submit_url = url_for('save_animal_note', animal_id=item_id)
    elif item_type == 'TerminationReason':
        item = Animal.query.get_or_404(item_id)
        form = TerminationForm(obj=item)
        label = f'Remove {item.custom_id}'
        submit_url = url_for('terminate_animal', animal_id=item_id)
    return render_template(
        'partials/form_modal.html',
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

if __name__ == '__main__':
    app.run(debug=True)
