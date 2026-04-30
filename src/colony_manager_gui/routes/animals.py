import datetime
import re

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, Response, send_file
from colony_manager.models import Animal, AnimalEvent, AnimalProcedure, Cage, Study, Ear, Feed, FeedLog, WeightLog, Data, DataType

from .. import db
from .. import forms
from .. import models
from ..forms import AnimalForm, AnimalEventForm, AnimalEventEditForm, AnimalCustomIDForm, NoteForm, TerminationForm, QuickAddToStudyForm, DailyLogForm, mark_disabled, mark_readonly
from .util import flash_form_errors


animals_bp = Blueprint('animals', __name__)


@animals_bp.route('/')
def list_animals():
    sort_by = request.args.get('sort_by', 'id')
    event_filter = request.args.get('event_filter', 'all')
    status_filter = request.args.get('status_filter', 'active')
    study_filter = request.args.get('study_filter', 'all')
    age_unit = request.args.get('age_unit', 'day')
    search_query = request.args.get('search_query', '')

    query = Animal.query.filter(Animal.custom_id.is_not(None))

    species_id = int(session.get('selected_species', -1))
    if species_id != -1:
        query = query.filter(Animal.species_id==species_id)

    if search_query:
        # We join Events and Procedures to allow searching by procedure name
        # .ilike(f'%{search_query}%') handles the "partial match" requirement
        query = query.join(Animal.events, isouter=True).join(AnimalEvent.procedure, isouter=True).filter(
            db.or_(
                Animal.custom_id.ilike(f'%{search_query}%'),
                AnimalProcedure.name.ilike(f'%{search_query}%')
            )
        )

    if status_filter == 'active':
        query = query.filter(Animal.termination_date.is_(None))
    elif status_filter == 'terminated':
        query = query.filter(Animal.termination_date.is_not(None))
    if study_filter != 'all':
        query = query.join(Animal.studies).filter(Study.id == int(study_filter))

    animals = query.all()
    if sort_by == 'age':
        animals.sort(key=lambda a: a.age_in_days)
    elif sort_by == 'event_date':
        animals.sort(key=lambda a: a.last_event_date, reverse=True)
    else:
        animals.sort(key=lambda a: a.custom_id)

    if event_filter == 'all':
        pass
    elif event_filter == 'has_events':
        animals = [a for a in animals if a.has_events]
    elif event_filter == 'no_events':
        animals = [a for a in animals if not a.has_events]
    elif event_filter == 'due_overdue':
        animals = [a for a in animals if (a.event_due or a.event_overdue)]
    elif event_filter == 'overdue':
        animals = [a for a in animals if a.event_overdue]

    return render_template(
        'animals.html',
        animals=animals,
        filters={
            'sort_by': sort_by,
            'status_filter': status_filter,
            'event_filter': event_filter,
            'study_filter': study_filter,
            'age_unit': age_unit,
            'search_query': search_query,
        },
    )


@animals_bp.route('/<int:animal_id>')
def view_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    feed = Feed.query.order_by(Feed.weight).all()
    return render_template(
        'view_animal.html',
        animal=animal,
        feeds=feed,
    )

@animals_bp.route('/create', methods=['POST'])
def create_animal():
    form = AnimalForm()
    if form.validate_on_submit():
        animal = Animal()
        form.populate_obj(animal)
        db.session.add(animal)
        db.session.commit()
        flash(f'Successfully created {animal.display_id}', 'success')
    else:
        flash_form_errors(form, 'Error creating animal')
    return redirect(request.referrer or url_for('animals.list_animals'))


@animals_bp.route('/<int:animal_id>/update', methods=['POST'])
def update_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = AnimalForm(obj=animal)
    if form.validate_on_submit():
        form.populate_obj(animal)
        if not form.custom_id.data:
            animal.custom_id = None
        db.session.commit()
        flash(f'Successfully updated {animal.display_id}', 'success')
    else:
        flash_form_errors(form, f'Error updating {animal.display_id}')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal_id))


@animals_bp.route('/<int:animal_id>/delete', methods=['POST'])
def delete_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    if animal.breeding_pair_male or animal.breeding_pair_female:
        flash(f'Cannot delete animal {animal.display_id} because it is part of a breeding pair.', 'danger')
        return redirect(request.referrer or url_for('animals.list_animals'))
    db.session.delete(animal)
    db.session.commit()
    flash(f'Animal {animal.display_id} has been deleted.', 'success')
    return redirect(request.referrer or url_for('animals.list_animals'))


