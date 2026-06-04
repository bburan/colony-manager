from sqlalchemy import exists, select
from sqlalchemy.orm import contains_eager, selectinload
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, make_response

from colony_manager.models import (
    Ear, EarTag, Animal, AnimalEvent, AnimalProcedure, AnimalTag, AnimalEventTag,
    Study, ConfocalImage, ImmunolabelingPanel, ConfocalImageType,
    ConfocalImageData, data_candidate_ears,
    _canonical_side,
)
from .. import db
from ..forms import HistologyForm, NoteForm, ConfocalImageForm
from .util import flash_form_errors, get_or_404, render_error_alert, is_htmx, render_modal
from ..services.data_linking import resync_confocal_image

histology_bp = Blueprint('histology', __name__)

_EAR_SORT_DIR_DEFAULTS = {
    'id': 'asc',
    'euthanasia': 'desc',
    'cryoprotection': 'desc',
    'dissection': 'desc',
    'immunolabel': 'desc',
}


def _ear_sort_cols():
    """Lazy column map. Built at call time so the columns bind correctly."""
    return {
        'id': Animal.custom_id,
        'euthanasia': Animal.termination_date,
        'cryoprotection': Ear.cryoprotection_date,
        'dissection': Ear.dissection_date,
        'immunolabel': Ear.immunolabel_date,
    }


def _parse_ear_filters(args):
    sort_by = args.get('sort_by', 'id')
    sort_dir = args.get('sort_dir', '')
    if sort_dir not in ('asc', 'desc'):
        sort_dir = _EAR_SORT_DIR_DEFAULTS.get(sort_by, 'asc')
    return {
        'sort_by': sort_by,
        'sort_dir': sort_dir,
        'immunolabel_filter': args.get('immunolabel_filter', 'all'),
        'analysis_filter': args.get('analysis_filter', 'all'),
        'side_filter': args.get('side_filter', 'all'),
        'tag_id': args.get('tag_id', 'all'),
        'cryo_filter': args.get('cryo_filter', 'all'),
        'sex_filter': args.get('sex_filter', 'all'),
        'procedure_id': args.get('procedure_id', 'all'),
        'animal_tag_id': args.get('animal_tag_id', 'all'),
        'event_tag_id': args.get('event_tag_id', 'all'),
        'study_id': args.get('study_id', 'all'),
    }


def _apply_ear_filters(query, f):
    """Apply every filter from ``_parse_ear_filters`` to ``query``.

    Assumes ``query`` is rooted on ``Ear`` and already joined to ``Animal``
    (needed for sex / sort by custom_id or termination_date).
    """
    if f['immunolabel_filter'] == 'labeled':
        query = query.filter(Ear.immunolabel_date.is_not(None))
    elif f['immunolabel_filter'] == 'pending':
        query = query.filter(Ear.immunolabel_date.is_(None))

    if f['cryo_filter'] == 'done':
        query = query.filter(Ear.cryoprotection_date.is_not(None))
    elif f['cryo_filter'] == 'pending':
        query = query.filter(Ear.cryoprotection_date.is_(None))

    if f['side_filter'] in ('Left', 'Right'):
        query = query.filter(Ear.side == f['side_filter'])

    if f['tag_id'] != 'all':
        ids = EarTag.descendant_ids(db.session, int(f['tag_id']))
        query = query.filter(Ear.tags.any(EarTag.id.in_(ids)))

    if f['sex_filter'] in ('male', 'female'):
        query = query.filter(Animal.sex == f['sex_filter'])

    if f['procedure_id'] != 'all':
        ids = AnimalProcedure.descendant_ids(db.session, int(f['procedure_id']))
        query = query.filter(Animal.events.any(
            AnimalEvent.procedure_id.in_(ids)
        ))

    if f['animal_tag_id'] != 'all':
        ids = AnimalTag.descendant_ids(db.session, int(f['animal_tag_id']))
        query = query.filter(Animal.tags.any(AnimalTag.id.in_(ids)))

    if f['event_tag_id'] != 'all':
        ids = AnimalEventTag.descendant_ids(db.session, int(f['event_tag_id']))
        query = query.filter(Animal.events.any(
            AnimalEvent.tags.any(AnimalEventTag.id.in_(ids))
        ))

    if f['study_id'] != 'all':
        query = query.filter(Animal.studies.any(
            Study.id == int(f['study_id'])
        ))

    if f['analysis_filter'] != 'all':
        subquery = exists().where(
            (ConfocalImage.ear_id == Ear.id)
            & (ConfocalImage.status == f['analysis_filter'])
        )
        query = query.filter(subquery)

    species_id = int(session.get('selected_species', -1))
    if species_id != -1:
        query = query.filter(Animal.species_id == species_id)

    return query


