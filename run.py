import os
from flask import Flask, render_template, request, redirect, url_for, flash, g, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, desc
from flask_migrate import Migrate
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, DateField, SelectField, SubmitField, TextAreaField
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
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    cages = db.relationship('Cage', backref='species', lazy=True)

class Source(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    cages = db.relationship('Cage', backref='source', lazy=True)

class Procedure(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    events = db.relationship('AnimalEvent', backref='procedure', lazy=True)

class TerminationReason(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reason = db.Column(db.String(150), unique=True, nullable=False)
    animals = db.relationship('Animal', backref='termination_reason', lazy=True)

class Cage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(50), unique=True, nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    sex = db.Column(db.String(10), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    species_id = db.Column(db.Integer, db.ForeignKey('species.id'), nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey('source.id'), nullable=True)
    breeding_pair_id = db.Column(db.Integer, db.ForeignKey('breeding_pair.id'), nullable=True)
    animals = db.relationship('Animal', backref='cage', lazy='dynamic', cascade="all, delete-orphan")

    @property
    def age_in_days(self):
        return (date.today() - self.date_of_birth).days

    @property
    def source_display(self):
        if self.source:
            return self.source.name
        if self.breeding_pair:
            return f"Breeding Pair #{self.breeding_pair.id}"
        return "Unknown"

    @property
    def is_active(self):
        return self.animals.filter_by(is_terminated=False).count() > 0

class Animal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(100), unique=True, nullable=False)
    animal_number = db.Column(db.Integer, nullable=False)
    cage_id = db.Column(db.Integer, db.ForeignKey('cage.id'), nullable=False)
    general_notes = db.Column(db.Text, nullable=True)
    is_terminated = db.Column(db.Boolean, default=False, nullable=False)
    termination_date = db.Column(db.Date, nullable=True)
    termination_reason_id = db.Column(db.Integer, db.ForeignKey('termination_reason.id'), nullable=True)
    ears_extracted = db.Column(db.String(10), default='None')
    events = db.relationship('AnimalEvent', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    ears = db.relationship('Ear', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    breeding_pair_male = db.relationship('BreedingPair', foreign_keys='BreedingPair.male_animal_id', backref='male', lazy=True)
    breeding_pair_female = db.relationship('BreedingPair', foreign_keys='BreedingPair.female_animal_id', backref='female', lazy=True)

    @property
    def has_events(self):
        return self.events.count() > 0
    
    @property
    def last_event_date(self):
        last_event = self.events.filter_by(status='completed').order_by(AnimalEvent.completion_date.desc()).first()
        return last_event.completion_date if last_event else date.min

class BreedingPair(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    male_animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    female_animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    litters = db.relationship('Litter', backref='breeding_pair', lazy='dynamic', cascade="all, delete-orphan")
    cages_sourced = db.relationship('Cage', backref='breeding_pair', lazy=True)

class Litter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    breeding_pair_id = db.Column(db.Integer, db.ForeignKey('breeding_pair.id'), nullable=False)
    birth_date = db.Column(db.Date, nullable=False)
    pup_count = db.Column(db.Integer, nullable=False)
    is_weaned = db.Column(db.Boolean, default=False, nullable=False)

class AnimalEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    procedure_id = db.Column(db.Integer, db.ForeignKey('procedure.id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    completion_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='scheduled') # scheduled, completed
    notes = db.Column(db.Text, nullable=True)

class ImmunolabelingPanel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    reagents = db.relationship('Reagent', backref='panel', lazy='dynamic', cascade="all, delete-orphan")
    ears = db.relationship('Ear', backref='panel', lazy=True)

class Reagent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    dilution = db.Column(db.String(50), nullable=True)
    panel_id = db.Column(db.Integer, db.ForeignKey('immunolabeling_panel.id'), nullable=False)

class Ear(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    side = db.Column(db.String(5), nullable=False)
    cryoprotection_date = db.Column(db.Date, nullable=True)
    dissection_date = db.Column(db.Date, nullable=True)
    panel_id = db.Column(db.Integer, db.ForeignKey('immunolabeling_panel.id'), nullable=True)

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
def procedure_factory(): return Procedure.query.order_by('name')
def panel_factory(): return ImmunolabelingPanel.query.order_by('name')
def termination_reason_factory(): return TerminationReason.query.order_by('reason')
def male_animal_factory(): return Animal.query.join(Cage).filter(Animal.is_terminated==False, Cage.sex=='Male').order_by(Animal.id)
def female_animal_factory(): return Animal.query.join(Cage).filter(Animal.is_terminated==False, Cage.sex=='Female').order_by(Animal.id)
def active_animal_factory(): return Animal.query.filter_by(is_terminated=False)

class SimpleAddForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    submit = SubmitField('Add')

class CageForm(FlaskForm):
    custom_id = StringField('Cage ID (e.g., B001)', validators=[DataRequired(), Length(min=1, max=50)])
    species = QuerySelectField('Species', query_factory=species_factory, get_label='name', allow_blank=False, validators=[DataRequired()])
    source = QuerySelectField('Source', query_factory=source_factory, get_label='name', allow_blank=True)
    sex = SelectField('Sex', choices=[('Male', 'Male'), ('Female', 'Female')], validators=[DataRequired()])
    number_of_animals = IntegerField('Number of Animals', validators=[InputRequired(), NumberRange(min=1)])
    date_of_birth = DateField('Date of Birth', default=date.today, validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Create Cage')

    def validate_custom_id(self, field):
        if Cage.query.filter_by(custom_id=field.data).first():
            raise ValidationError(f'Cage ID "{field.data}" already exists.')

class ScheduleEventForm(FlaskForm):
    procedure = QuerySelectField('Procedure', query_factory=procedure_factory, get_label='name', allow_blank=False)
    event_date = DateField('Scheduled Date', default=date.today, validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Schedule Event')

class CompleteEventForm(FlaskForm):
    completion_date = DateField('Actual Completion Date', default=date.today, validators=[DataRequired()])
    notes = TextAreaField('Completion Notes', validators=[Optional()])
    submit = SubmitField('Mark as Completed')

class CageNoteForm(FlaskForm):
    notes = TextAreaField('Cage Notes', validators=[Optional()])
    submit = SubmitField('Save Notes')

class BreedingPairForm(FlaskForm):
    male_animal = QuerySelectField('Male', query_factory=male_animal_factory, get_label='custom_id', allow_blank=False, validators=[DataRequired()])
    female_animal = QuerySelectField('Female', query_factory=female_animal_factory, get_label='custom_id', allow_blank=False, validators=[DataRequired()])
    start_date = DateField('Pairing Start Date', default=date.today, validators=[DataRequired()])
    submit = SubmitField('Create Breeding Pair')

class LitterForm(FlaskForm):
    birth_date = DateField('Litter Birth Date', default=date.today, validators=[DataRequired()])
    pup_count = IntegerField('Number of Pups', validators=[InputRequired(), NumberRange(min=1)])
    submit = SubmitField('Record Litter')

class TerminationForm(FlaskForm):
    termination_date = DateField('Date of Termination', default=date.today, validators=[DataRequired()])
    termination_reason = QuerySelectField('Reason', query_factory=termination_reason_factory, get_label='reason', allow_blank=True)
    ears_extracted = SelectField('Ears Extracted', choices=[('None', 'None'), ('Left', 'Left'), ('Right', 'Right'), ('Both', 'Both')], validators=[DataRequired()])
    submit = SubmitField('Confirm Termination')

class AnimalNoteForm(FlaskForm):
    general_notes = TextAreaField('General Notes', validators=[Optional()])
    submit = SubmitField('Save Notes')

class PanelForm(FlaskForm):
    name = StringField('Panel Name', validators=[DataRequired()])
    submit = SubmitField('Create Panel')

class ReagentForm(FlaskForm):
    name = StringField('Reagent Name', validators=[DataRequired()])
    dilution = StringField('Dilution', validators=[DataRequired()])
    submit = SubmitField('Add Reagent')
    
class RenamePanelForm(FlaskForm):
    name = StringField('New Panel Name', validators=[DataRequired()])
    submit = SubmitField('Rename')

class StudyForm(FlaskForm):
    name = StringField('Study Name', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[Optional()])
    submit = SubmitField('Save Changes')

class AddToStudyForm(FlaskForm):
    animals = QuerySelectMultipleField('Select Animals', query_factory=active_animal_factory, get_label='custom_id',
                                     widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())
    submit = SubmitField('Add Selected Animals')

class QuickAddToStudyForm(FlaskForm):
    study = QuerySelectField('Study', query_factory=study_factory, get_label='name', allow_blank=False)
    submit = SubmitField('Add')

# --- Context Processors and Before Request ---
@app.before_request
def before_request_func():
    g.study_form = StudyForm()
    g.rename_panel_form = RenamePanelForm()
    g.reagent_form = ReagentForm()
    g.simple_add_form = SimpleAddForm()
    g.panel_form = PanelForm()
    g.schedule_event_form = ScheduleEventForm()
    g.complete_event_form = CompleteEventForm()

# --- Routes ---
@app.route('/')
def index():
    active_cages_count = sum(1 for cage in Cage.query.all() if cage.is_active)
    active_animals_count = Animal.query.filter_by(is_terminated=False).count()
    active_breeding_pairs_count = BreedingPair.query.filter_by(is_active=True).count()
    ears_for_processing_count = Ear.query.filter(Ear.dissection_date == None).count()
    return render_template('index.html',
        active_cages=active_cages_count,
        active_animals=active_animals_count,
        active_pairs=active_breeding_pairs_count,
        ears_to_process=ears_for_processing_count
    )
    
@app.route('/calendar')
def calendar():
    events = AnimalEvent.query.filter(AnimalEvent.status.in_(['scheduled', 'completed'])).all()
    calendar_events = []
    for event in events:
        calendar_events.append({
            'title': f"{event.animal.custom_id}: {event.procedure.name}",
            'start': event.scheduled_date.isoformat(),
            'url': url_for('view_animals'),
            'color': '#3B82F6' if event.status == 'scheduled' else '#10B981' # blue-500 for scheduled, green-500 for completed
        })
    return render_template('calendar.html', calendar_events=calendar_events)


# --- Cage Routes ---
@app.route('/cages')
def view_cages():
    sort_by = request.args.get('sort_by', 'id')
    filter_by = request.args.get('filter', 'active')
    if sort_by == 'age':
        query = Cage.query.order_by(Cage.date_of_birth.asc())
    else:
        query = Cage.query.order_by(Cage.custom_id.asc())
    
    all_cages = query.all()
    if filter_by == 'active':
        cages = [c for c in all_cages if c.is_active]
    elif filter_by == 'inactive':
        cages = [c for c in all_cages if not c.is_active]
    else:
        cages = all_cages
    
    form = CageForm()
    return render_template('cages.html', cages=cages, form=form, sort_by=sort_by, filter_by=filter_by)

@app.route('/cage/<int:cage_id>', methods=['GET', 'POST'])
def cage_detail(cage_id):
    cage = Cage.query.get_or_404(cage_id)
    form = CageNoteForm(obj=cage)
    if form.validate_on_submit():
        cage.notes = form.notes.data
        db.session.commit()
        flash('Cage notes updated successfully.', 'success')
        return redirect(url_for('cage_detail', cage_id=cage.id))
        
    animals = cage.animals.order_by('animal_number').all()
    
    return render_template('cage_detail.html', cage=cage, form=form, animals=animals, 
                           termination_form=TerminationForm(), quick_add_form=QuickAddToStudyForm(), note_form=AnimalNoteForm())

@app.route('/cages/new', methods=['POST'])
def add_cage():
    form = CageForm()
    if form.validate_on_submit():
        new_cage = Cage(
            custom_id=form.custom_id.data,
            species=form.species.data,
            source=form.source.data,
            sex=form.sex.data,
            date_of_birth=form.date_of_birth.data,
            notes=form.notes.data
        )
        db.session.add(new_cage)
        db.session.commit()

        for i in range(form.number_of_animals.data):
            animal = Animal(
                cage_id=new_cage.id, 
                animal_number=i + 1,
                custom_id=f"{new_cage.custom_id}-{i+1}"
            )
            db.session.add(animal)
        
        db.session.commit()
        flash(f'Cage {new_cage.custom_id} with {form.number_of_animals.data} animals created.', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", 'danger')
    return redirect(url_for('view_cages'))

# --- Animal Routes ---
@app.route('/animals')
def view_animals():
    sort_by = request.args.get('sort_by', 'id')
    event_filter = request.args.get('event_filter', 'all')
    status_filter = request.args.get('status_filter', 'active')
    procedure_filter = request.args.get('procedure_filter', 'all')
    study_filter = request.args.get('study_filter', 'all')
    
    query = Animal.query.join(Cage)

    if status_filter == 'active':
        query = query.filter(Animal.is_terminated==False)
    elif status_filter == 'terminated':
        query = query.filter(Animal.is_terminated==True)
    
    if procedure_filter != 'all':
        query = query.join(Animal.events).filter(AnimalEvent.procedure_id == int(procedure_filter))

    if study_filter != 'all':
        query = query.join(Animal.studies).filter(Study.id == int(study_filter))

    animals = query.all()
    
    if sort_by == 'age':
        animals.sort(key=lambda a: a.cage.age_in_days)
    elif sort_by == 'event_date':
        animals.sort(key=lambda a: a.last_event_date, reverse=True)
    else:
        animals.sort(key=lambda a: a.custom_id)

    if event_filter == 'events':
        animals = [a for a in animals if a.has_events]
    elif event_filter == 'no_events':
        animals = [a for a in animals if not a.has_events]

    return render_template('animals.html', animals=animals, 
                           termination_form=TerminationForm(), note_form=AnimalNoteForm(), 
                           quick_add_form=QuickAddToStudyForm(),
                           sort_by=sort_by, event_filter=event_filter, status_filter=status_filter,
                           procedure_filter=procedure_filter, study_filter=study_filter,
                           procedures=Procedure.query.all(), studies=Study.query.all(), schedule_event_form=ScheduleEventForm())

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
    
@app.route('/animal/unterminate/<int:animal_id>', methods=['POST'])
def unterminate_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    animal.is_terminated = False
    animal.termination_date = None
    animal.termination_reason_id = None
    animal.ears_extracted = 'None'
    
    Ear.query.filter_by(animal_id=animal.id).delete()
    
    db.session.commit()
    flash(f'Termination for animal {animal.custom_id} has been reversed.', 'success')
    return redirect(request.referrer or url_for('view_animals'))

@app.route('/animals/terminate/<int:animal_id>', methods=['POST'])
def terminate_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = TerminationForm()
    if form.validate_on_submit():
        animal.is_terminated = True
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
    return redirect(url_for('view_animals'))

@app.route('/animal/schedule_event/<int:animal_id>', methods=['POST'])
def schedule_event(animal_id):
    form = ScheduleEventForm()
    if form.validate_on_submit():
        event = AnimalEvent(
            animal_id=animal_id,
            procedure_id=form.procedure.data.id,
            scheduled_date=form.event_date.data,
            notes=form.notes.data,
            status='scheduled'
        )
        db.session.add(event)
        db.session.commit()
        flash('Event scheduled successfully.', 'success')
    else:
        flash('Error scheduling event.', 'danger')
    return redirect(request.referrer or url_for('view_animals'))

@app.route('/event/complete/<int:event_id>', methods=['POST'])
def complete_event(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    form = CompleteEventForm()
    if form.validate_on_submit():
        event.status = 'completed'
        event.completion_date = form.completion_date.data
        if form.notes.data:
            event.notes = form.notes.data
        db.session.commit()
        flash(f'Event "{event.procedure.name}" for animal {event.animal.custom_id} marked as complete.', 'success')
    else:
        flash('Error completing event.', 'danger')
    return redirect(request.referrer or url_for('view_animals'))

@app.route('/animal/note/<int:animal_id>', methods=['POST'])
def save_animal_note(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = AnimalNoteForm()
    if form.validate_on_submit():
        animal.general_notes = form.general_notes.data
        db.session.commit()
        flash(f'Notes for animal {animal.custom_id} updated.', 'success')
    return redirect(url_for('view_animals'))

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
    cages = Cage.query.filter_by(breeding_pair_id=pair.id).all()
    animal_ids = [animal.id for cage in cages for animal in cage.animals]
    animals = Animal.query.filter(Animal.id.in_(animal_ids)).join(Cage).order_by(Cage.date_of_birth, Animal.id).all()
    return render_template('breeding_pair_detail.html', pair=pair, animals=animals)

@app.route('/breeding/new', methods=['POST'])
def add_breeding_pair():
    form = BreedingPairForm()
    if form.validate_on_submit():
        if form.male_animal.data.cage.sex != 'Male' or form.female_animal.data.cage.sex != 'Female':
            flash('Selected animals must be from designated Male and Female cages.', 'danger')
            return redirect(url_for('view_breeding_pairs'))
        if form.male_animal.data.cage.species != form.female_animal.data.cage.species:
            flash('Male and female must be of the same species.', 'danger')
            return redirect(url_for('view_breeding_pairs'))
        pair = BreedingPair(male_animal_id=form.male_animal.data.id, female_animal_id=form.female_animal.data.id, start_date=form.start_date.data)
        db.session.add(pair)
        db.session.commit()
        flash('New breeding pair created successfully.', 'success')
    else:
        flash('Error creating breeding pair.', 'danger')
    return redirect(url_for('view_breeding_pairs'))

@app.route('/breeding/litter/<int:pair_id>', methods=['POST'])
def add_litter(pair_id):
    pair = BreedingPair.query.get_or_404(pair_id)
    form = LitterForm()
    if form.validate_on_submit():
        litter = Litter(breeding_pair_id=pair.id, birth_date=form.birth_date.data, pup_count=form.pup_count.data)
        db.session.add(litter)
        db.session.commit()
        flash(f'Litter recorded for breeding pair #{pair.id}.', 'success')
    else:
        flash('Error recording litter.', 'danger')
    return redirect(url_for('view_breeding_pairs'))

@app.route('/breeding/wean/<int:litter_id>', methods=['GET', 'POST'])
def wean_litter(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    if request.method == 'POST':
        counts = request.form.getlist('counts')
        sexes = request.form.getlist('sexes')
        species = litter.breeding_pair.male.cage.species
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
                    animal = Animal(cage_id=new_cage.id, animal_number=j + 1, custom_id=f"{new_cage.custom_id}-{j+1}")
                    db.session.add(animal)
                cages_created += 1
        if cages_created > 0:
            litter.is_weaned = True
            db.session.commit()
            flash(f'Litter weaned into {cages_created} new cages.', 'success')
        else:
            flash('No pups were weaned as no counts were provided.', 'warning')
        return redirect(url_for('view_breeding_pairs'))
    return render_template('wean_litter.html', litter=litter)

@app.route('/breeding/deactivate/<int:pair_id>', methods=['POST'])
def deactivate_pair(pair_id):
    pair = BreedingPair.query.get_or_404(pair_id)
    pair.is_active = False
    db.session.commit()
    flash(f'Breeding pair #{pair.id} deactivated.', 'info')
    return redirect(url_for('view_breeding_pairs'))

@app.route('/breeding/reactivate/<int:pair_id>', methods=['POST'])
def reactivate_pair(pair_id):
    pair = BreedingPair.query.get_or_404(pair_id)
    pair.is_active = True
    db.session.commit()
    flash(f'Breeding pair #{pair.id} reactivated.', 'success')
    return redirect(url_for('view_breeding_pairs'))

# --- Histology Routes ---
@app.route('/histology')
def view_histology():
    dissected_filter = request.args.get('dissected_filter', 'all')
    labeled_filter = request.args.get('labeled_filter', 'all')
    
    query = Ear.query
    
    if dissected_filter == 'dissected':
        query = query.filter(Ear.dissection_date != None)
    elif dissected_filter == 'not_dissected':
        query = query.filter(Ear.dissection_date == None)
        
    if labeled_filter == 'labeled':
        query = query.filter(Ear.panel_id != None)
    elif labeled_filter == 'not_labeled':
        query = query.filter(Ear.panel_id == None)
    
    ears = query.join(Animal).join(Cage).order_by(Ear.id.desc()).all()
    panels = ImmunolabelingPanel.query.all()
    return render_template('histology.html', ears=ears, panels=panels, 
                           dissected_filter=dissected_filter, labeled_filter=labeled_filter)

@app.route('/histology/update/<int:ear_id>', methods=['POST'])
def update_ear(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    cp_date_str = request.form.get('cryoprotection_date')
    ear.cryoprotection_date = datetime.strptime(cp_date_str, '%Y-%m-%d').date() if cp_date_str else None
    ds_date_str = request.form.get('dissection_date')
    ear.dissection_date = datetime.strptime(ds_date_str, '%Y-%m-%d').date() if ds_date_str else None
    panel_id = request.form.get('panel_id')
    ear.panel_id = int(panel_id) if panel_id and panel_id != 'None' else None
    db.session.commit()
    flash(f'Ear #{ear.id} ({ear.animal.custom_id} - {ear.side}) updated.', 'success')
    return redirect(url_for('view_histology'))

# --- Studies Routes ---
@app.route('/studies')
def view_studies():
    studies = Study.query.all()
    return render_template('studies.html', studies=studies)

@app.route('/studies/new', methods=['POST'])
def add_study():
    form = g.study_form
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
    add_form.animals.query = Animal.query.filter(Animal.is_terminated==False, ~Animal.studies.any(id=study.id))

    if edit_form.submit.data and edit_form.validate_on_submit():
        if edit_form.name.data != study.name and Study.query.filter_by(name=edit_form.name.data).first():
            flash('A study with this name already exists.', 'danger')
        else:
            study.name = edit_form.name.data
            study.description = edit_form.description.data
            db.session.commit()
            flash(f'Study "{study.name}" has been updated.', 'success')
        return redirect(url_for('study_detail', study_id=study.id))
        
    return render_template('study_detail.html', study=study, edit_form=edit_form, add_form=add_form)

@app.route('/study/<int:study_id>/add_animals', methods=['POST'])
def add_to_study(study_id):
    study = Study.query.get_or_404(study_id)
    form = AddToStudyForm()
    form.animals.query = Animal.query.filter(Animal.is_terminated==False, ~Animal.studies.any(id=study.id))
    if form.validate_on_submit():
        for animal in form.animals.data:
            study.animals.append(animal)
        db.session.commit()
        flash(f'{len(form.animals.data)} animals added to study "{study.name}".', 'success')
    return redirect(url_for('study_detail', study_id=study.id))

@app.route('/study/<int:study_id>/remove/<int:animal_id>', methods=['POST'])
def remove_from_study(study_id, animal_id):
    study = Study.query.get_or_404(study_id)
    animal = Animal.query.get_or_404(animal_id)
    if animal in study.animals.all():
        study.animals.remove(animal)
        db.session.commit()
        flash(f'Animal {animal.custom_id} removed from study.', 'success')
    return redirect(url_for('study_detail', study_id=study.id))
    
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
@app.route('/settings')
def settings():
    return render_template('settings.html', 
                           species=Species.query.all(), 
                           sources=Source.query.all(), 
                           procedures=Procedure.query.all(),
                           termination_reasons=TerminationReason.query.all(),
                           panels=ImmunolabelingPanel.query.all())

@app.route('/settings/add/<item_type>', methods=['POST'])
def add_setting(item_type):
    form = g.simple_add_form
    if form.validate_on_submit():
        field_name = 'reason' if item_type == 'termination_reason' else 'name'
        Model = {'species': Species, 'source': Source, 'procedure': Procedure, 'termination_reason': TerminationReason}.get(item_type)
        
        if Model and not Model.query.filter(getattr(Model, field_name) == form.name.data).first():
            item = Model(**{field_name: form.name.data})
            db.session.add(item)
            db.session.commit()
            flash(f'{item_type.replace("_", " ").title()} "{form.name.data}" added.', 'success')
        else:
            flash(f'Error adding {item_type.replace("_", " ")}. It might already exist.', 'danger')
    return redirect(url_for('settings'))

@app.route('/settings/delete/<item_type>/<int:item_id>', methods=['POST'])
def delete_setting(item_type, item_id):
    Model = {'species': Species, 'source': Source, 'procedure': Procedure, 'termination_reason': TerminationReason}.get(item_type)
    item = Model.query.get_or_404(item_id)
    field_name = 'reason' if item_type == 'termination_reason' else 'name'
    
    if (item_type == 'species' and item.cages) or \
       (item_type == 'source' and item.cages) or \
       (item_type == 'procedure' and item.events) or \
       (item_type == 'termination_reason' and item.animals):
        flash(f'Cannot delete "{getattr(item, field_name)}" because it is currently in use.', 'danger')
        return redirect(url_for('settings'))

    db.session.delete(item)
    db.session.commit()
    flash(f'{item_type.replace("_", " ").title()} deleted.', 'success')
    return redirect(url_for('settings'))

@app.route('/settings/panel/new', methods=['POST'])
def add_panel():
    form = g.panel_form
    if form.validate_on_submit():
        if not ImmunolabelingPanel.query.filter_by(name=form.name.data).first():
            panel = ImmunolabelingPanel(name=form.name.data)
            db.session.add(panel)
            db.session.commit()
            flash(f'Panel "{panel.name}" created.', 'success')
        else:
            flash('A panel with this name already exists.', 'danger')
    return redirect(url_for('settings'))

@app.route('/settings/panel/rename/<int:panel_id>', methods=['POST'])
def rename_panel(panel_id):
    panel = ImmunolabelingPanel.query.get_or_404(panel_id)
    form = g.rename_panel_form
    if form.validate_on_submit():
        new_name = form.name.data
        if new_name != panel.name and not ImmunolabelingPanel.query.filter_by(name=new_name).first():
            panel.name = new_name
            db.session.commit()
            flash('Panel renamed successfully.', 'success')
        else:
            flash('Panel name already exists or is unchanged.', 'danger')
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
    form = g.reagent_form
    panel = ImmunolabelingPanel.query.get_or_404(panel_id)
    if form.validate_on_submit():
        reagent = Reagent(name=form.name.data, dilution=form.dilution.data, panel_id=panel.id)
        db.session.add(reagent)
        db.session.commit()
        flash(f'Reagent "{reagent.name}" added to panel "{panel.name}".', 'success')
    else:
        flash('Could not add reagent. Please check the form.', 'danger')
    return redirect(url_for('settings'))

if __name__ == '__main__':
    app.run(debug=True)