@animals_bp.route('/<int:animal_id>/terminate', methods=['POST'])
def terminate_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = TerminationForm()
    if form.validate_on_submit():
        ears = form.ears_extracted.data
        if ears == 'None':
            ears = None
        try:
            new_ears = animal.terminate(
                termination_date=form.termination_date.data,
                termination_reason=form.termination_reason.data,
                ears_extracted=ears,
            )
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(request.referrer or url_for('animals.list_animals'))
        for ear in new_ears:
            db.session.add(ear)
        db.session.commit()
        flash(f'Animal {animal.display_id} has been marked as terminated.', 'success')
    else:
        flash_form_errors(form, f'Error terminating {animal.display_id}')
    return redirect(request.referrer or url_for('animals.list_animals'))

# Nested Event Routes
@animals_bp.route('/<int:animal_id>/events/create', methods=['POST'])
def create_animal_event(animal_id):
    form = AnimalEventForm()
    if form.validate_on_submit():
        event = AnimalEvent(animal_id=animal_id)
        event.procedure = form.procedure.data
        event.procedure_target = form.procedure_target.data
        event.notes = form.notes.data
        event.tags = form.tags.data
        if form.action.data == 'schedule':
            event.scheduled_date = form.date.data
        else:
            event.scheduled_date = form.date.data
            event.completion_date = form.date.data
        db.session.add(event)
        db.session.commit()
        flash('Event created successfully.', 'success')
    else:
        flash_form_errors(form, f'Error creating event')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal_id))

@animals_bp.route('/events/<int:event_id>/update', methods=['POST'])
def update_animal_event(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    form = AnimalEventEditForm()
    if form.validate_on_submit():
        form.populate_obj(event)
        db.session.commit()
        _resync_event_files(event)
        db.session.commit()
        flash('Event updated successfully.', 'success')
    else:
        flash_form_errors(form, f'Error updating event')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=event.animal_id))


def _resync_event_files(event):
    """Unlink files whose date no longer matches the event, then link matching unassigned files."""
    new_date = event.completion_date or event.scheduled_date

    # 1. Unlink files that no longer match this event's date
    for f in list(event.data_files):
        if f.date != new_date:
            f.event_id = None

    # 2. Link unassigned Data files that now match date + datatype.default_procedure + animal
    animal_ids = [a.id for a in event.animal.cage.animals]
    candidate_files = Data.query.filter(
        Data.event_id == None,
        Data.date == new_date,
    ).all()
    for f in candidate_files:
        if f.datatype.default_procedure_id != event.procedure_id:
            continue
        # Check if any of the file's animals matches this event's animal
        if any(a.id == event.animal_id for a in f.animals):
            f.event_id = event.id


@animals_bp.route('/events/<int:event_id>/delete', methods=['POST'])
def delete_animal_event(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    animal_id = event.animal_id  # Grab this to redirect back to the right page
    db.session.delete(event)
    db.session.commit()
    # Flash messages are great for feedback
    flash("Event deleted successfully.", "success")
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal_id))

@animals_bp.route('/<int:animal_id>/weight-feed/create', methods=['POST'])
def create_animal_daily_log(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = DailyLogForm()
    if form.validate_on_submit():
        print(form.date.data)
        logs = WeightLog.query.filter_by(animal_id=animal.id, date=form.date.data).all()
        if len(logs) != 0:
            flash(f'Log for {animal.display_id} already exists for {form.date.data.strftime("%B %d, %Y")}.', 'danger')
            return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal.id))

        weight = WeightLog(
            animal_id=animal.id,
            weight=form.weight.data,
            notes=form.notes.data,
            date=form.date.data,
            baseline=form.baseline.data,
        )
        db.session.add(weight)

        for feed_form in form.feedings:
            if feed_form.quantity.data and feed_form.quantity.data > 0:
                new_feeding = FeedLog(
                    animal_id=animal.id,
                    feed_id=feed_form.feed_id.data,
                    quantity=feed_form.quantity.data,
                    date=form.date.data,
                )
                db.session.add(new_feeding)
        db.session.commit()
        flash('Added new log', 'success')
    else:
        flash_form_errors(form, f'Error creating daily log')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal.id))

