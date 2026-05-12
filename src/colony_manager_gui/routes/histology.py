from sqlalchemy import exists
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, make_response

import os

from colony_manager.datatypes import load_description_class
from colony_manager.models import (
    Ear, Animal, ConfocalImage, ImmunolabelingPanel, ConfocalImageType,
    ConfocalImageData, _canonical_side,
)
from .. import db
from ..forms import HistologyForm, NoteForm, ConfocalImageForm
from .util import flash_form_errors, render_error_alert

histology_bp = Blueprint('histology', __name__)

@histology_bp.route('/')
def list_histology():
    query = Ear.query.join(Animal)

    immunolabel_filter = request.args.get('immunolabel_filter', 'all')
    if immunolabel_filter == 'labeled':
        query = query.filter(Ear.immunolabel_date != None)
    elif immunolabel_filter == 'pending':
        query = query.filter(Ear.immunolabel_date == None)

    sort_by = request.args.get('sort_by', 'id')
    if sort_by == 'euthanasia':
        query = query.add_columns(Animal.termination_date).order_by(Animal.termination_date.desc().nulls_last())
    else:
        query = query.add_columns(Animal.custom_id).order_by(Animal.custom_id)

    analysis_filter = request.args.get('analysis_filter', 'all')
    if analysis_filter != 'all':
        subquery = exists().where(
            (ConfocalImage.ear_id == Ear.id) & \
            (ConfocalImage.status == analysis_filter)
        )
        query = query.filter(subquery)

    species_id = int(session.get('selected_species', -1))
    if species_id != -1:
        query = query.filter(Ear.animal.has(species_id=species_id))
    ears = [row[0] for row in query.distinct().all()]

    return render_template(
        'histology.html',
        ears=ears,
        filters={
            'immunolabel_filter': immunolabel_filter,
            'sort_by': sort_by,
            'analysis_filter': analysis_filter,
        },
    )


def _parse_orphan_confocal_files(ear):
    """Re-parse unmatched ConfocalImageData files attached to ``ear`` as
    candidates. Returns a list of dicts with keys: file, frequency,
    image_type_name, side.
    """
    results = []
    desc_cache = {}
    for f in ear.candidate_data_files:
        if f.target_type != 'confocal_image' or f.confocal_images:
            continue
        dotted = f.datatype.description_class
        if not dotted:
            continue
        if dotted not in desc_cache:
            try:
                desc_cache[dotted] = load_description_class(dotted)
            except Exception:
                desc_cache[dotted] = None
        desc_cls = desc_cache[dotted]
        if desc_cls is None:
            continue
        full_path = os.path.join(f.location.base_path, f.relative_path)
        try:
            parsed = desc_cls(full_path).parse() or {}
        except Exception:
            continue
        try:
            freq = float(parsed.get('frequency'))
        except (TypeError, ValueError):
            continue
        side = _canonical_side(parsed.get('side') or parsed.get('ear'))
        if side and side != ear.side:
            continue
        results.append({
            'file': f,
            'frequency': freq,
            'image_type_name': parsed.get('image_type'),
            'side': side,
        })
    return results


