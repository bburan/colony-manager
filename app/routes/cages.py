from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import func
from app import db
from app.models import Cage, Animal
from app.forms import CageForm, NoteForm, TerminationForm, QuickAddToStudyForm
from app.routes.util import flash_form_errors  # Importing the new utility

cages_bp = Blueprint('cages', __name__)


@cages_bp.route('/')
def list_cages():
    sort_by = request.args.get('sort_by', 'custom_id')
    if sort_by == 'custom_id':
        cages = Cage.query.order_by(Cage.custom_id).all()
    elif sort_by == 'age':
        cages = Cage.query \
            .outerjoin(Cage.animals) \
            .group_by(Cage.id) \
            .order_by(func.min(Animal.dob).desc()) \
            .all()

    status_filter = request.args.get('status_filter', 'active')
    if status_filter == 'active':
        cages = [c for c in cages if c.is_active]
    elif status_filter == 'inactive':
        cages = [c for c in cages if not c.is_active]

    filters = {
        'age_unit': request.args.get('age_unit', 'day'),
        'status_filter': status_filter,
        'sort_by': sort_by,
    }

    return render_template('cages.html', cages=cages, filters=filters)


@cages_bp.route('/<int:cage_id>')
def view_cage(cage_id):
    cage = Cage.query.get_or_404(cage_id)
    return render_template('view_cage.html', cage=cage)


@cages_bp.route('/create', methods=['POST'])
def create_cage():
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
        return redirect(url_for('cages.list_cages'))
    else:
        flash_form_errors(form, "Could not create cage")
    return redirect(request.referrer or url_for('cages.list_cages'))


@cages_bp.route('/<int:cage_id>/update', methods=['POST'])
def update_cage(cage_id):
    cage = Cage.query.get_or_404(cage_id)
    form = CageForm()
    if form.validate_on_submit():
        form.populate_obj(cage)
        db.session.commit()
        flash(f'Cage {cage.custom_id} updated.', 'success')
    else:
        flash_form_errors(form, title="Could not update notes")
    return redirect(request.referrer or url_for('cages.view_cage', cage_id=cage.id))


@cages_bp.route('/<int:cage_id>/update_note', methods=['POST'])
def update_cage_note(cage_id):
    cage = Cage.query.get_or_404(cage_id)
    form = NoteForm()
    if form.validate_on_submit():
        form.populate_obj(cage)
        db.session.commit()
        flash(f'Cage {cage.custom_id} updated.', 'success')
    else:
        flash_form_errors(form, title="Could not update notes")
    return redirect(request.referrer or url_for('cages.view_cage', cage_id=cage.id))


# --- Modal Routes ---
@cages_bp.route('/create_modal')
def create_cage_modal():
    form = CageForm()
    return render_template('partials/form_modal.html', form=form, item=None,
                           label='Add Cage', submit_url=url_for('cages.create_cage'))

@cages_bp.route('/<int:cage_id>/edit_note_modal')
def update_cage_note_modal(cage_id):
    cage = Cage.query.get_or_404(cage_id)
    form = NoteForm(obj=cage)
    return render_template(
        'partials/form_modal.html',
        form=form,
        item=cage,
        label=f'Edit note for {cage.custom_id}',
        submit_url=url_for('cages.update_cage_note', cage_id=cage.id)
    )