@animals_bp.route('/<int:animal_id>/<date>/weight-feed/delete', methods=['POST'])
def delete_animal_daily_log(animal_id, date):
    animal = Animal.query.get_or_404(animal_id)
    weight = WeightLog.query.filter_by(animal_id=animal.id, date=date).one_or_none()
    if weight is not None:
        db.session.delete(weight)
    for entry in FeedLog.query.filter_by(animal_id=animal.id, date=date):
        db.session.delete(entry)
    db.session.commit()
    flash('Daily log deleted successfully.', 'success')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal.id))

@animals_bp.route('/<int:animal_id>/<date>/weight-feed/update', methods=['POST'])
def update_animal_daily_log(animal_id, date):
    animal = Animal.query.get_or_404(animal_id)
    form = DailyLogForm()
    if form.validate_on_submit():
        weight = WeightLog.query.filter_by(animal_id=animal.id, date=date).one()
        weight.weight = form.weight.data
        weight.notes = form.notes.data
        weight.baseline = form.baseline.data
        for feed_form in form.feedings:
            feeding = FeedLog.query.filter_by(animal_id=animal.id, date=date, feed_id=feed_form.feed_id.data).one_or_none()
            if feeding is None:
                if feed_form.quantity.data > 0:
                    new_feeding = FeedLog(
                        animal_id=animal.id,
                        feed_id=feed_form.feed_id.data,
                        quantity=feed_form.quantity.data,
                        date=form.date.data,
                    )
                    db.session.add(new_feeding)
            else:
                if feed_form.quantity.data == 0:
                    db.session.delete(feeding)
                else:
                    feeding.quantity = feed_form.quantity.data
        db.session.commit()
        flash('Daily log updated successfully.', 'success')
    else:
        flash_form_errors(form, f'Error creating daily log')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal.id))


# --- Modal Routes ---
@animals_bp.route('/create_modal/<int:cage_id>')
def create_animal_modal(cage_id):
    cage = Cage.query.get_or_404(cage_id)
    animal = cage.animals.first()
    form = AnimalForm(
        cage=cage,
        dob=animal.dob,
        sex=animal.sex,
    )
    return render_template('partials/form_modal.html', form=form, item=None,
                           label='Create new animal', submit_url=url_for('animals.create_animal'))

@animals_bp.route('/<int:animal_id>/edit_modal')
def edit_animal_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = AnimalForm(obj=animal)
    return render_template('partials/form_modal.html', form=form, item=animal,
                           label=f'Edit {animal.display_id}', submit_url=url_for('animals.update_animal', animal_id=animal.id))

@animals_bp.route('/<int:animal_id>/assign_id_modal')
def assign_animal_id_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = AnimalCustomIDForm(custom_id=f'{animal.cage.custom_id}-')
    return render_template('partials/form_modal.html', form=form, item=animal,
                           label=f'Assign ID for {animal.display_id}', submit_url=url_for('animals.update_animal', animal_id=animal.id))

@animals_bp.route('/<int:animal_id>/edit_note_modal')
def edit_animal_note_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = NoteForm(obj=animal)
    return render_template('partials/form_modal.html', form=form, item=animal,
                           label=f'Edit note for {animal.display_id}', submit_url=url_for('animals.update_animal', animal_id=animal.id))

@animals_bp.route('/<int:animal_id>/terminate_modal')
def terminate_animal_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = TerminationForm(obj=animal)
    return render_template(
        'partials/form_modal.html', form=form, item=animal,
                           label=f'Remove {animal.display_id}', submit_url=url_for('animals.terminate_animal', animal_id=animal.id))

@animals_bp.route('/<int:animal_id>/quick_add_study_modal')
def add_study_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = QuickAddToStudyForm()
    return render_template(
        'partials/form_modal.html',
        form=form,
        item=animal,
        label=f'Add study for {animal.display_id}',
        submit_url=url_for('studies.add_study_animal', animal_id=animal.id))

# --- Animal Event Modals ---
@animals_bp.route('/<int:animal_id>/events/create_modal')
def create_animal_event_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = AnimalEventForm(animal=animal)
    return render_template('partials/form_event_modal.html', form=form, item=animal,
                           label=f'Create event for {animal.display_id}', submit_url=url_for('animals.create_animal_event', animal_id=animal.id))

