from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload

from colony_manager.models import (
    Cage, Animal, AnimalEvent, AnimalProcedure, AnimalTag, Source,
)
from .. import db
from ..forms import CageForm, NoteForm, TerminationForm, QuickAddToStudyForm
from .util import flash_form_errors, render_modal

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
    animals = db.session.scalars(
        select(Animal)
        .options(joinedload(Animal.source))
        .where(Animal.cage_id.in_(cage_ids))
    ).all()
    by_cage = {cid: [] for cid in cage_ids}
    for a in animals:
        by_cage.setdefault(a.cage_id, []).append(a)
    for c in cages:
        c._cached_animals = by_cage.get(c.id, [])


_CAGE_SORT_DIR_DEFAULTS = {
    'custom_id': 'asc',
    'age': 'asc',           # asc = youngest first ⇒ max(dob) desc
    'animal_count': 'desc',
    'active_count': 'desc',
}


@cages_bp.route('/')
def list_cages():
    sort_by = request.args.get('sort_by', 'custom_id')
    sort_dir = request.args.get('sort_dir', '')
    if sort_dir not in ('asc', 'desc'):
        sort_dir = _CAGE_SORT_DIR_DEFAULTS.get(sort_by, 'asc')

    status_filter = request.args.get('status_filter', 'active')
    sex_filter = request.args.get('sex_filter', 'all')
    source_filter = request.args.get('source_id', 'all')
    occupancy_filter = request.args.get('occupancy_filter', 'all')
    notes_filter = request.args.get('notes_filter', 'all')
    tag_filter = request.args.get('tag_id', 'all')
    procedure_filter = request.args.get('procedure_id', 'all')
    age_unit = request.args.get('age_unit', 'day')

    stmt = select(Cage).options(joinedload(Cage.species))

    species_id = int(session.get('selected_species', -1))
    if species_id != -1:
        stmt = stmt.where(Cage.species_id == species_id)

    # Active = has at least one non-terminated animal. Inactive cages
    # include both terminated-only and empty cages, matching the prior
    # ``is_active`` semantics.
    if status_filter == 'active':
        stmt = stmt.where(Cage.animals.any(Animal.termination_date.is_(None)))
    elif status_filter == 'inactive':
        stmt = stmt.where(~Cage.animals.any(Animal.termination_date.is_(None)))

    if sex_filter in ('male', 'female'):
        # Cage matches if it has any animal of this sex AND no animal of
        # the other sex — i.e. the cage is single-sex of this kind.
        other = 'female' if sex_filter == 'male' else 'male'
        stmt = stmt.where(
            Cage.animals.any(Animal.sex == sex_filter)
            & ~Cage.animals.any(Animal.sex == other)
        )
    elif sex_filter == 'mixed':
        stmt = stmt.where(
            Cage.animals.any(Animal.sex == 'male')
            & Cage.animals.any(Animal.sex == 'female')
        )

    if source_filter != 'all':
        stmt = stmt.where(Cage.animals.any(
            Animal.source_id == int(source_filter)
        ))

    if notes_filter == 'yes':
        stmt = stmt.where(
            Cage.notes.is_not(None) & (func.trim(Cage.notes) != '')
        )
    elif notes_filter == 'no':
        stmt = stmt.where(or_(
            Cage.notes.is_(None), func.trim(Cage.notes) == ''
        ))

    if tag_filter != 'all':
        tag_ids = AnimalTag.descendant_ids(db.session, int(tag_filter))
        stmt = stmt.where(Cage.animals.any(
            Animal.tags.any(AnimalTag.id.in_(tag_ids))
        ))

    if procedure_filter != 'all':
        proc_ids = AnimalProcedure.descendant_ids(db.session, int(procedure_filter))
        stmt = stmt.where(Cage.animals.any(
            Animal.events.any(AnimalEvent.procedure_id.in_(proc_ids))
        ))

    # Occupancy uses *active* animal counts. Build a correlated subquery
    # so we can filter and sort on it without an extra Python pass.
    active_count_subq = (
        select(
            Animal.cage_id.label('cage_id'),
            func.count(Animal.id).label('active_count'),
        )
        .where(Animal.termination_date.is_(None))
        .group_by(Animal.cage_id)
        .subquery()
    )
    total_count_subq = (
        select(
            Animal.cage_id.label('cage_id'),
            func.count(Animal.id).label('total_count'),
            func.min(Animal.dob).label('min_dob'),
            func.max(Animal.dob).label('max_dob'),
        )
        .group_by(Animal.cage_id)
        .subquery()
    )

    stmt = (
        stmt
        .outerjoin(active_count_subq, active_count_subq.c.cage_id == Cage.id)
        .outerjoin(total_count_subq, total_count_subq.c.cage_id == Cage.id)
    )

    active_count_col = func.coalesce(active_count_subq.c.active_count, 0)
    total_count_col = func.coalesce(total_count_subq.c.total_count, 0)

    if occupancy_filter == 'empty':
        stmt = stmt.where(active_count_col == 0)
    elif occupancy_filter == 'single':
        stmt = stmt.where(active_count_col == 1)
    elif occupancy_filter == 'multi':
        stmt = stmt.where(active_count_col > 1)

    # Sorting (SQL).
    if sort_by == 'age':
        # asc age = youngest first ⇒ newest dob first (max(dob) desc).
        col = total_count_subq.c.max_dob
        order = col.asc().nullslast() if sort_dir == 'desc' else col.desc().nullslast()
    elif sort_by == 'animal_count':
        col = total_count_col
        order = col.desc() if sort_dir == 'desc' else col.asc()
    elif sort_by == 'active_count':
        col = active_count_col
        order = col.desc() if sort_dir == 'desc' else col.asc()
    else:  # custom_id
        col = Cage.custom_id
        order = col.desc() if sort_dir == 'desc' else col.asc()

    cages = db.session.scalars(stmt.order_by(order)).all()
    _attach_cage_animals(cages)

    sources = db.session.scalars(
        select(Source).order_by(Source.name)
    ).all()
    animal_tags = AnimalTag.get_ordered(db.session)
    procedures = AnimalProcedure.get_ordered(db.session)

    filters = {
        'sort_by': sort_by,
        'sort_dir': sort_dir,
        'status_filter': status_filter,
        'sex_filter': sex_filter,
        'source_id': source_filter,
        'occupancy_filter': occupancy_filter,
        'notes_filter': notes_filter,
        'tag_id': tag_filter,
        'procedure_id': procedure_filter,
        'age_unit': age_unit,
    }
    return render_template(
        'cages.html', cages=cages, filters=filters,
        sources=sources, animal_tags=animal_tags, procedures=procedures,
    )


@cages_bp.route('/<int:cage_id>')
def view_cage(cage_id):
    cage = db.get_or_404(Cage, cage_id)
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
    cage = db.get_or_404(Cage, cage_id)
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
    cage = db.get_or_404(Cage, cage_id)
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
    return render_modal(CageForm(), label='Add Cage',
                        submit_url=url_for('cages.create_cage'))


@cages_bp.route('/<int:cage_id>/edit_note_modal')
def update_cage_note_modal(cage_id):
    cage = db.get_or_404(Cage, cage_id)
    return render_modal(NoteForm(obj=cage), item=cage,
                        label=f'Edit note for {cage.custom_id}',
                        submit_url=url_for('cages.update_cage_note', cage_id=cage.id))
