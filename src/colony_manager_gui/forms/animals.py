from datetime import date, datetime

from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import (
    BooleanField, DateField, FieldList, FloatField, Form, FormField,
    HiddenField, IntegerField, SelectField, StringField, TextAreaField,
    TimeField,
)
from wtforms.validators import (
    DataRequired, InputRequired, NumberRange, Optional, ValidationError,
)
from wtforms_sqlalchemy.fields import QuerySelectField, QuerySelectMultipleField

from colony_manager import models
from colony_manager.models import Animal, AnimalProcedure

from .. import db
from .common import (
    animal_procedure_target_factory, cage_factory, source_factory,
    species_factory, termination_reason_factory,
)


class AnimalCustomIDForm(FlaskForm):
    custom_id = StringField('Animal ID', validators=[DataRequired()])

    def __init__(self, *args, obj=None, **kwargs):
        super().__init__(*args, obj=obj, **kwargs)
        self.initial_custom_id = obj.custom_id if obj is not None else None

    def validate_custom_id(self, field):
        if self.initial_custom_id != field.data:
            if db.session.scalars(
                select(Animal).where(Animal.custom_id == field.data)
            ).first():
                raise ValidationError(f'Animal ID "{field.data}" already exists.')


class AnimalForm(AnimalCustomIDForm):
    custom_id = StringField('Animal ID', validators=[Optional()])
    cage = QuerySelectField('Cage', query_factory=cage_factory, get_label='custom_id')
    species = QuerySelectField('Species', query_factory=species_factory, get_label='name')
    sex = SelectField(
        'Sex', choices=[('male', 'male'), ('female', 'female')],
        validators=[DataRequired()],
    )
    dob = DateField('Date of Birth', default=date.today, validators=[DataRequired()])
    source = QuerySelectField(
        'Source', query_factory=source_factory, get_label='name', allow_blank=True,
    )
    notes = TextAreaField('Notes', validators=[Optional()])
    terminated = BooleanField('Terminated')
    termination_date = DateField('Termination date', validators=[Optional()])
    termination_reason = QuerySelectField(
        'Termination reason', query_factory=termination_reason_factory,
        get_label='name', validators=[Optional()],
    )
    tags = QuerySelectMultipleField(
        'Tags',
        query_factory=lambda: models.AnimalTag.get_ordered(db.session),
        get_label='display_name',
    )


class AnimalEventForm(FlaskForm):
    """Form for creating a new animal event."""
    procedure = QuerySelectField(
        'Procedure',
        query_factory=lambda: AnimalProcedure.get_ordered(db.session),
        get_label='display_name',
        allow_blank=False,
    )
    procedure_target = QuerySelectField(
        'Target', query_factory=animal_procedure_target_factory,
        get_label='name', allow_blank=False,
    )
    side = SelectField(
        'Side',
        choices=[('', '— side —'), ('Left', 'Left'), ('Right', 'Right'), ('Both', 'Both')],
        validators=[Optional()],
        filters=[lambda v: v or None],
    )
    date = DateField('Date', default=date.today, validators=[DataRequired()])
    action = HiddenField('action', default='completed')
    notes = TextAreaField('Notes', validators=[Optional()])
    tags = QuerySelectMultipleField(
        'Tags',
        query_factory=lambda: models.AnimalEventTag.get_ordered(db.session),
        get_label='display_name',
    )


class AnimalEventEditForm(FlaskForm):
    """Form for editing an existing animal event with full date control."""
    procedure = QuerySelectField(
        'Procedure',
        query_factory=lambda: AnimalProcedure.get_ordered(db.session),
        get_label='display_name',
        allow_blank=False,
    )
    procedure_target = QuerySelectField(
        'Target', query_factory=animal_procedure_target_factory,
        get_label='name', allow_blank=False,
    )
    side = SelectField(
        'Side',
        choices=[('', '— side —'), ('Left', 'Left'), ('Right', 'Right')],
        validators=[Optional()],
        filters=[lambda v: v or None],
    )
    scheduled_date = DateField('Scheduled Date', default=date.today, validators=[DataRequired()])
    completion_date = DateField('Completed Date', default=None, validators=[Optional()])
    completion_time = TimeField('Completed Time', default=None, validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])
    tags = QuerySelectMultipleField(
        'Tags',
        query_factory=lambda: models.AnimalEventTag.get_ordered(db.session),
        get_label='display_name',
    )


def _now_minute():
    """Current wall-clock time with seconds zeroed, for dosage TimeField default."""
    return datetime.now().time().replace(second=0, microsecond=0)


class DosageCalculateForm(FlaskForm):
    """Pick a protocol + weight on the animal page; result computed server-side."""
    protocol = QuerySelectField(
        'Protocol',
        query_factory=lambda: db.session.query(models.DosageProtocol).order_by(
            models.DosageProtocol.name
        ),
        get_label='name',
        allow_blank=False,
        validators=[DataRequired()],
    )
    weight_g = FloatField('Weight (g)', validators=[DataRequired(), NumberRange(min=0.01)])
    date = DateField('Date', default=date.today, validators=[DataRequired()])
    time = TimeField('Time', default=_now_minute, validators=[DataRequired()])


class FeedEntryForm(FlaskForm):
    feed_id = HiddenField()
    feed_name = StringField('Feed Type', render_kw={'readonly': True})
    feed_weight = HiddenField('Feed Weight')
    quantity = FloatField('Quantity', default=0, validators=[Optional()])


class DailyLogForm(FlaskForm):
    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()], default=date.today())
    weight = FloatField('Weight', validators=[Optional()])
    notes = StringField('Notes', validators=[Optional()])
    feedings = FieldList(FormField(FeedEntryForm))
    baseline = BooleanField('Baseline Weight?')
    current_baseline = HiddenField()
    current_baseline_pct = FloatField(
        '% Baseline', render_kw={'disabled': True}, validators=[Optional()],
    )
