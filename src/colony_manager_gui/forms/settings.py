"""Forms for the settings / admin area.

Covers DataType configuration, DataLocation, generic name-only forms
used in the settings registry, and admin-only dosage-protocol creation.
"""
from datetime import date, datetime

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField, DateField, FloatField, SelectField, StringField,
    TextAreaField, TimeField,
)
from wtforms.validators import DataRequired, Optional, NumberRange, ValidationError
from wtforms_sqlalchemy.fields import QuerySelectField

from colony_manager.models import AnimalProcedure

from .. import db
from .common import animal_procedure_target_factory


# ---------------------------------------------------------------------------
# Generic / reusable settings forms
# ---------------------------------------------------------------------------

class SimpleAddForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])


class SimpleAddWithDescriptionForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    description = StringField('Description', validators=[Optional()])


class ProcedureTargetForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    description = StringField('Description', validators=[Optional()])
    requires_side = BooleanField('Requires side?')


class FeedForm(FlaskForm):
    name = StringField('Feed Name', validators=[DataRequired()])
    weight = FloatField('Feed Weight', validators=[DataRequired()])


# ---------------------------------------------------------------------------
# DataType forms
# ---------------------------------------------------------------------------

def _description_class_choices():
    from colony_manager.datatypes import get_allowed_description_classes
    return [('', '-- None --')] + [
        (key, key) for key in get_allowed_description_classes()
    ]


class DataTypeForm(FlaskForm):
    """Base fields shared by every DataType subclass."""
    name = StringField('Name', validators=[DataRequired()])
    description = StringField('Description', validators=[Optional()])
    description_class = SelectField(
        'Description Class',
        choices=_description_class_choices,
        validators=[Optional()],
        filters=[lambda v: v or None],
    )
    is_folder = BooleanField('Is Folder?')

    def __init__(self, *args, obj=None, **kwargs):
        super().__init__(*args, obj=obj, **kwargs)
        existing = getattr(obj, 'description_class', None)
        if existing and existing not in dict(self.description_class.choices):
            self.description_class.choices = (
                self.description_class.choices
                + [(existing, f'{existing} (unregistered)')]
            )


class AnimalEventDataTypeForm(DataTypeForm):
    default_procedure = QuerySelectField(
        'Default Procedure',
        query_factory=lambda: AnimalProcedure.get_ordered(db.session),
        get_label='display_name',
        allow_blank=True,
        blank_text='-- None --',
    )
    default_procedure_target = QuerySelectField(
        'Default Procedure Target',
        query_factory=animal_procedure_target_factory,
        get_label='name',
        allow_blank=True,
        blank_text='-- None --',
    )
    auto_create = BooleanField('Auto-create event for unmatched files?')


class ConfocalImageDataTypeForm(DataTypeForm):
    pass


class AnimalDataTypeForm(DataTypeForm):
    pass


class EarDataTypeForm(DataTypeForm):
    pass


DATATYPE_FORMS = {
    'animal_event':    AnimalEventDataTypeForm,
    'confocal_image':  ConfocalImageDataTypeForm,
    'animal':          AnimalDataTypeForm,
    'ear':             EarDataTypeForm,
}

DATATYPE_TARGET_LABELS = [
    ('animal_event',   'Animal Event'),
    ('confocal_image', 'Confocal Image'),
    ('animal',         'Animal'),
    ('ear',            'Ear'),
]


def datatype_form_for(target_type, *args, **kwargs):
    form_cls = DATATYPE_FORMS.get(target_type)
    if form_cls is None:
        raise ValueError(f'Unknown DataType target_type: {target_type!r}')
    return form_cls(*args, **kwargs)


class DataLocationForm(FlaskForm):
    base_path = StringField('Base Path', validators=[DataRequired()])


# ---------------------------------------------------------------------------
# Dosage protocol (admin-side creation)
# ---------------------------------------------------------------------------

class DosageProtocolForm(FlaskForm):
    """Top-level fields for a DosageProtocol.

    Drug rows are submitted as parallel ``drug_name`` / ``drug_dose`` /
    ``drug_concentration`` / ``drug_id`` arrays and parsed directly out of
    ``request.form`` by the route.
    """
    name = StringField('Name', validators=[DataRequired()])
    procedure = QuerySelectField(
        'Procedure',
        query_factory=lambda: AnimalProcedure.get_ordered(db.session),
        get_label='display_name',
        allow_blank=False,
        validators=[DataRequired()],
    )
    procedure_target = QuerySelectField(
        'Procedure Target',
        query_factory=animal_procedure_target_factory,
        get_label='name',
        allow_blank=False,
        validators=[DataRequired()],
    )
    notes = TextAreaField('Notes', validators=[Optional()])
