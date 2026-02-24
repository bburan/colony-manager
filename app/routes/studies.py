from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Study, Animal
from app.forms import StudyForm, AddToStudyForm, QuickAddToStudyForm, NoteForm
from app.routes.util import flash_form_errors

studies_bp = Blueprint('studies', __name__)


@studies_bp.route('/')
def list_studies():
    studies = Study.query.all()
    return render_template('studies.html', studies=studies)


@studies_bp.route('/<int:study_id>')
def view_study(study_id):
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
    study = Study.query.get_or_404(study_id)
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
    study = Study.query.get_or_404(study_id)
    form = AddToStudyForm()
    form.animals.query = Animal.query.all()
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
    study = Study.query.get_or_404(study_id)
    animal = Animal.query.get_or_404(animal_id)
    if animal in study.animals.all():
        study.animals.remove(animal)
        db.session.commit()
        flash(f'Animal {animal.custom_id} removed from study.', 'success')
    else:
        flash(f'Animal {animal.custom_id} not found in study.', 'danger')
    return redirect(request.referrer or url_for('studies.view_study', study_id=study.id))


@studies_bp.route('/add/<int:animal_id>', methods=['POST'])
def add_study_animal(animal_id):
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
    else:
        flash_form_errors(form, title="Failed to quick-add animal:")
    return redirect(request.referrer or url_for('animals.list_animals'))

# --- Modal Routes ---
@studies_bp.route('/create_modal')
def create_study_modal():
    form = StudyForm()
    return render_template('partials/form_modal.html', form=form, item=None,
                           label='Add Study', submit_url=url_for('studies.create_study'))

@studies_bp.route('/<int:study_id>/edit_modal')
def edit_study_modal(study_id):
    study = Study.query.get_or_404(study_id)
    form = StudyForm(obj=study)
    return render_template('partials/form_modal.html', form=form, item=study,
                           label=f'Edit Study {study.name}', submit_url=url_for('studies.update_study', study_id=study.id))