def _apply_ear_sort(query, f):
    col = _ear_sort_cols().get(f['sort_by'], Animal.custom_id)
    if f['sort_dir'] == 'desc':
        order = col.desc().nullslast()
    else:
        order = col.asc().nullsfirst()
    return query.order_by(order, Ear.side)


def _ear_filter_lookups():
    return {
        'ear_tags': EarTag.get_ordered(db.session),
        'procedures': AnimalProcedure.get_ordered(db.session),
        'animal_tags': AnimalTag.get_ordered(db.session),
        'event_tags': AnimalEventTag.get_ordered(db.session),
        'studies': db.session.scalars(
            select(Study).order_by(Study.name)
        ).all(),
    }


@histology_bp.route('/')
def list_histology():
    f = _parse_ear_filters(request.args)
    stmt = _apply_ear_filters(
        select(Ear).join(Animal).options(
            contains_eager(Ear.animal),
            selectinload(Ear.tags),
        ),
        f,
    )
    ears = db.session.scalars(_apply_ear_sort(stmt, f)).all()
    return render_template(
        'histology.html',
        ears=ears,
        filters=f,
        **_ear_filter_lookups(),
    )


@histology_bp.route('/grid')
def view_grid():
    f = _parse_ear_filters(request.args)
    conflicts_only = request.args.get('conflicts_only') in ('1', 'true', 'on')

    image_types = db.session.scalars(
        select(ConfocalImageType).order_by(ConfocalImageType.name)
    ).all()
    if not image_types:
        return render_template(
            'histology_grid.html',
            image_types=[],
            selected_image_type=None,
            ears=[],
            frequencies=[],
            grid={},
            orphans_by_ear={},
            has_other_column=False,
            filters={**f, 'image_type': '', 'conflicts_only': '1' if conflicts_only else ''},
            **_ear_filter_lookups(),
        )

    selected_id = request.args.get('image_type', type=int)
    selected_image_type = None
    if selected_id is not None:
        selected_image_type = next((t for t in image_types if t.id == selected_id), None)
    if selected_image_type is None:
        selected_image_type = image_types[0]

    # Eager-load the two relationships the template accesses on every row:
    # - contains_eager: Animal is already JOIN-ed for filtering/sorting, so
    #   we piggyback on that JOIN to populate ear.animal at no extra cost.
    # - selectinload: EarTag is M2M; one SELECT IN replaces N lazy loads.
    ear_stmt = _apply_ear_filters(
        select(Ear).join(Animal).options(
            contains_eager(Ear.animal),
            selectinload(Ear.tags),
        ),
        f,
    )
    ears = db.session.scalars(_apply_ear_sort(ear_stmt, f)).all()

    # Column set: distinct frequencies across all in-scope ConfocalImage rows
    # for the selected image type. Fixed regardless of row filters.
    ear_ids = [e.id for e in ears]
    freq_set = set()
    if ear_ids:
        rows = db.session.execute(
            select(ConfocalImage.frequency).where(
                ConfocalImage.ear_id.in_(ear_ids),
                ConfocalImage.image_type_id == selected_image_type.id,
            ).distinct()
        ).all()
        freq_set = {r[0] for r in rows if r[0] is not None}
    frequencies = sorted(freq_set)

    # Build grid: {ear_id: {frequency: ConfocalImage}}
    # selectinload on data_files: one SELECT IN for all images replaces the
    # per-cell lazy load that grid_status_square.html triggers via
    # ``img.data_files|length``.
    grid = {e.id: {} for e in ears}
    if ear_ids:
        imgs = db.session.scalars(
            select(ConfocalImage).where(
                ConfocalImage.ear_id.in_(ear_ids),
                ConfocalImage.image_type_id == selected_image_type.id,
            ).options(selectinload(ConfocalImage.data_files))
        ).all()
        for img in imgs:
            grid[img.ear_id][img.frequency] = img

    # Orphan candidates: one bulk query across all visible ears reads
    # ``parsed_metadata`` directly. Avoids the per-ear lazy load on
    # ``ear.candidate_data_files`` (dynamic relationship) plus the per-file
    # description-class round-trip in the old implementation.
    orphans_by_ear = {}
    has_other_column = False
    freq_col_set = set(frequencies)
    if ear_ids:
        rows = db.session.execute(
            select(ConfocalImageData, data_candidate_ears.c.ear_id)
            .join(data_candidate_ears,
                  data_candidate_ears.c.data_id == ConfocalImageData.id)
            .where(
                data_candidate_ears.c.ear_id.in_(ear_ids),
                ~ConfocalImageData.confocal_images.any(),
            )
        ).all()

        ear_by_id = {e.id: e for e in ears}
        for data_file, ear_id in rows:
            parsed = data_file.parsed_metadata
            if not parsed:
                continue
            if parsed.get('image_type') != selected_image_type.name:
                continue
            try:
                freq = float(parsed.get('frequency'))
            except (TypeError, ValueError):
                continue
            ear = ear_by_id.get(ear_id)
            if ear is None:
                continue
            side = _canonical_side(parsed.get('side') or parsed.get('ear'))
            if side and side != ear.side:
                continue
            if freq in grid[ear_id]:
                continue
            orphans_by_ear.setdefault(ear_id, []).append({
                'file': data_file,
                'frequency': freq,
                'image_type_name': parsed.get('image_type'),
                'side': side,
            })
            if freq not in freq_col_set:
                has_other_column = True

    if conflicts_only:
        # data_files is already selectinloaded above, so img.data_files is an
        # in-memory list — no further queries issued here.
        conflict_statuses = {'imaged', 'analyzed', 'need_review', 'region_bad'}

        def ear_has_conflict(ear):
            if ear.id in orphans_by_ear:
                return True
            for img in grid[ear.id].values():
                if img.status in conflict_statuses and not img.data_files:
                    return True
            return False

        ears = [e for e in ears if ear_has_conflict(e)]

    return render_template(
        'histology_grid.html',
        image_types=image_types,
        selected_image_type=selected_image_type,
        ears=ears,
        frequencies=frequencies,
        grid=grid,
        orphans_by_ear=orphans_by_ear,
        has_other_column=has_other_column,
        filters={**f, 'image_type': selected_image_type.id,
                 'conflicts_only': '1' if conflicts_only else ''},
        **_ear_filter_lookups(),
    )


