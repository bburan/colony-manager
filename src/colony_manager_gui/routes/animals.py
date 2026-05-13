import datetime
import re
from datetime import date

from sqlalchemy import func, case
from sqlalchemy.orm import joinedload
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, Response, send_file
from colony_manager.models import (
    Animal, AnimalEvent, AnimalProcedure, Cage, Study, Ear, Feed, FeedLog,
    WeightLog, Data, DataType, AnimalEventData, AnimalEventDataType,
    ConfocalImageData, AnimalData, EarData, study_animals, _expand_sides,
)

from .. import db
from .. import forms
from .. import models
from ..forms import AnimalForm, AnimalEventForm, AnimalEventEditForm, AnimalCustomIDForm, NoteForm, TerminationForm, QuickAddToStudyForm, DailyLogForm, mark_disabled, mark_readonly
from .util import flash_form_errors, render_modal


animals_bp = Blueprint('animals', __name__)


def _attach_event_aggregates(animals, today):
    """Bulk-load event/study aggregates and stash them on each animal.

    Replaces the per-row dynamic-relationship queries that the
    ``Animal.event_*`` / ``has_events`` / ``events_count`` /
    ``studies_count`` properties would otherwise issue once each per
    rendered row. Two grouped queries cover any number of animals.
    """
    if not animals:
        return
    animal_ids = [a.id for a in animals]

    event_rows = db.session.query(
        AnimalEvent.animal_id,
        func.count(AnimalEvent.id).label('total'),
        func.coalesce(
            func.bool_or(
                (AnimalEvent.scheduled_date == today)
                & AnimalEvent.completion_date.is_(None)
            ),
            False,
        ).label('any_due'),
        func.coalesce(
            func.bool_or(
                (AnimalEvent.scheduled_date < today)
                & AnimalEvent.completion_date.is_(None)
            ),
            False,
        ).label('any_overdue'),
        func.max(AnimalEvent.completion_date).label('last_completion'),
    ).filter(AnimalEvent.animal_id.in_(animal_ids)) \
     .group_by(AnimalEvent.animal_id).all()
    events_by_id = {r.animal_id: r for r in event_rows}

    study_rows = db.session.query(
        study_animals.c.animal_id,
        func.count(study_animals.c.study_id).label('total'),
    ).filter(study_animals.c.animal_id.in_(animal_ids)) \
     .group_by(study_animals.c.animal_id).all()
    studies_by_id = {r.animal_id: r.total for r in study_rows}

    for a in animals:
        row = events_by_id.get(a.id)
        a._events_count_cached = row.total if row else 0
        a._has_events_cached = bool(row and row.total)
        a._event_due_cached = bool(row and row.any_due)
        a._event_overdue_cached = bool(row and row.any_overdue)
        a._last_event_date_cached = row.last_completion if (row and row.last_completion) else date.min
        a._studies_count_cached = studies_by_id.get(a.id, 0)


@animals_bp.route('/')
def list_animals():
    sort_by = request.args.get('sort_by', 'id')
    event_filter = request.args.get('event_filter', 'all')
    status_filter = request.args.get('status_filter', 'active')
    study_filter = request.args.get('study_filter', 'all')
    age_unit = request.args.get('age_unit', 'day')
    search_query = request.args.get('search_query', '')

    # ``species`` and ``cage`` are dereferenced once per row in the table
    # template; eager-load both so the row render isn't 1+2N queries.
    query = Animal.query.options(
        joinedload(Animal.species),
        joinedload(Animal.cage),
    ).filter(Animal.custom_id.is_not(None))

    species_id = int(session.get('selected_species', -1))
    if species_id != -1:
        query = query.filter(Animal.species_id==species_id)

    if search_query:
        # Join events + procedures so we can match either the animal's
        # custom_id or a procedure name. ``.distinct()`` prevents an animal
        # with N matching events from appearing N times.
        query = query.join(Animal.events, isouter=True) \
                     .join(AnimalEvent.procedure, isouter=True) \
                     .filter(
                         db.or_(
                             Animal.custom_id.ilike(f'%{search_query}%'),
                             AnimalProcedure.name.ilike(f'%{search_query}%')
                         )
                     ).distinct()

    if status_filter == 'active':
        query = query.filter(Animal.termination_date.is_(None))
    elif status_filter == 'terminated':
        query = query.filter(Animal.termination_date.is_not(None))
    if study_filter != 'all':
        query = query.join(Animal.studies).filter(Study.id == int(study_filter))

    animals = query.all()
    _attach_event_aggregates(animals, date.today())
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
        sides = ['Left', 'Right'] if form.side.data == 'Both' else [form.side.data]
        for side in sides:
            event = AnimalEvent(animal_id=animal_id)
            event.procedure = form.procedure.data
            event.procedure_target = form.procedure_target.data
            event.side = side
            event.notes = form.notes.data
            event.tags = form.tags.data
            if form.action.data == 'schedule':
                event.scheduled_date = form.date.data
            else:
                event.scheduled_date = form.date.data
                event.completion_date = form.date.data
            db.session.add(event)
        db.session.commit()
        msg = 'Events created successfully.' if len(sides) > 1 else 'Event created successfully.'
        flash(msg, 'success')
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


