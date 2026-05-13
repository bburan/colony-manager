import importlib
import os
from urllib.parse import urlparse, urljoin
import sqlalchemy
from sqlalchemy.orm import joinedload, selectinload
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort
from flask_login import current_user, login_user
from datetime import date, timedelta

from colony_manager import models

from .. import db
from .. import forms
from ..forms import (
    FeedForm, SimpleAddForm, SimpleAddWithDescriptionForm, DataTypeForm,
    DataLocationForm, DATATYPE_FORMS, DATATYPE_TARGET_LABELS, datatype_form_for,
)
from .util import flash_form_errors, render_error_alert, htmx_or_redirect, htmx_error, is_htmx
from colony_manager.datatypes import load_description_class
from ..jobs import (
    enqueue_datatype_sync, enqueue_datatype_rematch,
    recent_jobs, parse_summary,
)
from .. import queries

main_bp = Blueprint('main', __name__)


@main_bp.before_request
def _restrict_settings_to_admin():
    if not request.path.startswith('/settings'):
        return
    if current_user.is_anonymous or not current_user.is_admin():
        abort(403)


SETTINGS_MAP = {
    'species': {'model': models.Species, 'form': forms.SimpleAddForm},
    'source': {'model': models.Source, 'form': forms.SimpleAddForm},
    'confocal_image_type': {'model': models.ConfocalImageType, 'form': forms.SimpleAddForm},
    'termination_reason': {'model': models.TerminationReason, 'form': forms.SimpleAddForm},
    'animal_procedure': {'model': models.AnimalProcedure, 'form': forms.create_nested_form(models.AnimalProcedure)},
    'animal_procedure_target': {'model': models.AnimalProcedureTarget, 'form': forms.ProcedureTargetForm},
    'feed': {'model': models.Feed, 'form': forms.FeedForm},
    'animal_tag': {'model': models.AnimalTag, 'form': forms.create_nested_form(models.AnimalTag)},
    'animal_event_tag': {'model': models.AnimalEventTag, 'form': forms.create_nested_form(models.AnimalEventTag)},
    'ear_tag': {'model': models.EarTag, 'form': forms.create_nested_form(models.EarTag)},
    'immunolabeling_panel': {'model': models.ImmunolabelingPanel, 'form': forms.SimpleAddWithDescriptionForm},
}