@histology_bp.route('/ears/<int:ear_id>')
def view_ear(ear_id):
    ear = get_or_404(Ear, ear_id)
    return render_template('view_ear.html', ear=ear)


def _update_ear_response(ear, default_card_partial):
    """Build the HTMX swap response for a successful ear update.

    The caller passes ``hx_target`` (the swap target the originating page
    cares about). Three shapes are produced:

    - ``#histology-grid-reload``: grid cells depend on page-level
      frequency/orphan state, so we trigger a full page refresh.
    - anything starting with ``#ear-row-``: re-render that table row.
    - anything else (incl. unset): re-render ``default_card_partial`` for
      the ear-detail page.
    """
    hx_target = request.args.get('hx_target')
    if hx_target == '#histology-grid-reload':
        response = make_response('', 204)
        response.headers['HX-Trigger'] = 'closeModal'
        response.headers['HX-Refresh'] = 'true'
        return response
    if hx_target and hx_target.startswith('#ear-row-'):
        body = render_template('partials/ear_row.html', ear=ear)
    else:
        body = render_template(default_card_partial, ear=ear)
    response = make_response(body)
    response.headers['HX-Trigger'] = 'closeModal'
    return response


def _update_ear(ear_id, form_cls, default_card_partial):
    """Shared body for both ear-update routes."""
    ear = get_or_404(Ear, ear_id)
    form = form_cls(obj=ear)
    if not form.validate_on_submit():
        if is_htmx():
            return render_error_alert(message='Update failed', form=form), 400
        flash_form_errors(form, title='Error updating ear')
        return redirect(request.referrer or url_for('histology.list_histology'))

    form.populate_obj(ear)
    db.session.commit()
    if is_htmx():
        return _update_ear_response(ear, default_card_partial)
    flash('Ear updated.', 'success')
    return redirect(request.referrer or url_for('histology.list_histology'))


