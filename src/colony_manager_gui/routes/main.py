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
from .util import flash_form_errors, render_error_alert
from colony_manager.datatypes import load_description_class
from ..sync import sync_locations, rematch_datatype as _rematch_datatype
from ..jobs import (
    enqueue_datatype_sync, enqueue_datatype_rematch,
    recent_jobs, parse_summary,
)

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
    'immunolabeling_panel': {'model': models.ImmunolabelingPanel, 'form': forms.SimpleAddWithDescriptionForm},
}

@main_bp.route('/')
def view_dashboard():
    today = date.today()

    # 1. Metrics for Top Cards
    active_cages_count = models.Species.count_active_cages()
    active_animals_count = models.Species.count_active_animals()
    ears_for_processing_count = models.Species.count_unprocessed_ears()
    active_breeding_pairs_count = models.Species.count_active_breeding_pairs()

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


@main_bp.route('/settings/<item_type>/create', methods=['POST'])
def create_setting(item_type):
    Model = SETTINGS_MAP[item_type]['model']
    form = SETTINGS_MAP[item_type]['form']()
    if form.validate_on_submit():
        if Model.query.filter(Model.name == form.name.data).first():
            if request.headers.get('HX-Request'):
                return f'<div class="alert alert-danger small py-1 mb-0">Already exists.</div>', 400, {'HX-Retarget': f'#error-{item_type}'}
            flash(f'Error adding {item_type.replace("_", " ")}. It might already exist.', 'danger')
        else:
            try:
                item = Model()
                form.populate_obj(item)
                db.session.add(item)
                db.session.commit()
                if request.headers.get('HX-Request'):
                    display_form = SETTINGS_MAP[item_type]['form'](obj=item)
                    html = render_template('partials/setting_list_item.html', type=item_type, item=item, form=display_form)
                    # Clear error div
                    error_clear = f'<div id="error-{item_type}" hx-swap-oob="true"></div>'
                    return html + error_clear
                flash(f'{item_type.replace("_", " ").title()} "{form.name.data}" added.', 'success')
            except sqlalchemy.exc.IntegrityError:
                db.session.rollback()
                if request.headers.get('HX-Request'):
                    return render_error_alert(message='Already exists or invalid data.', alert_class='small py-1'), 400, {'HX-Retarget': f'#error-{item_type}'}
                flash(f'Error adding {item_type.replace("_", " ")}. It might already exist.', 'danger')
    else:
        if request.headers.get('HX-Request'):
            return render_error_alert(message='Validation failed', form=form, alert_class='small py-1'), 400, {'HX-Retarget': f'#error-{item_type}'}
        flash_form_errors(form, title="Could not create setting")
    return redirect(request.referrer or url_for('main.list_settings'))


@main_bp.route('/settings/<item_type>/<int:item_id>/update', methods=['POST'])
def update_setting(item_type, item_id):
    item = SETTINGS_MAP[item_type]['model'].query.get_or_404(item_id)
    form = SETTINGS_MAP[item_type]['form'](obj=item)
    if form.validate_on_submit():
        form.populate_obj(item)
        try:
            db.session.commit()
            if request.headers.get('HX-Request'):
                display_form = SETTINGS_MAP[item_type]['form'](obj=item)
                html = render_template('partials/setting_list_item.html', type=item_type, item=item, form=display_form)
                # Clear error too
                error_clear = f'<div id="error-{item_type}" hx-swap-oob="true"></div>'
                return html + error_clear
            flash("Updated successfully!", "success")
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()
            if request.headers.get('HX-Request'):
                return render_error_alert(message='Update failed: It might already exist.', alert_class='small py-1'), 400, {'HX-Retarget': f'#error-{item_type}'}
            flash("Update failed: It might already exist.", "danger")
    else:
        if request.headers.get('HX-Request'):
            return render_error_alert(message='Update failed', form=form, alert_class='small py-1'), 400, {'HX-Retarget': f'#error-{item_type}'}
        flash_form_errors(form, title="Could not update setting")
    return redirect(request.referrer or url_for('main.list_settings'))


@main_bp.route('/settings/<item_type>/<int:item_id>/delete', methods=['POST'])
def delete_setting(item_type, item_id):
    item = SETTINGS_MAP[item_type]['model'].query.get_or_404(item_id)
    item_name = item.name
    try:
        db.session.delete(item)
        db.session.commit()
        if request.headers.get('HX-Request'):
            return ''
        flash(f'{item_type.replace("_", " ").title()} deleted.', 'success')
    except sqlalchemy.exc.IntegrityError:
        if request.headers.get('HX-Request'):
            return render_error_alert(message=f'Cannot delete {item_name} (referenced elsewhere).', alert_class='small py-1', oob_id=f'error-{item_type}'), 200
        flash(f'Cannot delete {item_name} since other objects reference this setting.', 'danger')
    return redirect(request.referrer or url_for('main.list_settings'))