@main_bp.route('/')
def view_dashboard():
    today = date.today()

    # 1. Metrics for Top Cards
    active_cages_count = queries.count_active_cages(db.session)
    active_animals_count = queries.count_active_animals(db.session)
    ears_for_processing_count = queries.count_unprocessed_ears(db.session)
    active_breeding_pairs_count = queries.count_active_breeding_pairs(db.session)

    # 2. Upcoming Events Table (Next 7 days + Overdue)
    upcoming_events = models.AnimalEvent.query.options(
        joinedload(models.AnimalEvent.animal),
        joinedload(models.AnimalEvent.procedure),
    ).filter(
        models.AnimalEvent.completion_date == None,
        models.AnimalEvent.scheduled_date <= today + timedelta(days=7)
    ).order_by(models.AnimalEvent.scheduled_date.asc()).all()

    # Recently completed events (last 7 days), most recent first. The
    # template walks each event's animal/procedure/target. ``data_files``
    # is a dynamic relationship (lazy='dynamic') and can't be eager-loaded
    # — the template's ``event.data_files.count()`` per row stays one
    # cheap COUNT(*) per event, and iteration is gated behind an Alpine
    # accordion so it only fires on click.
    recent_events_threshold = today - timedelta(days=7)
    recent_events = models.AnimalEvent.query.options(
        joinedload(models.AnimalEvent.animal),
        joinedload(models.AnimalEvent.procedure),
        joinedload(models.AnimalEvent.procedure_target),
    ).filter(
        models.AnimalEvent.completion_date != None,
        models.AnimalEvent.completion_date >= recent_events_threshold,
    ).order_by(
        models.AnimalEvent.completion_date.desc(),
        models.AnimalEvent.id.desc(),
    ).all()

    # Confocal image files acquired in the last 7 days (by file mtime),
    # grouped by ConfocalImage. Insertion order = most-recently-modified first.
    # We walk each file's confocal_images, then per-image its image_type and
    # ear→animal — load the whole chain in one shot.
    recent_confocal_files = models.ConfocalImageData.query.options(
        joinedload(models.ConfocalImageData.datatype),
        selectinload(models.ConfocalImageData.confocal_images)
            .joinedload(models.ConfocalImage.image_type),
        selectinload(models.ConfocalImageData.confocal_images)
            .joinedload(models.ConfocalImage.ear)
            .joinedload(models.Ear.animal),
    ).filter(
        models.ConfocalImageData.mtime != None,
        models.ConfocalImageData.mtime >= recent_events_threshold,
    ).order_by(models.ConfocalImageData.mtime.desc()).all()
    recent_confocal_groups = []
    _seen_image_ids = {}
    unmatched_recent_confocal = []
    for f in recent_confocal_files:
        images = list(f.confocal_images)
        if not images:
            unmatched_recent_confocal.append(f)
            continue
        for img in images:
            idx = _seen_image_ids.get(img.id)
            if idx is None:
                _seen_image_ids[img.id] = len(recent_confocal_groups)
                recent_confocal_groups.append({'image': img, 'files': [f]})
            else:
                recent_confocal_groups[idx]['files'].append(f)

    # Animals terminated in the last 30 days. Template renders display_id,
    # which falls back to cage.custom_id when the animal has no custom id.
    recent_terminations = models.Animal.query.options(
        joinedload(models.Animal.cage),
    ).filter(
        models.Animal.termination_date >= (date.today() - timedelta(days=7))
    ).order_by(models.Animal.termination_date.desc())

    upcoming_litters = models.Litter.query.options(
        joinedload(models.Litter.breeding_pair),
    ).filter(models.Litter.wean_date == None).order_by(models.Litter.dob).all()

    active_males = db.session.query(models.BreedingPair.male_animal_id).filter_by(is_active=True)
    active_females = db.session.query(models.BreedingPair.female_animal_id).filter_by(is_active=True)
    active_parent_ids = active_males.union(active_females)
    unassigned_animals = models.Animal.query.filter(
        models.Animal.termination_date == None,
        ~models.Animal.studies.any(),
        models.Animal.custom_id != None,
        ~models.Animal.id.in_(active_parent_ids),
    ).order_by(models.Animal.custom_id)

    available_animals_n = models.Animal.query.filter(models.Animal.custom_id == None).count()

    # Both lists are grouped in the template by ear and image_type — load
    # the chain so the groupby doesn't fire one query per image.
    _image_options = (
        joinedload(models.ConfocalImage.image_type),
        joinedload(models.ConfocalImage.ear).joinedload(models.Ear.animal),
    )
    image_analysis_pending = models.ConfocalImage.query.options(
        *_image_options
    ).filter_by(status='pending')
    image_analysis_review = models.ConfocalImage.query.options(
        *_image_options
    ).filter_by(status='need_review')

    species_id = int(session.get('selected_species', -1))
    if species_id != -1:
        species = models.Species.query.get(species_id)
    else:
        species = None

    return render_template(
        'view_dashboard.html',
        # Card Metrics
        active_cages=active_cages_count,
        active_animals=active_animals_count,
        active_pairs=active_breeding_pairs_count,
        ears_to_process=ears_for_processing_count,

        # Schedule & Alerts
        upcoming_events=upcoming_events,
        recent_events=recent_events,
        recent_confocal_groups=recent_confocal_groups,
        unmatched_recent_confocal=unmatched_recent_confocal,

        # Additional information
        recent_terminations=recent_terminations,
        upcoming_litters=upcoming_litters,
        unassigned_animals=unassigned_animals,
        available_animals_n=available_animals_n,
        image_analysis_pending=image_analysis_pending,
        image_analysis_review=image_analysis_review,
        today=today,

        # Table of weights for past week
        weights=models.Animal.get_daily_logs(before=5, after=2, species=species),
    )


@main_bp.route('/calendar')
def view_calendar():
    events = models.AnimalEvent.query.options(
        joinedload(models.AnimalEvent.animal),
        joinedload(models.AnimalEvent.procedure),
    ).all()
    calendar_events = []
    for event in events:
        calendar_events.append({
            'title': f"{event.animal.custom_id}: {event.procedure.name}",
            'start': event.completion_date.isoformat() if event.completion_date is not None else event.scheduled_date.isoformat(),
            'url': url_for('animals.view_animal', animal_id=event.animal.id),
            'backgroundColor': '#198754' if event.completion_date is not None else '#0d6efd',
        })
    return render_template('calendar.html', calendar_events=calendar_events)


