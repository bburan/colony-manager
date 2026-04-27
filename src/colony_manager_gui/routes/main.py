from urllib.parse import urlparse, urljoin
import sqlalchemy
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import current_user, login_user
from datetime import date, timedelta

from colony_manager import models

from .. import db
from .. import forms
from ..forms import FeedForm, SimpleAddForm, SimpleAddWithDescriptionForm, DataTypeForm, DataLocationForm
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
        panels=models.ImmunolabelingPanel.query.all(),
        simple_add_form=SimpleAddForm(),
        simple_add_with_description_form=SimpleAddWithDescriptionForm(),
        settings=settings,
        datatypes=models.DataType.query.all(),
        datatype_form=DataTypeForm(),
        DataTypeForm=DataTypeForm,
        datalocation_form=DataLocationForm(),
    )


@main_bp.route('/settings/<item_type>/create', methods=['POST'])
def create_setting(item_type):
    Model = SETTINGS_MAP[item_type]['model']
    form = SETTINGS_MAP[item_type]['form']()
    if form.validate_on_submit():
        if Model.query.filter(Model.name == form.name.data).first():
            flash(f'Error adding {item_type.replace("_", " ")}. It might already exist.', 'danger')
        else:
            item = Model()
            form.populate_obj(item)
            db.session.add(item)
            db.session.commit()
            flash(f'{item_type.replace("_", " ").title()} "{form.name.data}" added.', 'success')
    else:
        flash_form_errors(form, title="Could not create setting")
    return redirect(request.referrer or url_for('main.list_settings'))


@main_bp.route('/settings/<item_type>/<int:item_id>/update', methods=['POST'])
def update_setting(item_type, item_id):
    item = SETTINGS_MAP[item_type]['model'].query.get_or_404(item_id)
    form = SETTINGS_MAP[item_type]['form']()
    if form.validate_on_submit():
        form.populate_obj(item)
        db.session.commit()
        flash("Updated successfully!", "success")
    else:
        flash_form_errors(form, title="Could not update setting")
    return redirect(request.referrer or url_for('main.list_settings'))


@main_bp.route('/settings/<item_type>/<int:item_id>/delete', methods=['POST'])
def delete_setting(item_type, item_id):
    item = SETTINGS_MAP[item_type]['model'].query.get_or_404(item_id)
    item_name = item.name
    try:
        db.session.delete(item)
        db.session.commit()
        flash(f'{item_type.replace("_", " ").title()} deleted.', 'success')
    except sqlalchemy.exc.IntegrityError:
        flash(f'Cannot delete {item_name} since other objects reference this setting.', 'danger')
    return redirect(request.referrer or url_for('main.list_settings'))


@main_bp.route('/settings/panel/delete/<int:panel_id>', methods=['POST'])
def delete_panel(panel_id):
    panel = models.ImmunolabelingPanel.query.get_or_404(panel_id)
    if panel.ears:
        flash(f'Cannot delete "{panel.name}" because it is in use on at least one ear.', 'danger')
        return redirect(url_for('settings'))
    db.session.delete(panel)
    db.session.commit()
    flash(f'Panel "{panel.name}" deleted.', 'success')
    return redirect(url_for('settings'))


@main_bp.route('/settings/reagent/new/<int:panel_id>', methods=['POST'])
def add_reagent(panel_id):
    form = SimpleAddWithDescriptionForm()
    panel = models.ImmunolabelingPanel.query.get_or_404(panel_id)
    if form.validate_on_submit():
        reagent = Reagent(name=form.name.data, description=form.description.data, panel_id=panel.id)
        db.session.add(reagent)
        db.session.commit()
        flash(f'Reagent "{reagent.name}" added to panel "{panel.name}".', 'success')
    else:
        flash('Could not add reagent. Please check the form.', 'danger')
    return redirect(url_for('settings'))

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

@main_bp.route('/settings/datatype/create', methods=['POST'])
def create_datatype():
    form = DataTypeForm()
    if form.validate_on_submit():
        if models.DataType.query.filter_by(name=form.name.data).first():
            flash('This DataType already exists.', 'danger')
        else:
            dt = models.DataType()
            form.populate_obj(dt)
            db.session.add(dt)
            db.session.commit()
            flash(f'DataType "{dt.name}" added.', 'success')
    else:
        flash_form_errors(form, title="Could not create DataType")
    return redirect(url_for('main.list_settings'))

@main_bp.route('/settings/datatype/<int:datatype_id>/update', methods=['POST'])
def update_datatype(datatype_id):
    dt = models.DataType.query.get_or_404(datatype_id)
    form = DataTypeForm()
    if form.validate_on_submit():
        form.populate_obj(dt)
        db.session.commit()
        flash("DataType updated successfully!", "success")
    return redirect(url_for('main.list_settings'))

@main_bp.route('/settings/datatype/<int:datatype_id>/delete', methods=['POST'])
def delete_datatype(datatype_id):
    dt = models.DataType.query.get_or_404(datatype_id)
    if dt.data_files.count() > 0:
        flash(f'Cannot delete DataType "{dt.name}" because it is currently linked to files.', 'danger')
    else:
        db.session.delete(dt)
        db.session.commit()
        flash(f'DataType "{dt.name}" deleted.', 'success')
    return redirect(url_for('main.list_settings'))

@main_bp.route('/settings/datalocation/new/<int:datatype_id>', methods=['POST'])
def add_datalocation(datatype_id):
    form = DataLocationForm()
    dt = models.DataType.query.get_or_404(datatype_id)
    if form.validate_on_submit():
        loc = models.DataLocation(base_path=form.base_path.data, datatype_id=dt.id)
        db.session.add(loc)
        db.session.commit()
        flash(f'Location added to "{dt.name}".', 'success')
    return redirect(url_for('main.list_settings'))

@main_bp.route('/settings/datalocation/<int:location_id>/update', methods=['POST'])
def update_datalocation(location_id):
    loc = models.DataLocation.query.get_or_404(location_id)
    form = DataLocationForm()
    if form.validate_on_submit():
        form.populate_obj(loc)
        db.session.commit()
    return redirect(url_for('main.list_settings'))

@main_bp.route('/settings/datalocation/<int:location_id>/delete', methods=['POST'])
def delete_datalocation(location_id):
    loc = models.DataLocation.query.get_or_404(location_id)
    db.session.delete(loc)
    db.session.commit()
    return redirect(url_for('main.list_settings'))
