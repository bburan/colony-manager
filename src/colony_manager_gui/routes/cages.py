from flask import Blueprint, render_template, request, redirect, url_for, flash, session, Response

from colony_manager.models import Cage, Animal
from .. import db
from ..forms.cages import CageForm, CageDetailsForm
from ..forms.common import NoteForm, QuickAddToStudyForm, TerminationForm
from .util import flash_form_errors, get_or_404, parse_target_age, render_modal
from ..services.cage_queries import get_filtered_cages, get_cage_filter_options

cages_bp = Blueprint('cages', __name__)


_CAGE_SORT_DIR_DEFAULTS = {
    'custom_id': 'asc',
    'age': 'asc',           # asc = youngest first ⇒ max(dob) desc
    'animal_count': 'desc',
    'active_count': 'desc',
}


@cages_bp.route('/')
def list_cages() -> Response | str:
    sort_by = request.args.get('sort_by', 'custom_id')
    sort_dir = request.args.get('sort_dir', '')
    if sort_dir not in ('asc', 'desc'):
        sort_dir = _CAGE_SORT_DIR_DEFAULTS.get(sort_by, 'asc')

    filters = {
        'sort_by': sort_by,
        'sort_dir': sort_dir,
        'status_filter': request.args.get('status_filter', 'active'),
        'sex_filter': request.args.get('sex_filter', 'all'),
        'source_id': request.args.get('source_id', 'all'),
        'occupancy_filter': request.args.get('occupancy_filter', 'all'),
        'notes_filter': request.args.get('notes_filter', 'all'),
        'tag_id': request.args.get('tag_id', 'all'),
        'procedure_id': request.args.get('procedure_id', 'all'),
        'target_age': request.args.get('target_age', ''),
        'species_id': int(session.get('selected_species', -1)),
    }

    cages = get_filtered_cages(db.session, filters)
    options = get_cage_filter_options(db.session)

    target_age, target_age_unit, target_age_error = parse_target_age(
        filters['target_age'])

    return render_template(
        'cages.html', cages=cages, filters=filters,
        target_age=target_age, target_age_unit=target_age_unit,
        target_age_error=target_age_error, **options,
    )


@cages_bp.route('/<int:cage_id>')
def view_cage(cage_id) -> Response | str:
    cage = get_or_404(Cage, cage_id)
    # Sort animals by custom_id with NULLs at the end. The previous
    # Jinja ``|sort(attribute='custom_id')`` filter raised TypeError on
    # any cage that held animals with no custom_id yet (e.g. before the
    # user assigned IDs from the cage detail page).
    animals = sorted(
        cage.animals,
        key=lambda a: (a.custom_id is None, a.custom_id or ''),
    )
    return render_template('view_cage.html', cage=cage, animals=animals)


@cages_bp.route('/create', methods=['POST'])
def create_cage() -> Response | str:
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
def update_cage(cage_id) -> Response | str:
    cage = get_or_404(Cage, cage_id)
    form = CageForm()
    if form.validate_on_submit():
        form.populate_obj(cage)
        db.session.commit()
        flash(f'Cage {cage.custom_id} updated.', 'success')
    else:
        flash_form_errors(form, title="Could not update notes")
    return redirect(request.referrer or url_for('cages.view_cage', cage_id=cage.id))


@cages_bp.route('/<int:cage_id>/update_details', methods=['POST'])
def update_cage_details(cage_id) -> Response | str:
    cage = get_or_404(Cage, cage_id)
    form = CageDetailsForm(obj=cage)
    if form.validate_on_submit():
        form.populate_obj(cage)
        db.session.commit()
        flash(f'Cage {cage.custom_id} updated.', 'success')
    else:
        flash_form_errors(form, title='Could not update cage')
    return redirect(request.referrer or url_for('cages.view_cage', cage_id=cage.id))


@cages_bp.route('/<int:cage_id>/update_note', methods=['POST'])
def update_cage_note(cage_id) -> Response | str:
    cage = get_or_404(Cage, cage_id)
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
def create_cage_modal() -> Response | str:
    return render_modal(CageForm(), label='Add Cage',
                        submit_url=url_for('cages.create_cage'))


@cages_bp.route('/<int:cage_id>/edit_details_modal')
def edit_cage_details_modal(cage_id) -> Response | str:
    cage = get_or_404(Cage, cage_id)
    return render_modal(CageDetailsForm(obj=cage), item=cage,
                        label=f'Edit {cage.custom_id}',
                        submit_url=url_for('cages.update_cage_details', cage_id=cage.id))


@cages_bp.route('/<int:cage_id>/edit_note_modal')
def update_cage_note_modal(cage_id) -> Response | str:
    cage = get_or_404(Cage, cage_id)
    return render_modal(NoteForm(obj=cage), item=cage,
                        label=f'Edit note for {cage.custom_id}',
                        submit_url=url_for('cages.update_cage_note', cage_id=cage.id))