# --- Settings Routes ---
@main_bp.route('/settings')
def list_settings():
    settings = {k: {'items': v['model'].query.all(), 'form': v['form']} for k, v in SETTINGS_MAP.items()}
    jobs = recent_jobs(limit=10)
    return render_template(
        'view_settings.html',
        simple_add_form=SimpleAddForm(),
        simple_add_with_description_form=SimpleAddWithDescriptionForm(),
        settings=settings,
        datatypes=models.DataType.query.all(),
        recent_jobs=jobs,
        parse_summary=parse_summary,
    )


@main_bp.route('/settings/jobs/recent')
def list_recent_jobs():
    """HTMX poll target — returns the recent-jobs panel HTML."""
    return render_template(
        'partials/recent_jobs_panel.html',
        recent_jobs=recent_jobs(limit=10),
        parse_summary=parse_summary,
    )


def _render_nested_section(item_type):
    """Re-render the whole settings section for a nested-tag setting. Every
    mutation (create/update/delete) returns this so htmx swaps the entire
    section — sidesteps having to surgically sync parent dropdowns."""
    cfg = SETTINGS_MAP[item_type]
    info = {'items': cfg['model'].query.all(), 'form': cfg['form']}
    return render_template(
        'partials/setting_section_nested.html', type=item_type, info=info,
    )


def _setting_is_nested(item_type, form=None):
    Model = SETTINGS_MAP[item_type]['model']
    if form is None:
        form = SETTINGS_MAP[item_type]['form']()
    return hasattr(form, 'parent') and hasattr(Model, 'parent_id')


def _setting_success_body(item_type, item, form):
    """Render the HTMX success body for create/update of a setting."""
    if _setting_is_nested(item_type, form):
        return _render_nested_section(item_type), None
    display_form = SETTINGS_MAP[item_type]['form'](obj=item)
    html = render_template(
        'partials/setting_list_item.html',
        type=item_type, item=item, form=display_form,
    )
    return html, f'error-{item_type}'


@main_bp.route('/settings/<item_type>/create', methods=['POST'])
def create_setting(item_type):
    Model = SETTINGS_MAP[item_type]['model']
    form = SETTINGS_MAP[item_type]['form']()
    pretty = item_type.replace("_", " ")
    list_url = url_for('main.list_settings')
    retarget = f'#error-{item_type}'

    if not form.validate_on_submit():
        return htmx_error(message='Validation failed', form=form,
                          retarget=retarget,
                          flash_title='Could not create setting',
                          redirect_to=list_url)

    dupe_query = Model.query.filter(Model.name == form.name.data)
    if _setting_is_nested(item_type, form):
        parent_obj = form.parent.data
        parent_id = parent_obj.id if parent_obj else None
        dupe_query = dupe_query.filter(Model.parent_id == parent_id)
    if dupe_query.first():
        return htmx_error(message='Already exists.', retarget=retarget,
                          flash_title=f'Error adding {pretty}. It might already exist.',
                          redirect_to=list_url)

    try:
        item = Model()
        form.populate_obj(item)
        db.session.add(item)
        db.session.commit()
    except sqlalchemy.exc.IntegrityError:
        db.session.rollback()
        return htmx_error(message='Already exists or invalid data.', retarget=retarget,
                          flash_title=f'Error adding {pretty}. It might already exist.',
                          redirect_to=list_url)

    body, oob_clear_id = (None, None)
    if is_htmx():
        body, oob_clear_id = _setting_success_body(item_type, item, form)
    return htmx_or_redirect(
        body=body, oob_clear_id=oob_clear_id,
        flash_message=f'{pretty.title()} "{form.name.data}" added.',
        redirect_to=list_url,
    )


@main_bp.route('/settings/<item_type>/<int:item_id>/update', methods=['POST'])
def update_setting(item_type, item_id):
    item = SETTINGS_MAP[item_type]['model'].query.get_or_404(item_id)
    form = SETTINGS_MAP[item_type]['form'](obj=item)
    list_url = url_for('main.list_settings')
    retarget = f'#error-{item_type}'

    if not form.validate_on_submit():
        return htmx_error(message='Update failed', form=form,
                          retarget=retarget,
                          flash_title='Could not update setting',
                          redirect_to=list_url)

    form.populate_obj(item)
    try:
        db.session.commit()
    except sqlalchemy.exc.IntegrityError:
        db.session.rollback()
        return htmx_error(message='Update failed: It might already exist.',
                          retarget=retarget,
                          flash_title='Update failed: It might already exist.',
                          redirect_to=list_url)

    body, oob_clear_id = (None, None)
    if is_htmx():
        body, oob_clear_id = _setting_success_body(item_type, item, form)
    return htmx_or_redirect(
        body=body, oob_clear_id=oob_clear_id,
        flash_message='Updated successfully!',
        redirect_to=list_url,
    )