@main_bp.route('/settings/feed/create', methods=['POST'])
def create_feed():
    form = FeedForm()
    if form.validate_on_submit():
        feed = Feed()
        form.populate_obj(feed)
        db.session.add(feed)
        db.session.commit()
        flash(f'Feed "{feed.name}" added.', 'success')
    else:
        flash_form_errors(form, title="Could not create feed")
    return redirect(request.referrer or url_for('list_settings'))

@main_bp.route('/set-species/<species_id>', methods=['POST'])
def set_species(species_id):
    from ..forms import CSRFOnlyForm
    form = CSRFOnlyForm()
    if not form.validate_on_submit():
        abort(400)
    session['selected_species'] = species_id
    return redirect(request.referrer or url_for('main.view_dashboard'))

def _autosync_datatype(dt):
    """Queue a background sync for one DataType.

    No-ops when the DataType has no description_class or no locations
    configured (nothing for sync to do). Returns immediately so the
    request thread isn't tied up walking the filesystem.
    """
    if not dt.description_class or not dt.locations.count():
        return
    enqueue_datatype_sync(dt.id)
    flash(f'Sync for "{dt.name}" queued in background.', 'info')


def _save_datatype_children(dt):
    """Persist DataLocation rows from request.form."""
    location_paths = [p.strip() for p in request.form.getlist('locations') if p.strip()]
    for loc in dt.locations.all():
        if loc.base_path not in location_paths:
            db.session.delete(loc)
    existing_paths = {loc.base_path for loc in dt.locations.all()}
    for path in location_paths:
        if path not in existing_paths:
            db.session.add(models.DataLocation(base_path=path, datatype_id=dt.id))


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
    target_type = request.form.get('target_type')
    if target_type not in DATATYPE_FORMS:
        if request.headers.get('HX-Request'):
            return render_error_alert(message='Pick a target type first.'), 200, {'HX-Retarget': '#datatype-error'}
        flash('Pick a target type first.', 'danger')
        return redirect(url_for('main.list_settings'))

    form = datatype_form_for(target_type)
    if form.validate_on_submit():
        if models.DataType.query.filter_by(name=form.name.data).first():
            if request.headers.get('HX-Request'):
                return render_error_alert(message='This DataType already exists.'), 200, {'HX-Retarget': '#datatype-error'}
            flash('This DataType already exists.', 'danger')
        else:
            try:
                dt_class = models.DATATYPE_SUBCLASSES[target_type]
                dt = dt_class()
                form.populate_obj(dt)
                db.session.add(dt)
                db.session.flush()
                _save_datatype_children(dt)
                db.session.commit()
                _autosync_datatype(dt)
                if request.headers.get('HX-Request'):
                    response = render_template('partials/datatype_list_item.html', dt=dt)
                    return response, {'HX-Trigger': 'datatype-created'}
                flash(f'DataType "{dt.name}" added.', 'success')
            except sqlalchemy.exc.IntegrityError:
                db.session.rollback()
                if request.headers.get('HX-Request'):
                    return render_error_alert(message='Already exists or invalid data.'), 200, {'HX-Retarget': '#datatype-error'}
                flash(f'Error adding DataType. It might already exist.', 'danger')
    else:
        if request.headers.get('HX-Request'):
            return render_error_alert(message='Validation failed', form=form), 200, {'HX-Retarget': '#datatype-error'}
        flash_form_errors(form, title="Could not create DataType")
    return redirect(url_for('main.list_settings'))


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
    if form.validate_on_submit():
        form.populate_obj(dt)
        _save_datatype_children(dt)
        try:
            db.session.commit()
            _autosync_datatype(dt)
            if request.headers.get('HX-Request'):
                response = render_template('partials/datatype_list_item.html', dt=dt)
                return response, {'HX-Trigger': 'datatype-updated'}
            flash("DataType updated successfully!", "success")
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()
            if request.headers.get('HX-Request'):
                return render_error_alert(message='Update failed: It might already exist.'), 200, {'HX-Retarget': '#datatype-error'}
            flash("Update failed: It might already exist.", "danger")
    else:
        if request.headers.get('HX-Request'):
            return render_error_alert(message='Update failed', form=form), 200, {'HX-Retarget': '#datatype-error'}
        flash_form_errors(form, title="Could not update DataType")
    return redirect(url_for('main.list_settings'))


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
    return redirect(url_for('main.list_settings'))


@main_bp.route('/settings/datatype/<int:datatype_id>/delete', methods=['POST'])
def delete_datatype(datatype_id):
    dt = models.DataType.query.get_or_404(datatype_id)
    if dt.data_files.count() > 0:
        if request.headers.get('HX-Request'):
            return f'<div class="alert alert-danger small py-1 mb-0" hx-swap-oob="true" id="error-datatypes">Cannot delete (linked to files).</div>', 200
        flash(f'Cannot delete DataType "{dt.name}" because it is currently linked to files.', 'danger')
    else:
        db.session.delete(dt)
        db.session.commit()
        if request.headers.get('HX-Request'):
            return ''
        flash(f'DataType "{dt.name}" deleted.', 'success')
    return redirect(url_for('main.list_settings'))