@histology_bp.route('/grid')
def view_grid():
    species_id = int(session.get('selected_species', -1))

    image_types = ConfocalImageType.query.order_by(ConfocalImageType.name).all()
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
            filters={'sort_by': 'id', 'conflicts_only': False},
        )

    selected_id = request.args.get('image_type', type=int)
    selected_image_type = None
    if selected_id is not None:
        selected_image_type = next((t for t in image_types if t.id == selected_id), None)
    if selected_image_type is None:
        selected_image_type = image_types[0]

    sort_by = request.args.get('sort_by', 'id')
    conflicts_only = request.args.get('conflicts_only') in ('1', 'true', 'on')

    ear_query = Ear.query.join(Animal)
    if species_id != -1:
        ear_query = ear_query.filter(Ear.animal.has(species_id=species_id))
    if sort_by == 'euthanasia':
        ear_query = ear_query.add_columns(Animal.termination_date).order_by(
            Animal.termination_date.desc().nulls_last())
    else:
        ear_query = ear_query.add_columns(Animal.custom_id).order_by(Animal.custom_id)
    ears = [row[0] for row in ear_query.distinct().all()]

    # Column set: distinct frequencies across all in-scope ConfocalImage rows
    # for the selected image type. Fixed regardless of row filters.
    ear_ids = [e.id for e in ears]
    freq_set = set()
    if ear_ids:
        rows = db.session.query(ConfocalImage.frequency).filter(
            ConfocalImage.ear_id.in_(ear_ids),
            ConfocalImage.image_type_id == selected_image_type.id,
        ).distinct().all()
        freq_set = {r[0] for r in rows if r[0] is not None}
    frequencies = sorted(freq_set)

    # Build grid: {ear_id: {frequency: ConfocalImage}}
    grid = {e.id: {} for e in ears}
    if ear_ids:
        imgs = ConfocalImage.query.filter(
            ConfocalImage.ear_id.in_(ear_ids),
            ConfocalImage.image_type_id == selected_image_type.id,
        ).all()
        for img in imgs:
            grid[img.ear_id][img.frequency] = img

    # Parse orphan candidate data files per ear, filtered to selected image type.
    orphans_by_ear = {}
    has_other_column = False
    freq_col_set = set(frequencies)
    for ear in ears:
        parsed = _parse_orphan_confocal_files(ear)
        orphans = [
            p for p in parsed
            if p['image_type_name'] == selected_image_type.name
            and p['frequency'] not in grid[ear.id]
        ]
        if orphans:
            orphans_by_ear[ear.id] = orphans
            for o in orphans:
                if o['frequency'] not in freq_col_set:
                    has_other_column = True

    def ear_has_conflict(ear):
        if ear.id in orphans_by_ear:
            return True
        for img in grid[ear.id].values():
            if img.status in ('imaged', 'analyzed', 'need_review', 'region_bad') \
                    and img.data_files.count() == 0:
                return True
        return False

    if conflicts_only:
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
        filters={'sort_by': sort_by, 'conflicts_only': conflicts_only},
    )