def _parsed_animal_sides(f, animal_custom_id):
    """Sides the parser assigns to ``animal_custom_id`` in file ``f``.

    Returns
    -------
    None
        The parser did not see this animal in this file.
    list[str]
        Canonical sides for this animal in this file. Empty list means
        "animal is present, but no side was parsed".
    """
    try:
        cls = f.datatype.get_description()
        parsed = cls(f).parse() or {}
    except Exception:
        return None
    raw_ids = parsed.get('animal_id')
    if not raw_ids:
        return None
    ids = list(raw_ids) if isinstance(raw_ids, (list, tuple)) else [raw_ids]
    if animal_custom_id not in ids:
        return None
    sides = _expand_sides(parsed.get('side') or parsed.get('ear'), len(ids))
    if sides is None:
        return []
    return [s for aid, s in zip(ids, sides) if aid == animal_custom_id and s]


def _resync_event_files(event):
    """Unlink files whose date or parsed side no longer matches the event, then link matching files."""
    new_date = event.completion_date or event.scheduled_date
    animal_custom_id = event.animal.custom_id

    # 1. Unlink files (this event only) whose date or parsed side no longer
    #    matches. A file with no parsed side is allowed to stay linked —
    #    same convention as the initial sync match.
    for f in list(event.data_files):
        if f.date != new_date:
            f.events.remove(event)
            continue
        if event.side is not None:
            f_sides = _parsed_animal_sides(f, animal_custom_id)
            if f_sides and event.side not in set(f_sides):
                f.events.remove(event)

    # 2. Link AnimalEventData files matching date, animal candidacy, and the
    #    DataType's default procedure. Side must match when both the event
    #    and the file's parser specify one.
    candidate_files = AnimalEventData.query.filter(
        AnimalEventData.date == new_date,
    ).all()
    for f in candidate_files:
        dt = f.datatype
        if getattr(dt, 'default_procedure_id', None) != event.procedure_id:
            continue
        if event in f.events:
            continue
        if not any(a.id == event.animal_id for a in f.candidate_animals):
            continue
        if event.side is not None:
            f_sides = _parsed_animal_sides(f, animal_custom_id)
            if f_sides and event.side not in set(f_sides):
                continue
        f.events.append(event)


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
    form = AnimalForm(cage=cage, dob=animal.dob, sex=animal.sex)
    return render_modal(form, label='Create new animal',
                        submit_url=url_for('animals.create_animal'))


@animals_bp.route('/<int:animal_id>/edit_modal')
def edit_animal_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    return render_modal(AnimalForm(obj=animal), item=animal,
                        label=f'Edit {animal.display_id}',
                        submit_url=url_for('animals.update_animal', animal_id=animal.id))


@animals_bp.route('/<int:animal_id>/assign_id_modal')
def assign_animal_id_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    form = AnimalCustomIDForm(custom_id=f'{animal.cage.custom_id}-')
    return render_modal(form, item=animal,
                        label=f'Assign ID for {animal.display_id}',
                        submit_url=url_for('animals.update_animal', animal_id=animal.id))


@animals_bp.route('/<int:animal_id>/edit_note_modal')
def edit_animal_note_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    return render_modal(NoteForm(obj=animal), item=animal,
                        label=f'Edit note for {animal.display_id}',
                        submit_url=url_for('animals.update_animal', animal_id=animal.id))