@histology_bp.route('/ears/<int:ear_id>/notes/update', methods=['POST'])
def update_ear_note(ear_id):
    return _update_ear(ear_id, NoteForm, 'partials/ear_notes_card.html')


@histology_bp.route('/ears/<int:ear_id>/histology/update', methods=['POST'])
def update_ear_histology(ear_id):
    return _update_ear(ear_id, HistologyForm, 'partials/ear_histology_card.html')


# --- Confocal Image Routes ---
@histology_bp.route('/ears/<int:ear_id>/confocal_images/create', methods=['POST'])
def create_confocal_image(ear_id):
    ear = get_or_404(Ear, ear_id)
    form = ConfocalImageForm()
    form.image_type.choices = [
        (t.id, t.name) for t in db.session.scalars(select(ConfocalImageType)).all()
    ]

    if form.validate_on_submit():
        new_images = []
        for freq_str in form.frequencies.data:
            new_image = ConfocalImage(
                ear_id=ear.id,
                frequency=float(freq_str),
                image_type=form.image_type.data,
                notes=form.notes.data,
                status='imaged',
            )
            db.session.add(new_image)
            new_images.append(new_image)
        db.session.flush()  # populate image.id and image_type_id
        for img in new_images:
            resync_confocal_image(img)
        db.session.commit()
        if request.headers.get('HX-Request'):
            html = render_template('partials/confocal_image_table.html', ear=ear)
            response = make_response(html)
            response.headers['HX-Trigger'] = 'closeModal'
            return response
        flash(f'Images added for {ear.animal.custom_id} {ear.side}', 'success')
    else:
        if request.headers.get('HX-Request'):
            return render_error_alert(message='Error adding images', form=form), 400
        flash_form_errors(form, title="Error adding images")
    return redirect(request.referrer or url_for('histology.list_histology'))

@histology_bp.route('/confocal_images/<int:image_id>/update', methods=['POST'])
def update_confocal_image(image_id):
    img = get_or_404(ConfocalImage, image_id)
    img.status = request.form['status']
    img.notes = request.form['notes']
    db.session.commit()
    if request.headers.get('HX-Request'):
        # Return the updated grid cell as an OOB swap so the histology grid
        # repaints behind the open modal. Harmless on pages that don't
        # render the square (the OOB target id simply won't exist).
        return render_template('partials/grid_status_square.html', img=img, oob=True)
    return redirect(request.referrer or url_for('histology.list_histology'))

@histology_bp.route('/confocal_images/<int:image_id>/delete', methods=['POST'])
def delete_confocal_image(image_id):
    img = get_or_404(ConfocalImage, image_id)
    try:
        db.session.delete(img)
        db.session.commit()
        if request.headers.get('HX-Request'):
            return '', 200
        flash('Image record deleted successfully.', 'info')
    except Exception as e:
        db.session.rollback()
        if request.headers.get('HX-Request'):
            return 'Error deleting record', 500
        flash('Error deleting record', 'danger')
    return redirect(request.referrer or url_for('histology.list_histology'))


