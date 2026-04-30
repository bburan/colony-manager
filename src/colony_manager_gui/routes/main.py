from urllib.parse import urlparse, urljoin
import sqlalchemy
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import current_user, login_user
from datetime import date, timedelta

from colony_manager import models

from .. import db
from .. import forms
from ..forms import (
    FeedForm, SimpleAddForm, SimpleAddWithDescriptionForm, DataTypeForm,
    DataLocationForm, DATATYPE_FORMS, DATATYPE_TARGET_LABELS, datatype_form_for,
)
from .util import flash_form_errors

main_bp = Blueprint('main', __name__)

SETTINGS_MAP = {
    'species': {'model': models.Species, 'form': forms.SimpleAddForm},
    'source': {'model': models.Source, 'form': forms.SimpleAddForm},
    'confocal_image_type': {'model': models.ConfocalImageType, 'form': forms.SimpleAddForm},
    'termination_reason': {'model': models.TerminationReason, 'form': forms.SimpleAddForm},
    'animal_procedure': {'model': models.AnimalProcedure, 'form': forms.create_nested_form(models.AnimalProcedure)},
    'animal_procedure_target': {'model': models.AnimalProcedureTarget, 'form': forms.SimpleAddForm},
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
    upcoming_events = models.AnimalEvent.query.filter(
        models.AnimalEvent.completion_date == None,
        models.AnimalEvent.scheduled_date <= today + timedelta(days=7)
    ).order_by(models.AnimalEvent.scheduled_date.asc()).all()

    # Animals terminated in the last 30 days
    recent_terminations = models.Animal.query.filter(
        models.Animal.termination_date >= (date.today() - timedelta(days=7))
    ).order_by(models.Animal.termination_date.desc())

    upcoming_litters = models.Litter.query.filter(models.Litter.wean_date == None).order_by(models.Litter.dob).all()

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

    image_analysis_pending = models.ConfocalImage.query.filter_by(status='pending')
    image_analysis_review = models.ConfocalImage.query.filter_by(status='need_review')

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
    events = models.AnimalEvent.query.all()
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
    return render_template(
        'view_settings.html',
        simple_add_form=SimpleAddForm(),
        simple_add_with_description_form=SimpleAddWithDescriptionForm(),
        settings=settings,
        datatypes=models.DataType.query.all(),
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
                    return f'<div class="alert alert-danger small py-1 mb-0">Already exists or invalid data.</div>', 400, {'HX-Retarget': f'#error-{item_type}'}
                flash(f'Error adding {item_type.replace("_", " ")}. It might already exist.', 'danger')
    else:
        if request.headers.get('HX-Request'):
            return f'<div class="alert alert-danger small py-1 mb-0">Validation failed: {form.errors}</div>', 400, {'HX-Retarget': f'#error-{item_type}'}
        flash_form_errors(form, title="Could not create setting")
    return redirect(request.referrer or url_for('main.list_settings'))


@main_bp.route('/settings/<item_type>/<int:item_id>/update', methods=['POST'])
def update_setting(item_type, item_id):
    item = SETTINGS_MAP[item_type]['model'].query.get_or_404(item_id)
    form = SETTINGS_MAP[item_type]['form']()
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
                return f'<div class="alert alert-danger small py-1 mb-0">Update failed: It might already exist.</div>', 400, {'HX-Retarget': f'#error-{item_type}'}
            flash("Update failed: It might already exist.", "danger")
    else:
        if request.headers.get('HX-Request'):
            return f'<div class="alert alert-danger small py-1 mb-0">Update failed: {form.errors}</div>', 400, {'HX-Retarget': f'#error-{item_type}'}
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
            return f'<div class="alert alert-danger small py-1 mb-0" hx-swap-oob="true" id="error-{item_type}">Cannot delete {item_name} (referenced elsewhere).</div>', 200
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

@main_bp.route('/set-species/<species_id>')
def set_species(species_id):
    session['selected_species'] = species_id
    return redirect(request.referrer or url_for('main.view_dashboard'))

def _save_datatype_children(dt):
    """Persist DataLocation rows and DataTypeCallback rows from request.form."""
    location_paths = [p.strip() for p in request.form.getlist('locations') if p.strip()]
    for loc in dt.locations.all():
        if loc.base_path not in location_paths:
            db.session.delete(loc)
    existing_paths = {loc.base_path for loc in dt.locations.all()}
    for path in location_paths:
        if path not in existing_paths:
            db.session.add(models.DataLocation(base_path=path, datatype_id=dt.id))

    for cb in dt.callbacks.all():
        db.session.delete(cb)
    names = request.form.getlist('callback_name')
    funcs = request.form.getlist('callback_function')
    types = request.form.getlist('callback_type')
    for n, f, t in zip(names, funcs, types):
        if n.strip() and f.strip():
            db.session.add(models.DataTypeCallback(
                datatype_id=dt.id,
                name=n.strip(),
                callback_function=f.strip(),
                callback_type=t,
            ))


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
            return '<div class="alert alert-danger py-2 small">Pick a target type first.</div>', 200, {'HX-Retarget': '#datatype-error'}
        flash('Pick a target type first.', 'danger')
        return redirect(url_for('main.list_settings'))

    form = datatype_form_for(target_type)
    if form.validate_on_submit():
        if models.DataType.query.filter_by(name=form.name.data).first():
            if request.headers.get('HX-Request'):
                return '<div class="alert alert-danger py-2 small">This DataType already exists.</div>', 200, {'HX-Retarget': '#datatype-error'}
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
                if request.headers.get('HX-Request'):
                    response = render_template('partials/datatype_list_item.html', dt=dt)
                    return response, {'HX-Trigger': 'datatype-created'}
                flash(f'DataType "{dt.name}" added.', 'success')
            except sqlalchemy.exc.IntegrityError:
                db.session.rollback()
                if request.headers.get('HX-Request'):
                    return '<div class="alert alert-danger py-2 small">Already exists or invalid data.</div>', 200, {'HX-Retarget': '#datatype-error'}
                flash(f'Error adding DataType. It might already exist.', 'danger')
    else:
        if request.headers.get('HX-Request'):
            return f'<div class="alert alert-danger py-2 small">Validation failed: {form.errors}</div>', 200, {'HX-Retarget': '#datatype-error'}
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
            if request.headers.get('HX-Request'):
                response = render_template('partials/datatype_list_item.html', dt=dt)
                return response, {'HX-Trigger': 'datatype-updated'}
            flash("DataType updated successfully!", "success")
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()
            if request.headers.get('HX-Request'):
                return '<div class="alert alert-danger py-2 small">Update failed: It might already exist.</div>', 200, {'HX-Retarget': '#datatype-error'}
            flash("Update failed: It might already exist.", "danger")
    else:
        if request.headers.get('HX-Request'):
            return f'<div class="alert alert-danger py-2 small">Update failed: {form.errors}</div>', 200, {'HX-Retarget': '#datatype-error'}
        flash_form_errors(form, title="Could not update DataType")
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