@histology_bp.route('/ears/<int:ear_id>')
def view_ear(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    return render_template('view_ear.html', ear=ear)


@histology_bp.route('/ears/<int:ear_id>/update', methods=['POST'])
def update_ear(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    # Detect which form is being used based on request data or a custom arg
    target = request.args.get('target', 'all')
    hx_target = request.args.get('hx_target')
    
    if target == 'notes':
        form = NoteForm(obj=ear)
    else:
        form = HistologyForm(obj=ear)
        
    if form.validate_on_submit():
        form.populate_obj(ear)
        db.session.commit()
        if request.headers.get('HX-Request'):
            # Grid view doesn't have a partial for one row (cells depend on
            # page-level frequency/orphan state). Trigger a full refresh.
            if hx_target == '#histology-grid-reload':
                response = make_response('', 204)
                response.headers['HX-Trigger'] = 'closeModal'
                response.headers['HX-Refresh'] = 'true'
                return response
            # If hx_target starts with #ear-row-, it's from histology.html
            if hx_target and hx_target.startswith('#ear-row-'):
                response_html = render_template('partials/ear_row.html', ear=ear)
            else:
                # Default to cards for view_ear.html
                notes_html = render_template('partials/ear_notes_card.html', ear=ear)
                hist_html = render_template('partials/ear_histology_card.html', ear=ear)
                
                if target == 'notes':
                    response_html = notes_html
                elif target == 'histology':
                    response_html = hist_html
                else:
                    response_html = notes_html + hist_html
            
            response = make_response(response_html)
            response.headers['HX-Trigger'] = 'closeModal'
            return response
            
        flash('Ear updated.', 'success')
    else:
        if request.headers.get('HX-Request'):
            return render_error_alert(message='Update failed', form=form), 400
        flash_form_errors(form, title="Error updating ear")
    return redirect(request.referrer or url_for('histology.list_histology'))


def _resync_confocal_image(image):
    """Link unmatched ConfocalImageData rows whose parsed metadata matches *image*.

    Walks ``image.ear.candidate_data_files`` filtered to unmatched
    confocal rows, re-parses each via the row's description class, and
    links if the parsed frequency + image type + side line up. Re-parse
    is cheap because description-class ``parse()`` methods are filename
    regexes (no disk I/O).
    """
    if image.frequency is None or image.image_type_id is None:
        return 0
    image_type_name = image.image_type.name
    desc_cache = {}
    linked = 0
    for f in image.ear.candidate_data_files:
        if f.target_type != 'confocal_image' or f.confocal_images:
            continue
        dotted = f.datatype.description_class
        if not dotted:
            continue
        if dotted not in desc_cache:
            try:
                desc_cache[dotted] = load_description_class(dotted)
            except Exception:
                desc_cache[dotted] = None
        desc_cls = desc_cache[dotted]
        if desc_cls is None:
            continue
        full_path = os.path.join(f.location.base_path, f.relative_path)
        try:
            parsed = desc_cls(full_path).parse() or {}
        except Exception:
            continue
        try:
            parsed_freq = float(parsed.get('frequency'))
        except (TypeError, ValueError):
            continue
        if parsed_freq != image.frequency:
            continue
        if parsed.get('image_type') != image_type_name:
            continue
        side = _canonical_side(parsed.get('side') or parsed.get('ear'))
        if side and side != image.ear.side:
            continue
        f.confocal_images.append(image)
        linked += 1
    return linked


# --- Confocal Image Routes ---
@histology_bp.route('/ears/<int:ear_id>/confocal_images/create', methods=['POST'])
def create_confocal_image(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = ConfocalImageForm()
    form.image_type.choices = [(t.id, t.name) for t in ConfocalImageType.query.all()]

    if form.validate_on_submit():
        new_images = []
        for freq_str in form.frequencies.data:
            new_image = ConfocalImage(
                ear_id=ear.id,
                frequency=float(freq_str),
                image_type=form.image_type.data,
                notes=form.notes.data,
                status='pending',
            )
            db.session.add(new_image)
            new_images.append(new_image)
        db.session.flush()  # populate image.id and image_type_id
        for img in new_images:
            _resync_confocal_image(img)
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
    img = ConfocalImage.query.get_or_404(image_id)
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
    img = ConfocalImage.query.get_or_404(image_id)
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

# --- Modal Routes ---
@histology_bp.route('/ears/<int:ear_id>/edit_note_modal')
def edit_ear_note_modal(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = NoteForm(obj=ear)
    hx_target = request.args.get('hx_target', '#ear-notes-card')
    return render_template('partials/form_modal.html', form=form, item=ear,
                           label=f'Edit note for {ear.animal.custom_id} {ear.side}', 
                           submit_url=url_for('histology.update_ear', ear_id=ear.id, target='notes', hx_target=hx_target),
                           hx_target=hx_target,
                           hx_swap="outerHTML")

@histology_bp.route('/ears/<int:ear_id>/edit_histology_modal')
def edit_ear_histology_modal(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = HistologyForm(obj=ear)
    hx_target = request.args.get('hx_target', '#ear-histology-card')
    return render_template('partials/form_modal.html', form=form, item=ear,
                           label=f'Edit histology for {ear.animal.custom_id} {ear.side}', 
                           submit_url=url_for('histology.update_ear', ear_id=ear.id, target='histology', hx_target=hx_target),
                           hx_target=hx_target,
                           hx_swap="outerHTML")

@histology_bp.route('/confocal_images/<int:image_id>/edit_modal')
def edit_confocal_image_modal(image_id):
    img = ConfocalImage.query.get_or_404(image_id)
    return render_template('partials/edit_confocal_image_modal.html', img=img)


@histology_bp.route('/ears/<int:ear_id>/confocal_images/create_modal')
def create_confocal_images_modal(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = ConfocalImageForm()
    return render_template('partials/form_modal.html', form=form, item=ear,
                           label=f'Add images for {ear.animal.custom_id} {ear.side}', 
                           submit_url=url_for('histology.create_confocal_image', ear_id=ear.id),
                           hx_target="#confocal-image-table-container",
                           hx_swap="outerHTML")

# --- AJAX Popover Routes ---
@histology_bp.route('/ears/<int:ear_id>/images_popover')
def view_ear_images_popover(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    return render_template(
        'partials/ear_images_popover.html',
        ear=ear,
    )
