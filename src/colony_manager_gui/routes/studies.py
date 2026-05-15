from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import select

from colony_manager.models import Study, Animal
from .. import db
from ..forms import StudyForm, AddToStudyForm, QuickAddToStudyForm, NoteForm
from .util import flash_form_errors, render_modal

studies_bp = Blueprint('studies', __name__)


@studies_bp.route('/')
def list_studies():
    studies = db.session.scalars(select(Study)).all()
    return render_template('studies.html', studies=studies)


@studies_bp.route('/<int:study_id>')
def view_study(study_id):
    study = db.get_or_404(Study, study_id)
    edit_form = StudyForm(obj=study)
    add_form = AddToStudyForm()
    # WTForms-SQLAlchemy's QuerySelectField expects a Query object on
    # ``.query``, not a Select. Use the legacy ``db.session.query(...)``
    # form rather than ``select(...)``; it's not the global Model.query
    # monkey-patch we're removing, just SQLAlchemy's session-level
    # Query API which remains supported in 2.0.
    add_form.animals.query = db.session.query(Animal).filter(
        Animal.custom_id != None  # noqa: E711  (SQL IS NOT NULL needs ``!=``)
    )

    if edit_form.data and edit_form.validate_on_submit():
        name_collision = db.session.scalars(
            select(Study).where(Study.name == edit_form.name.data)
        ).first()
        if edit_form.name.data != study.name and name_collision:
            flash('A study with this name already exists.', 'danger')
        else:
            study.name = edit_form.name.data
            study.description = edit_form.description.data
            db.session.commit()
            flash(f'Study "{study.name}" has been updated.', 'success')
        return redirect(url_for('studies.view_study', study_id=study.id))

    if request.method == 'POST' and not edit_form.validate_on_submit():
        flash_form_errors(edit_form, title="Error updating study")

    return render_template('view_study.html', study=study)


@studies_bp.route('/create', methods=['POST'])
def create_study():
    form = StudyForm()
    if form.validate_on_submit():
        study = Study(name=form.name.data, description=form.description.data)
        db.session.add(study)
        db.session.commit()
        flash('Study created successfully.', 'success')
    else:
        flash_form_errors(form, title="Study create failed")
    return redirect(url_for('studies.list_studies'))


@studies_bp.route('/<int:study_id>/update', methods=['POST'])
def update_study(study_id):
    study = db.get_or_404(Study, study_id)
    form = StudyForm(obj=study)
    if form.validate_on_submit():
        form.populate_obj(study)
        db.session.commit()
        flash('Study updated successfully.', 'success')
    else:
        flash_form_errors(form, title="Study update failed")
    return redirect(request.referrer or url_for('studies.list_studies'))


@studies_bp.route('/<int:study_id>/animals/add', methods=['POST'])
def add_study_animals(study_id):
    study = db.get_or_404(Study, study_id)
    form = AddToStudyForm()
    # See view_study for why this uses db.session.query(...) instead
    # of select(...).
    form.animals.query = db.session.query(Animal)
    if form.validate_on_submit():
        for animal in form.animals.data:
            study.animals.append(animal)
        db.session.commit()
        flash(f'{len(form.animals.data)} animals added to study "{study.name}".', 'success')
    else:
        flash_form_errors(form, title="Failed to add animals")
    return redirect(request.referrer or url_for('studies.view_study', study_id=study.id))


@studies_bp.route('/<int:study_id>/animals/<int:animal_id>/delete', methods=['POST'])
def remove_study_animal(study_id, animal_id):
    study = db.get_or_404(Study, study_id)
    animal = db.get_or_404(Animal, animal_id)
    if animal in study.animals:
        study.animals.remove(animal)
        db.session.commit()
        flash(f'Animal {animal.custom_id} removed from study.', 'success')
    else:
        flash(f'Animal {animal.custom_id} not found in study.', 'danger')
    return redirect(request.referrer or url_for('studies.view_study', study_id=study.id))


@studies_bp.route('/bulk_assign', methods=['POST'])
def bulk_assign_animals():
    """Add a list of animals (by ID) to a study in one shot.

    Posted from the Animal Overview bulk-action bar: ``study_id`` plus
    repeated ``animal_ids`` fields.
    """
    try:
        study_id = int(request.form.get('study_id') or 0)
    except (TypeError, ValueError):
        study_id = 0
    animal_ids = request.form.getlist('animal_ids', type=int)

    if not study_id or not animal_ids:
        flash('Pick a study and at least one animal.', 'warning')
        return redirect(request.referrer or url_for('animals.list_animals'))

    study = db.get_or_404(Study, study_id)
    existing = {a.id for a in study.animals}
    animals = db.session.scalars(
        select(Animal).where(Animal.id.in_(animal_ids))
    ).all()

    added = 0
    for animal in animals:
        if animal.id in existing:
            continue
        study.animals.append(animal)
        added += 1
    db.session.commit()

    skipped = len(animals) - added
    if added and skipped:
        flash(f'Added {added} animals to "{study.name}" ({skipped} already in study).', 'success')
    elif added:
        flash(f'Added {added} animals to "{study.name}".', 'success')
    else:
        flash(f'All selected animals were already in "{study.name}".', 'info')
    return redirect(request.referrer or url_for('animals.list_animals'))


@studies_bp.route('/add/<int:animal_id>', methods=['POST'])
def add_study_animal(animal_id):
    animal = db.get_or_404(Animal, animal_id)
    form = QuickAddToStudyForm()
    if form.validate_on_submit():
        study = form.study.data
        if animal not in study.animals:
            study.animals.append(animal)
            db.session.commit()
            flash(f'Animal {animal.custom_id} added to study "{study.name}".', 'success')
        else:
            flash(f'Animal {animal.custom_id} is already in study "{study.name}".', 'warning')
    else:
        flash_form_errors(form, title="Failed to quick-add animal:")
    return redirect(request.referrer or url_for('animals.list_animals'))

# --- Modal Routes ---
@studies_bp.route('/create_modal')
def create_study_modal():
    return render_modal(StudyForm(), label='Add Study',
                        submit_url=url_for('studies.create_study'))


@studies_bp.route('/<int:study_id>/edit_modal')
def edit_study_modal(study_id):
    study = db.get_or_404(Study, study_id)
    return render_modal(StudyForm(obj=study), item=study,
                        label=f'Edit Study {study.name}',
                        submit_url=url_for('studies.update_study', study_id=study.id))
