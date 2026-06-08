"""Shared query factories, widgets, and cross-blueprint forms.

Everything here is imported by at least two distinct blueprint form
modules or route files.  Blueprint-specific forms live in their own
sibling modules.
"""
from datetime import date

from flask_wtf import FlaskForm
from flask_wtf.file import MultipleFileField
from markupsafe import Markup
from wtforms import DateField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Optional
from wtforms_sqlalchemy.fields import QuerySelectField

from colony_manager.models import (
    Animal, AnimalProcedure, AnimalProcedureTarget, Cage,
    ConfocalImageType, ImmunolabelingPanel, Source, Species, Study,
    TerminationReason,
)

from .. import db


# ---------------------------------------------------------------------------
# Query-factory helpers
# ---------------------------------------------------------------------------

def order_by(model, attr='name'):
    """Return a zero-arg callable for WTForms-SQLAlchemy QuerySelectField."""
    return lambda: db.session.query(model).order_by(attr)


species_factory                 = order_by(Species)
source_factory                  = order_by(Source)
study_factory                   = order_by(Study)
cage_factory                    = order_by(Cage, 'custom_id')
animal_procedure_factory        = order_by(AnimalProcedure)
animal_procedure_target_factory = order_by(AnimalProcedureTarget)
panel_factory                   = order_by(ImmunolabelingPanel)
termination_reason_factory      = order_by(TerminationReason)
confocal_image_type_factory     = order_by(ConfocalImageType)


def male_animal_factory():
    return (db.session.query(Animal)
            .filter(Animal.terminated == False,  # noqa: E712
                    Animal.sex == 'male')
            .order_by(Animal.id))


def female_animal_factory():
    return (db.session.query(Animal)
            .filter(Animal.terminated == False,  # noqa: E712
                    Animal.sex == 'female')
            .order_by(Animal.id))


def active_animal_factory():
    return db.session.query(Animal).filter(
        Animal.terminated == False  # noqa: E712
    )


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class ButtonGroupWidget:
    """Renders a SelectMultipleField as a Bootstrap button-group checkbox row."""

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


# ---------------------------------------------------------------------------
# Shared / cross-blueprint forms
# ---------------------------------------------------------------------------

class NoteForm(FlaskForm):
    notes = TextAreaField('Notes', validators=[Optional()])


class CSRFOnlyForm(FlaskForm):
    """No fields — validates only the CSRF token on simple POST actions."""
    pass


class UploadFilesForm(FlaskForm):
    """User-driven file upload from an entity (Animal / Ear / ...) detail page.

    ``targets`` and ``file_notes`` are intentionally NOT WTForms fields — see
    the docstring in the original forms.py for the rationale.
    """
    datatype = SelectField('Type', coerce=int, validators=[DataRequired()])
    location = SelectField('Location', coerce=int, validators=[DataRequired()])
    date = DateField('Date', default=date.today, validators=[DataRequired()])
    files = MultipleFileField('Files')


class QuickAddToStudyForm(FlaskForm):
    study = QuerySelectField(
        'Study', query_factory=study_factory, get_label='name', allow_blank=False,
    )


class TerminationForm(FlaskForm):
    termination_date = DateField(
        'Date of Termination', default=date.today, validators=[Optional()],
    )
    termination_reason = QuerySelectField(
        'Reason', query_factory=termination_reason_factory,
        get_label='name', allow_blank=True,
    )
    ears_extracted = SelectField(
        'Ears Extracted',
        choices=[('None', 'None'), ('Left', 'Left'), ('Right', 'Right'), ('Both', 'Both')],
        validators=[DataRequired()],
    )


# ---------------------------------------------------------------------------
# Factory: dynamically-built nested form
# ---------------------------------------------------------------------------

def create_nested_form(model_class, label='Parent'):
    """Return a FlaskForm subclass with a QuerySelectField for *model_class*
    as the parent plus a name field, excluding descendants when editing."""

    class NestedAddForm(FlaskForm):
        parent = QuerySelectField(
            label,
            query_factory=lambda: model_class.get_ordered(db.session),
            get_label='display_name',
            allow_blank=True,
            blank_text='-- No Parent --',
        )
        name = StringField('Name', validators=[DataRequired()])

        def __init__(self, *args, obj=None, **kwargs):
            super().__init__(*args, obj=obj, **kwargs)
            obj_id = getattr(obj, 'id', None)
            if obj_id is not None:
                excluded = model_class.descendant_ids(db.session, obj_id)
                self.parent.query_factory = lambda: [
                    item for item in model_class.get_ordered(db.session)
                    if item.id not in excluded
                ]

    return NestedAddForm


# ---------------------------------------------------------------------------
# Helpers for disabling / making fields read-only
# ---------------------------------------------------------------------------

def mark_disabled(form, field_name=None):
    if field_name is not None:
        field = getattr(form, field_name)
        if field.render_kw is None:
            field.render_kw = {}
        field.render_kw['disabled'] = True
        return
    for field in form:
        if field.type not in ['CSRFTokenField', 'SubmitField']:
            if field.render_kw is None:
                field.render_kw = {}
            field.render_kw['disabled'] = True
        if field.type == 'FieldList':
            for item in field:
                mark_disabled(item)


def mark_readonly(form, field_name=None):
    if field_name is not None:
        field = getattr(form, field_name)
        if field.render_kw is None:
            field.render_kw = {}
        field.render_kw['readonly'] = True
        return
    for field in form:
        if field.type not in ['CSRFTokenField', 'SubmitField']:
            if field.render_kw is None:
                field.render_kw = {}
            field.render_kw['readonly'] = True
        if field.type == 'FieldList':
            for item in field:
                mark_readonly(item)