@main_bp.route('/settings/<item_type>/<int:item_id>/delete', methods=['POST'])
def delete_setting(item_type, item_id):
    Model = SETTINGS_MAP[item_type]['model']
    item = Model.query.get_or_404(item_id)
    item_name = item.name
    pretty = item_type.replace("_", " ")
    list_url = url_for('main.list_settings')
    try:
        db.session.delete(item)
        db.session.commit()
    except sqlalchemy.exc.IntegrityError:
        db.session.rollback()
        return htmx_error(
            message=f'Cannot delete {item_name} (referenced elsewhere).',
            oob_id=f'error-{item_type}', status=200,
            flash_title=f'Cannot delete {item_name} since other objects reference this setting.',
            redirect_to=list_url,
        )

    body = None
    if is_htmx() and hasattr(Model, 'parent_id'):
        body = _render_nested_section(item_type)
    return htmx_or_redirect(
        body=body or '',
        flash_message=f'{pretty.title()} deleted.',
        redirect_to=list_url,
    )

@main_bp.route('/settings/feed/create', methods=['POST'])
def create_feed():
    form = FeedForm()
    if form.validate_on_submit():
        feed = models.Feed()
        form.populate_obj(feed)
        db.session.add(feed)
        db.session.commit()
        flash(f'Feed "{feed.name}" added.', 'success')
    else:
        flash_form_errors(form, title="Could not create feed")
    return redirect(request.referrer or url_for('main.list_settings'))

@main_bp.route('/set-species/<species_id>', methods=['POST'])
def set_species(species_id):
    from ..forms import CSRFOnlyForm
    form = CSRFOnlyForm()
    if not form.validate_on_submit():
        abort(400)
    session['selected_species'] = species_id
    return redirect(request.referrer or url_for('main.view_dashboard'))

def _save_datatype_children(dt):
    """Persist DataLocation rows from request.form.

    The form submits parallel ``locations`` / ``location_ids`` lists.
    Rows with an existing id get their ``base_path`` updated in place so
    attached ``Data`` rows aren't cascade-deleted — important when
    relocating the database to a new system whose root path differs but
    whose relative tree is intact.
    """
    submitted_paths = request.form.getlist('locations')
    submitted_ids = request.form.getlist('location_ids')

    existing_locs = {loc.id: loc for loc in dt.locations.all()}
    seen_ids = set()

    for loc_id_str, path in zip(submitted_ids, submitted_paths):
        path = path.strip()
        if not path:
            continue
        try:
            loc_id = int(loc_id_str)
        except (TypeError, ValueError):
            loc_id = None
        if loc_id and loc_id in existing_locs:
            existing_locs[loc_id].base_path = path
            seen_ids.add(loc_id)
        else:
            db.session.add(models.DataLocation(base_path=path, datatype_id=dt.id))

    for loc_id, loc in existing_locs.items():
        if loc_id not in seen_ids:
            db.session.delete(loc)


@main_bp.route('/settings/datatype/create_modal')
def create_datatype_modal():
    target_type = request.args.get('target_type')
    if target_type:
        form = datatype_form_for(target_type)
        return render_template(
            'partials/form_datatype_modal.html',
            form=form, dt=None, target_type=target_type,
            target_labels=DATATYPE_TARGET_LABELS,
        )
    return render_template(
        'partials/form_datatype_modal.html',
        form=None, dt=None, target_type=None,
        target_labels=DATATYPE_TARGET_LABELS,
    )