@histology_bp.route('/animals/<int:animal_id>/ears/create', methods=['POST'])
def create_ear(animal_id):
    """Create a missing Ear (Left or Right) for an already-terminated animal.

    Covers the case where ``ears_extracted`` wasn't set on the
    termination form. Side is provided via form data. Duplicates are
    refused — there's a unique (animal_id, side) pair implicitly via
    histology semantics, though no DB constraint enforces it today.
    """
    animal = get_or_404(Animal, animal_id)
    side = request.form.get('side', '').strip()
    side = _canonical_side(side)
    if side not in ('Left', 'Right'):
        flash('Side must be Left or Right.', 'danger')
        return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal_id))

    existing = db.session.scalars(
        select(Ear).where(Ear.animal_id == animal.id, Ear.side == side)
    ).first()
    if existing is not None:
        flash(f'{animal.display_id} already has a {side} ear.', 'warning')
        return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal_id))

    db.session.add(Ear(animal_id=animal.id, side=side))
    db.session.commit()
    flash(f'{side} ear created for {animal.display_id}.', 'success')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal_id))


@histology_bp.route('/ears/<int:ear_id>/delete', methods=['POST'])
def delete_ear(ear_id):
    ear = get_or_404(Ear, ear_id)
    if ear.confocal_images:
        msg = 'Cannot delete an ear that has acquired images.'
        if request.headers.get('HX-Request'):
            return msg, 409
        flash(msg, 'danger')
        return redirect(request.referrer or url_for('histology.list_histology'))
    try:
        db.session.delete(ear)
        db.session.commit()
        if request.headers.get('HX-Request'):
            return '', 200
        flash('Ear deleted successfully.', 'info')
    except Exception as e:
        db.session.rollback()
        if request.headers.get('HX-Request'):
            return 'Error deleting ear (it may have linked records)', 500
        flash('Error deleting ear (it may have linked records)', 'danger')
    return redirect(request.referrer or url_for('histology.list_histology'))


# --- Modal Routes ---
@histology_bp.route('/ears/<int:ear_id>/edit_note_modal')
def edit_ear_note_modal(ear_id):
    ear = get_or_404(Ear, ear_id)
    hx_target = request.args.get('hx_target', '#ear-notes-card')
    return render_modal(
        NoteForm(obj=ear), item=ear,
        label=f'Edit note for {ear.animal.custom_id} {ear.side}',
        submit_url=url_for('histology.update_ear_note', ear_id=ear.id, hx_target=hx_target),
        hx_target=hx_target, hx_swap='outerHTML',
    )


@histology_bp.route('/ears/<int:ear_id>/edit_histology_modal')
def edit_ear_histology_modal(ear_id):
    ear = get_or_404(Ear, ear_id)
    hx_target = request.args.get('hx_target', '#ear-histology-card')
    return render_modal(
        HistologyForm(obj=ear), item=ear,
        label=f'Edit histology for {ear.animal.custom_id} {ear.side}',
        submit_url=url_for('histology.update_ear_histology', ear_id=ear.id, hx_target=hx_target),
        hx_target=hx_target, hx_swap='outerHTML',
    )


@histology_bp.route('/confocal_images/<int:image_id>/edit_modal')
def edit_confocal_image_modal(image_id):
    img = get_or_404(ConfocalImage, image_id)
    return render_template('partials/edit_confocal_image_modal.html', img=img)


@histology_bp.route('/ears/<int:ear_id>/confocal_images/create_modal')
def create_confocal_images_modal(ear_id):
    ear = get_or_404(Ear, ear_id)
    return render_modal(
        ConfocalImageForm(), item=ear,
        label=f'Add images for {ear.animal.custom_id} {ear.side}',
        submit_url=url_for('histology.create_confocal_image', ear_id=ear.id),
        hx_target='#confocal-image-table-container', hx_swap='outerHTML',
    )

# --- AJAX Popover Routes ---
@histology_bp.route('/ears/<int:ear_id>/images_popover')
def view_ear_images_popover(ear_id):
    ear = get_or_404(Ear, ear_id)
    return render_template(
        'partials/ear_images_popover.html',
        ear=ear,
    )