@animals_bp.route('/<int:animal_id>/terminate_modal')
def terminate_animal_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    return render_modal(TerminationForm(obj=animal), item=animal,
                        label=f'Remove {animal.display_id}',
                        submit_url=url_for('animals.terminate_animal', animal_id=animal.id))


@animals_bp.route('/<int:animal_id>/quick_add_study_modal')
def add_study_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    return render_modal(QuickAddToStudyForm(), item=animal,
                        label=f'Add study for {animal.display_id}',
                        submit_url=url_for('studies.add_study_animal', animal_id=animal.id))

# --- Animal Event Modals ---
def _target_requires_side_map():
    return {
        str(t.id): bool(t.requires_side)
        for t in models.AnimalProcedureTarget.query.all()
    }


@animals_bp.route('/<int:animal_id>/events/create_modal')
def create_animal_event_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    return render_modal(
        AnimalEventForm(animal=animal), item=animal,
        label=f'Create event for {animal.display_id}',
        submit_url=url_for('animals.create_animal_event', animal_id=animal.id),
        partial='partials/form_event_modal.html',
        target_requires_side=_target_requires_side_map(),
        is_edit=False,
    )


@animals_bp.route('/events/<int:event_id>/edit_modal')
def edit_animal_event_modal(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    return render_modal(
        AnimalEventEditForm(obj=event), item=event,
        label=f'Edit event for {event.animal.display_id}',
        submit_url=url_for('animals.update_animal_event', event_id=event.id),
        partial='partials/form_event_modal.html',
        target_requires_side=_target_requires_side_map(),
        is_edit=True,
    )


@animals_bp.route('/events/<int:event_id>/delete_modal')
def delete_animal_event_modal(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    form = AnimalEventEditForm(obj=event)
    mark_disabled(form)
    return render_modal(form, item=event,
                        label=f'Remove event for {event.animal.display_id}',
                        submit_url=url_for('animals.delete_animal_event', event_id=event.id))


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
    return render_modal(
        form, item=animal,
        label=f'Add entry for {animal.display_id}',
        submit_url=url_for('animals.create_animal_daily_log', animal_id=animal.id),
        partial='partials/form_daily_log_modal.html',
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
    return render_modal(
        form, item=animal,
        label=f'Update entry for {animal.display_id}',
        submit_url=url_for('animals.update_animal_daily_log', animal_id=animal.id, date=date),
        partial='partials/form_daily_log_modal.html',
    )


@animals_bp.route('/<int:animal_id>/<date>/weight-feed/delete_modal')
def delete_animal_daily_log_modal(animal_id, date):
    animal, form = _generate_daily_log_form(animal_id, date)
    mark_disabled(form)
    return render_modal(
        form, item=animal,
        label=f'Delete entry for {animal.display_id}',
        submit_url=url_for('animals.delete_animal_daily_log', animal_id=animal.id, date=date),
        partial='partials/form_daily_log_modal.html',
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
    """Attach/detach an AnimalEventData row to a single event for this animal."""
    data_file = AnimalEventData.query.get_or_404(data_id)
    event_id = request.form.get('event_id')

    # Drop any existing link to events belonging to this animal so we don't
    # leave duplicates after the user picks a different one.
    for ev in list(data_file.events):
        if ev.animal_id == animal_id:
            data_file.events.remove(ev)

    if event_id and event_id != '__None':
        event = AnimalEvent.query.get_or_404(int(event_id))
        data_file.events.append(event)
        flash(f"File {data_file.name} attached to event.", "success")
    else:
        flash(f"File {data_file.name} detached from event.", "info")
    db.session.commit()
    return redirect(url_for('animals.view_animal', animal_id=animal_id))


@animals_bp.route('/unmatched-data')
def list_unmatched_data():
    """Files where the sync script could not link to any target."""
    from colony_manager.models import DataType, DATA_SUBCLASSES
    from sqlalchemy import union_all

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    target_type_filter = request.args.get('target_type', 'all')
    datatype_id_filter = request.args.get('datatype_id', None, type=int)

    if target_type_filter == 'animal_event':
        query = AnimalEventData.query.filter(~AnimalEventData.events.any())
    elif target_type_filter == 'confocal_image':
        query = ConfocalImageData.query.filter(~ConfocalImageData.confocal_images.any())
    elif target_type_filter == 'animal':
        query = AnimalData.query.filter(~AnimalData.animals.any())
    elif target_type_filter == 'ear':
        query = EarData.query.filter(~EarData.ears.any())
    else:
        unmatched_ae_ids = db.session.query(AnimalEventData.id).filter(~AnimalEventData.events.any())
        unmatched_ci_ids = db.session.query(ConfocalImageData.id).filter(~ConfocalImageData.confocal_images.any())
        unmatched_a_ids = db.session.query(AnimalData.id).filter(~AnimalData.animals.any())
        unmatched_e_ids = db.session.query(EarData.id).filter(~EarData.ears.any())
        combined = union_all(unmatched_ae_ids, unmatched_ci_ids, unmatched_a_ids, unmatched_e_ids).subquery()
        query = Data.query.filter(Data.id.in_(combined))

    if datatype_id_filter:
        query = query.filter(Data.datatype_id == datatype_id_filter)

    query = query.order_by(Data.date.desc(), Data.name)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    datatypes = DataType.query.order_by(DataType.name).all()
    return render_template(
        'unmatched_data.html',
        files=pagination.items,
        pagination=pagination,
        filters={
            'target_type': target_type_filter,
            'datatype_id': datatype_id_filter,
            'per_page': per_page,
        },
        datatypes=datatypes,
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

@animals_bp.route('/data/<int:data_id>/notes', methods=['POST'])
def update_data_notes(data_id):
    """Update the notes field on a Data file."""
    data_file = Data.query.get_or_404(data_id)
    data_file.notes = request.form.get('notes', '').strip() or None
    db.session.commit()
    return '', 204


@animals_bp.route('/<int:animal_id>/data/<int:data_id>/auto_create_event', methods=['POST'])
def auto_create_event(animal_id, data_id):
    """Auto-create an AnimalEvent for an unassigned AnimalEventData file, then link matching files."""
    data_file = AnimalEventData.query.get_or_404(data_id)
    datatype = data_file.datatype

    if not getattr(datatype, 'default_procedure_id', None):
        flash('Cannot auto-create: DataType has no Default Procedure configured.', 'danger')
        return redirect(url_for('animals.view_animal', animal_id=animal_id))
    if not data_file.date:
        flash('Cannot auto-create: file has no parsed date.', 'danger')
        return redirect(url_for('animals.view_animal', animal_id=animal_id))

    animal_custom_id = Animal.query.get_or_404(animal_id).custom_id

    target = datatype.default_procedure_target
    if target is not None and target.requires_side:
        own_sides = _parsed_animal_sides(data_file, animal_custom_id)
        sides = sorted(set(own_sides)) if own_sides else []
        if not sides:
            flash(
                'Cannot auto-create: target requires a side but the parser '
                'did not resolve one for this animal.', 'danger')
            return redirect(url_for('animals.view_animal', animal_id=animal_id))
    else:
        sides = [None]

    # Reuse an existing matching event when one is already on the animal —
    # otherwise a second wand-click for a sibling file (or any later
    # wand-click after this date already has the event) duplicates it.
    target_events = []
    created_count = 0
    for side in sides:
        query = AnimalEvent.query.filter_by(
            animal_id=animal_id,
            procedure_id=datatype.default_procedure_id,
            procedure_target_id=datatype.default_procedure_target_id,
        ).filter(
            db.or_(
                AnimalEvent.scheduled_date == data_file.date,
                AnimalEvent.completion_date == data_file.date,
            )
        )
        if side is None:
            query = query.filter(AnimalEvent.side.is_(None))
        else:
            query = query.filter(AnimalEvent.side == side)
        existing = query.first()
        if existing:
            target_events.append(existing)
        else:
            event = AnimalEvent(
                animal_id=animal_id,
                procedure_id=datatype.default_procedure_id,
                procedure_target_id=datatype.default_procedure_target_id,
                side=side,
                scheduled_date=data_file.date,
                completion_date=data_file.date,
            )
            db.session.add(event)
            target_events.append(event)
            created_count += 1
    db.session.flush()

    # Link any AnimalEventData on this date whose datatype shares the
    # event's procedure — covers same-datatype siblings *and* sister
    # datatypes (e.g. ABR + DPOAE both defaulting to Physiology).
    # ``candidate_animals`` is deliberately not in the SQL filter: it can
    # be stale (file synced before the animal existed) and would silently
    # drop files the parser would otherwise place on this animal. The
    # reparse below is the authoritative animal/side check.
    candidate_files = AnimalEventData.query.join(
        AnimalEventDataType,
        AnimalEventData.datatype_id == AnimalEventDataType.id,
    ).filter(
        AnimalEventDataType.default_procedure_id == datatype.default_procedure_id,
        AnimalEventData.date == data_file.date,
    ).all()
    linked_count = 0
    for f in candidate_files:
        f_sides = _parsed_animal_sides(f, animal_custom_id)
        if f_sides is None:
            continue  # parser doesn't place this animal in this file
        f_sides = set(f_sides)
        for event in target_events:
            if event in f.events:
                continue
            # No parsed side → link best-effort. Parsed side present →
            # require it to match the event's side.
            if event.side is not None and f_sides and event.side not in f_sides:
                continue
            f.events.append(event)
            linked_count += 1

    db.session.commit()
    parts = []
    if created_count:
        parts.append(f'{created_count} event{"s" if created_count != 1 else ""} created')
    reused = len(target_events) - created_count
    if reused:
        parts.append(f'{reused} reused')
    parts.append(f'{linked_count} file(s) linked')
    flash(', '.join(parts).capitalize() + '.', 'success')
    return redirect(url_for('animals.view_animal', animal_id=animal_id))

def _resolve_callback(data_id, callback_name):
    """Look up a Data row + DataTypeDescription callback.

    Returns ``(description_instance, callback_info)`` on success, or
    ``(None, (error_message, status_code))`` on failure.
    """
    import os
    from colony_manager.datatypes import load_description_class

    data_file = Data.query.get_or_404(data_id)
    dt = data_file.datatype
    if not dt.description_class:
        return None, ('No description class configured for this datatype.', 400)
    try:
        desc_cls = load_description_class(dt.description_class)
    except Exception as e:
        return None, (f'Failed to load description class: {e}', 500)

    callbacks = desc_cls.get_callbacks()
    if callback_name not in callbacks:
        return None, (f'Unknown callback: {callback_name}', 404)

    full_path = os.path.join(data_file.location.base_path, data_file.relative_path)
    desc = desc_cls(full_path)
    return (desc, callbacks[callback_name]), None


@animals_bp.route('/data/<int:data_id>/plot/<path:callback_name>')
def plot_data(data_id, callback_name):
    """Invoke a plot callback and return JSON (Plotly figure or arbitrary dict)."""
    pair, err = _resolve_callback(data_id, callback_name)
    if err:
        msg, status = err
        return jsonify({'error': msg}), status
    desc, cb_info = pair
    try:
        result = desc.invoke_callback(callback_name)
        if hasattr(result, 'to_json'):
            return Response(result.to_json(), mimetype='application/json')
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'Error loading plot data: {str(e)}'}), 500


@animals_bp.route('/data/<int:data_id>/pdf/<path:callback_name>')
def view_data_pdf(data_id, callback_name):
    """Invoke a PDF callback and stream the resulting file."""
    import os
    pair, err = _resolve_callback(data_id, callback_name)
    if err:
        msg, status = err
        return msg, status
    desc, cb_info = pair
    try:
        pdf_path = desc.invoke_callback(callback_name)
        if not pdf_path or not os.path.exists(pdf_path):
            return f"PDF file not generated or not found: {pdf_path}", 404
        return send_file(pdf_path, mimetype='application/pdf')
    except Exception as e:
        return f"Error generating PDF: {str(e)}", 500


@animals_bp.route('/data/<int:data_id>/image/<path:callback_name>')
def view_data_image(data_id, callback_name):
    """Invoke an image callback and stream the resulting JPG."""
    import os
    pair, err = _resolve_callback(data_id, callback_name)
    if err:
        msg, status = err
        return msg, status
    desc, cb_info = pair
    try:
        result = desc.invoke_callback(callback_name)
        if hasattr(result, 'read'):
            return send_file(result, mimetype='image/jpeg')
        if not result or not os.path.exists(result):
            return f"Image not found: {result}", 404
        return send_file(result, mimetype='image/jpeg')
    except Exception as e:
        return f"Error loading image: {str(e)}", 500