@main_bp.route('/settings/datatype/create', methods=['POST'])
def create_datatype():
    list_url = url_for('main.list_settings')
    retarget = '#datatype-error'

    target_type = request.form.get('target_type')
    if target_type not in DATATYPE_FORMS:
        return htmx_error(message='Pick a target type first.', retarget=retarget,
                          redirect_to=list_url)

    form = datatype_form_for(target_type)
    if not form.validate_on_submit():
        return htmx_error(message='Validation failed', form=form, retarget=retarget,
                          flash_title='Could not create DataType', redirect_to=list_url)

    if models.DataType.query.filter_by(name=form.name.data).first():
        return htmx_error(message='This DataType already exists.', retarget=retarget,
                          redirect_to=list_url)

    try:
        dt_class = models.DATATYPE_SUBCLASSES[target_type]
        dt = dt_class()
        form.populate_obj(dt)
        db.session.add(dt)
        db.session.flush()
        _save_datatype_children(dt)
        db.session.commit()
    except sqlalchemy.exc.IntegrityError:
        db.session.rollback()
        return htmx_error(message='Already exists or invalid data.', retarget=retarget,
                          flash_title='Error adding DataType. It might already exist.',
                          redirect_to=list_url)

    return htmx_or_redirect(
        partial='partials/datatype_list_item.html', context={'dt': dt},
        trigger='datatype-created',
        flash_message=f'DataType "{dt.name}" added. Click the sync button to import files.',
        redirect_to=list_url,
    )


@main_bp.route('/settings/datatype/<int:datatype_id>/edit_modal')
def edit_datatype_modal(datatype_id):
    dt = models.DataType.query.get_or_404(datatype_id)
    form = datatype_form_for(dt.target_type, obj=dt)
    return render_template(
        'partials/form_datatype_modal.html',
        form=form, dt=dt, target_type=dt.target_type,
        target_labels=DATATYPE_TARGET_LABELS,
    )


@main_bp.route('/settings/datatype/<int:datatype_id>/update', methods=['POST'])
def update_datatype(datatype_id):
    dt = models.DataType.query.get_or_404(datatype_id)
    form = datatype_form_for(dt.target_type)
    list_url = url_for('main.list_settings')
    retarget = '#datatype-error'

    if not form.validate_on_submit():
        return htmx_error(message='Update failed', form=form, retarget=retarget,
                          flash_title='Could not update DataType', redirect_to=list_url)

    form.populate_obj(dt)
    _save_datatype_children(dt)
    try:
        db.session.commit()
    except sqlalchemy.exc.IntegrityError:
        db.session.rollback()
        return htmx_error(message='Update failed: It might already exist.',
                          retarget=retarget,
                          flash_title='Update failed: It might already exist.',
                          redirect_to=list_url)

    return htmx_or_redirect(
        partial='partials/datatype_list_item.html', context={'dt': dt},
        trigger='datatype-updated',
        flash_message='DataType updated successfully!',
        redirect_to=list_url,
    )


@main_bp.route('/settings/datatype/<int:datatype_id>/sync', methods=['POST'])
def sync_datatype(datatype_id):
    """Queue a background sync_locations run for one DataType."""
    dt = models.DataType.query.get_or_404(datatype_id)
    if not dt.description_class or not dt.locations.count():
        flash(
            f'Cannot sync "{dt.name}": needs a description class and at '
            f'least one location.',
            'warning',
        )
        return redirect(url_for('main.list_settings'))
    enqueue_datatype_sync(dt.id)
    flash(f'Sync for "{dt.name}" queued. See status below.', 'info')
    return redirect(url_for('main.list_settings', _anchor='setting-jobs'))


@main_bp.route('/settings/datatype/<int:datatype_id>/rematch', methods=['POST'])
def rematch_datatype(datatype_id):
    """Queue a background rematch run for a DataType's Data files.

    Pass ``?force=1`` to walk every row (clearing existing target links,
    candidate animals, and candidate ears before re-resolving). Without
    it, only currently-unmatched rows are touched. Returns immediately —
    progress shows up in the recent-jobs panel on the settings page.
    """
    dt = models.DataType.query.get_or_404(datatype_id)
    force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
    enqueue_datatype_rematch(dt.id, force=force)
    label = 'Force-rematch' if force else 'Rematch'
    flash(f'{label} for "{dt.name}" queued in background.', 'info')
    return redirect(url_for('main.list_settings', _anchor='setting-jobs'))


@main_bp.route('/settings/datatype/<int:datatype_id>/delete', methods=['POST'])
def delete_datatype(datatype_id):
    dt = models.DataType.query.get_or_404(datatype_id)
    list_url = url_for('main.list_settings')
    if dt.data_files.count() > 0:
        return htmx_error(
            message='Cannot delete (linked to files).',
            oob_id='error-datatypes', status=200,
            flash_title=f'Cannot delete DataType "{dt.name}" because it is currently linked to files.',
            redirect_to=list_url,
        )

    name = dt.name
    db.session.delete(dt)
    db.session.commit()
    return htmx_or_redirect(
        body='',
        flash_message=f'DataType "{name}" deleted.',
        redirect_to=list_url,
    )


