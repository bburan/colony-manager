from datetime import date
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, DateField, SelectField, SelectMultipleField, TextAreaField, FieldList, Form, FormField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional, ValidationError, Length
from wtforms.widgets import ListWidget, CheckboxInput
from wtforms_sqlalchemy.fields import QuerySelectField, QuerySelectMultipleField
from markupsafe import Markup

# Import models required for the form query factories
from app.models import (
    Species, Source, Study, Cage, AnimalProcedure, AnimalProcedureTarget,
    ImmunolabelingPanel, TerminationReason, Animal, ConfocalImageType, BreedingPair
)

# --- Query Factories ---
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
def active_animal_factory(): return Animal.query.filter_by(termination_date=None) # Note: Changed from is_terminated=False which didn't match model
def confocal_image_type_factory(): return ConfocalImageType.query.order_by('name')

# --- Widgets ---
class ButtonGroupWidget:
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

# --- Forms ---
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
        self.initial_custom_id = obj.custom_id if obj is not None else None

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

class AnimalEventDeleteForm(AnimalEventForm):
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
        self.initial_name = obj.name if obj is not None else None

    def validate_name(self, field):
        if self.initial_name != field.data:
            if Study.query.filter_by(name=field.data).first():
                raise ValidationError(f'Study "{field.data}" already exists.')

class AddToStudyForm(FlaskForm):
    animals = QuerySelectMultipleField('Select Animals', query_factory=active_animal_factory, get_label='custom_id', widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())

class QuickAddToStudyForm(FlaskForm):
    study = QuerySelectField('Study', query_factory=study_factory, get_label='name', allow_blank=False)

class ConfocalImageForm(FlaskForm):
    FREQUENCIES = [0.5, 0.7, 1, 1.4, 2, 2.8, 4, 5.6, 8, 11.2, 16, 22.6, 32, 45.2, 64]
    frequencies = SelectMultipleField(
        'Frequencies (kHz)',
        choices=[(str(f), str(f)) for f in FREQUENCIES],
        option_widget=CheckboxInput(),
        widget=ButtonGroupWidget(),
    )
    image_type = QuerySelectField('Image Type', query_factory=confocal_image_type_factory, get_label='name', validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])