@animals_bp.route('/events/<int:event_id>/edit_modal')
def edit_animal_event_modal(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    form = AnimalEventEditForm(obj=event)
    return render_template('partials/form_modal.html', form=form, item=event,
                           label=f'Edit event for {event.animal.display_id}', submit_url=url_for('animals.update_animal_event', event_id=event.id))

@animals_bp.route('/events/<int:event_id>/delete_modal')
def delete_animal_event_modal(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    form = AnimalEventEditForm(obj=event)
    mark_disabled(form)
    return render_template('partials/form_modal.html', form=form, item=event,
                           label=f'Remove event for {event.animal.display_id}', submit_url=url_for('animals.delete_animal_event', event_id=event.id))


# --- Animal Weight/Feed Modals ---
@animals_bp.route('/<int:animal_id>/weight-feed/create_modal')
@animals_bp.route('/<int:animal_id>/<date>/weight-feed/create_modal')
def create_animal_daily_log_modal(animal_id, date=None):
    disable_date = date is not None
    if date is not None:
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    else:
        date = datetime.date.today()
    animal = Animal.query.get_or_404(animal_id)
    feed = Feed.query.order_by(Feed.weight).all()
    feed_data = [{'feed_id': f.id, 'feed_name': f.name, 'feed_weight': f.weight, 'amount': 0} for f in feed]
    form = DailyLogForm(feedings=feed_data, date=date, current_baseline=animal.baseline_weight)
    if disable_date:
        mark_readonly(form, 'date')
    return render_template(
        'partials/form_daily_log_modal.html',
        form=form,
        item=animal,
        label=f'Add entry for {animal.display_id}',
        submit_url=url_for('animals.create_animal_daily_log', animal_id=animal.id)
    )

def _generate_daily_log_form(animal_id, date):
    date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    animal = Animal.query.get_or_404(animal_id)
    feed = Feed.query.order_by(Feed.weight).all()
    feed_data = []
    for f in feed:
        entry = FeedLog.query.filter_by(animal_id=animal.id, date=date, feed_id=f.id).one_or_none()
        feed_data.append({
            'feed_id': f.id,
            'feed_name': f.name,
            'feed_weight': f.weight,
            'quantity': entry.quantity if entry else 0,
        })

    weight_log = WeightLog.query.filter_by(animal_id=animal.id, date=date).one_or_none()
    if weight_log is not None:
        if weight_log.weight is not None and animal.baseline_weight is not None:
            current_baseline_pct = int(round(weight_log.weight / animal.baseline_weight * 100))
        else:
            current_baseline_pct = None
        weight_data = {
            'weight': weight_log.weight,
            'notes': weight_log.notes,
            'baseline': weight_log.baseline,
            'current_baseline_pct': current_baseline_pct,
        }
    else:
        weight_data = {}

    return animal, DailyLogForm(
        feedings=feed_data,
        date=date,
        current_baseline=animal.baseline_weight,
        **weight_data,
    )

@animals_bp.route('/<int:animal_id>/<date>/weight-feed/update_modal')
def update_animal_daily_log_modal(animal_id, date):
    animal, form = _generate_daily_log_form(animal_id, date)
    mark_disabled(form, 'date')
    return render_template(
        'partials/form_daily_log_modal.html',
        form=form,
        item=animal,
        label=f'Update entry for {animal.display_id}',
        submit_url=url_for('animals.update_animal_daily_log',
                           animal_id=animal.id,
                           date=date)
    )

@animals_bp.route('/<int:animal_id>/<date>/weight-feed/delete_modal')
def delete_animal_daily_log_modal(animal_id, date):
    animal, form = _generate_daily_log_form(animal_id, date)
    mark_disabled(form)
    return render_template(
        'partials/form_daily_log_modal.html',
        form=form,
        item=animal,
        label=f'Delete entry for {animal.display_id}',
        submit_url=url_for('animals.delete_animal_daily_log',
                           animal_id=animal.id,
                           date=date)
    )


# --- AJAX Popover Routes ---
@animals_bp.route('/<int:animal_id>/events_popover')
def view_animal_events_popover(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    return render_template(
        'partials/event_popover.html',
        animal=animal,
    )

@animals_bp.route('/<int:animal_id>/data/<int:data_id>/reassign', methods=['POST'])
def reassign_data(animal_id, data_id):
    data_file = Data.query.get_or_404(data_id)
    event_id = request.form.get('event_id')
    if event_id and event_id != '__None':
        data_file.event_id = int(event_id)
        flash(f"File {data_file.name} attached to event.", "success")
    else:
        data_file.event_id = None
        flash(f"File {data_file.name} detached from event.", "info")
    db.session.commit()
    return redirect(url_for('animals.view_animal', animal_id=animal_id))

@animals_bp.route('/unmatched-data')
def list_unmatched_data():
    """Shows all data files that were not matched to any Animal custom_id."""
    unmatched_files = Data.query.filter(~Data.animals.any()).all()
    return render_template(
        'unmatched_data.html',
        files=unmatched_files
    )

@animals_bp.route('/<int:animal_id>/data/<int:data_id>/set_status', methods=['POST'])
def set_data_status(animal_id, data_id):
    """Toggle the status of a Data file (reviewed / excluded / unreviewed)."""
    data_file = Data.query.get_or_404(data_id)
    new_status = request.form.get('status', 'unreviewed')
    data_file.status = new_status
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return {'status': 'success', 'new_status': data_file.status}

    return redirect(url_for('animals.view_animal', animal_id=animal_id))

@animals_bp.route('/<int:animal_id>/data/<int:data_id>/auto_create_event', methods=['POST'])
def auto_create_event(animal_id, data_id):
    """Auto-create an AnimalEvent for an unassigned Data file, then link all matching files."""
    data_file = Data.query.get_or_404(data_id)
    datatype = data_file.datatype

    if not datatype.default_procedure_id:
        flash('Cannot auto-create: DataType has no Default Procedure configured.', 'danger')
        return redirect(url_for('animals.view_animal', animal_id=animal_id))
    if not data_file.date:
        flash('Cannot auto-create: file has no parsed date.', 'danger')
        return redirect(url_for('animals.view_animal', animal_id=animal_id))

    # Create the event
    event = AnimalEvent(
        animal_id=animal_id,
        procedure_id=datatype.default_procedure_id,
        procedure_target_id=datatype.default_procedure_target_id,
        scheduled_date=data_file.date,
        completion_date=data_file.date,
    )
    db.session.add(event)
    db.session.flush()  # get event.id before full commit

    # Link all unassigned files with matching datatype, date, and animal
    candidate_files = Data.query.filter(
        Data.event_id == None,
        Data.datatype_id == datatype.id,
        Data.date == data_file.date,
    ).all()
    linked_count = 0
    for f in candidate_files:
        if any(a.id == animal_id for a in f.animals):
            f.event_id = event.id
            linked_count += 1

    db.session.commit()
    flash(f'Event created and {linked_count} file(s) linked.', 'success')
    return redirect(url_for('animals.view_animal', animal_id=animal_id))

@animals_bp.route('/data/<int:data_id>/plot/<int:callback_id>')
def plot_data(data_id, callback_id):
    """Invoke the datatype callback function and return plot data as JSON."""
    data_file = Data.query.get_or_404(data_id)
    callback = models.DataTypeCallback.query.get_or_404(callback_id)
    
    if callback.datatype_id != data_file.datatype_id:
        return jsonify({'error': 'Callback does not belong to this datatype.'}), 400

    import importlib
    try:
        module_name, func_name = callback.callback_function.rsplit('.', 1)
        module = importlib.import_module(module_name)
        loader = getattr(module, func_name)
    except Exception as e:
        return jsonify({'error': f'Failed to import callback function: {e}'}), 500

    try:
        plot_data_res = loader(data_file)
        if hasattr(plot_data_res, 'to_json'):
            # It's likely a Plotly Figure, which has .to_json()
            return Response(plot_data_res.to_json(), mimetype='application/json')
        else:
            return jsonify(plot_data_res)
    except Exception as e:
        return jsonify({'error': f'Error loading plot data: {str(e)}'}), 500

@animals_bp.route('/data/<int:data_id>/pdf/<int:callback_id>')
def view_data_pdf(data_id, callback_id):
    """Invoke the datatype callback function and return the PDF file."""
    data_file = Data.query.get_or_404(data_id)
    callback = models.DataTypeCallback.query.get_or_404(callback_id)

    if callback.datatype_id != data_file.datatype_id:
        return "Callback does not belong to this datatype.", 400

    import importlib
    import os
    try:
        module_name, func_name = callback.callback_function.rsplit('.', 1)
        module = importlib.import_module(module_name)
        generator = getattr(module, func_name)
    except Exception as e:
        return f"Failed to import callback function: {e}", 500

    try:
        pdf_file_path = generator(data_file)
        if not pdf_file_path or not isinstance(pdf_file_path, str) or not os.path.exists(pdf_file_path):
            return f"PDF file not generated or not found: {pdf_file_path}", 404
        return send_file(pdf_file_path, mimetype='application/pdf')
    except Exception as e:
        return f"Error generating PDF: {str(e)}", 500
