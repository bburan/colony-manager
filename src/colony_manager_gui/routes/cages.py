from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from colony_manager.models import Cage, Animal
from .. import db
from ..forms import CageForm, NoteForm, TerminationForm, QuickAddToStudyForm
from .util import flash_form_errors  # Importing the new utility

cages_bp = Blueprint('cages', __name__)


def _attach_cage_animals(cages):
    """Bulk-load each cage's animals (with source) and stash on ``_cached_animals``.

    The cages-list template touches ``cage.animals.count()``,
    ``cage.animals.filter_by(termination_date=None).count()``,
    ``cage.sex_symbol``, ``cage.age_display(...)``, and
    ``cage.source_display`` per row — every one of those would issue its
    own query against the dynamic ``animals`` relationship. This helper
    fetches every relevant animal in a single query and lets the
    cache-aware ``Cage`` properties iterate the in-memory list.
    """
    if not cages:
        return
    cage_ids = [c.id for c in cages]
    animals = Animal.query.options(joinedload(Animal.source)) \
                          .filter(Animal.cage_id.in_(cage_ids)).all()
    by_cage = {cid: [] for cid in cage_ids}
    for a in animals:
        by_cage.setdefault(a.cage_id, []).append(a)
    for c in cages:
        c._cached_animals = by_cage.get(c.id, [])


@cages_bp.route('/')
def list_cages():
    species_id = int(session.get('selected_species', -1))
    base_query = Cage.query.options(joinedload(Cage.species))
    if species_id != -1:
        query = base_query.filter(Cage.species_id==species_id)
    else:
        query = base_query

    sort_by = request.args.get('sort_by', 'custom_id')
    if sort_by == 'custom_id':
        cages = query.order_by(Cage.custom_id).all()
    elif sort_by == 'age':
        cages = query \
            .outerjoin(Cage.animals) \
            .group_by(Cage.id) \
            .order_by(func.min(Animal.dob).desc()) \
            .all()

    _attach_cage_animals(cages)

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
