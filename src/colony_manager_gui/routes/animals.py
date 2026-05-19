import datetime
import re
from datetime import date

from sqlalchemy import func, case, or_, select
from sqlalchemy.orm import joinedload, selectinload
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, Response, send_file
from colony_manager.models import (
    Animal, AnimalEvent, AnimalProcedure, AnimalTag, AnimalEventTag,
    Cage, Study, Ear, Feed, FeedLog,
    WeightLog, Data, DataType, AnimalEventData,
    ConfocalImageData, AnimalData, EarData, data_candidate_animals,
)

from .. import db
from .. import forms
from .. import models
from ..forms import AnimalForm, AnimalEventForm, AnimalEventEditForm, AnimalCustomIDForm, NoteForm, TerminationForm, QuickAddToStudyForm, DailyLogForm, mark_disabled, mark_readonly
from .util import flash_form_errors, render_modal
from ..services.data_linking import (
    parsed_animal_sides, resync_event_files, auto_create_animal_event,
)


animals_bp = Blueprint('animals', __name__)


_SORT_DIR_DEFAULTS = {'id': 'asc', 'age': 'asc', 'event_date': 'desc'}


@animals_bp.route('/')
def list_animals():
    sort_by = request.args.get('sort_by', 'id')
    sort_dir = request.args.get('sort_dir', '')
    if sort_dir not in ('asc', 'desc'):
        sort_dir = _SORT_DIR_DEFAULTS.get(sort_by, 'asc')

    event_filter = request.args.get('event_filter', 'all')
    status_filter = request.args.get('status_filter', 'active')
    sex_filter = request.args.get('sex_filter', 'all')
    study_filter = request.args.get('study_filter', 'all')
    procedure_filter = request.args.get('procedure_id', 'all')
    tag_filter = request.args.get('tag_id', 'all')
    event_tag_filter = request.args.get('event_tag_id', 'all')
    age_unit = request.args.get('age_unit', 'day')
    search_query = request.args.get('search_query', '')

    today = date.today()

    # ``species`` and ``cage`` are dereferenced once per row in the table
    # template; eager-load both so the row render isn't 1+2N queries.
    # ``events`` and ``studies`` drive the per-row aggregate properties
    # (events_count, event_due, etc.); load both in bulk so those don't
    # fan out into N queries either.
    stmt = select(Animal).options(
        joinedload(Animal.species),
        joinedload(Animal.cage),
        selectinload(Animal.events),
        selectinload(Animal.studies),
    ).where(Animal.custom_id.is_not(None))

    species_id = int(session.get('selected_species', -1))
    if species_id != -1:
        stmt = stmt.where(Animal.species_id == species_id)

    if search_query:
        stmt = stmt.where(Animal.custom_id.ilike(f'%{search_query}%'))

    if status_filter == 'active':
        stmt = stmt.where(Animal.termination_date.is_(None))
    elif status_filter == 'terminated':
        stmt = stmt.where(Animal.termination_date.is_not(None))

    if sex_filter in ('male', 'female'):
        stmt = stmt.where(Animal.sex == sex_filter)

    if study_filter != 'all':
        stmt = stmt.where(Animal.studies.any(Study.id == int(study_filter)))

    if procedure_filter != 'all':
        proc_ids = AnimalProcedure.descendant_ids(db.session, int(procedure_filter))
        stmt = stmt.where(
            Animal.events.any(AnimalEvent.procedure_id.in_(proc_ids))
        )

    if tag_filter != 'all':
        tag_ids = AnimalTag.descendant_ids(db.session, int(tag_filter))
        stmt = stmt.where(Animal.tags.any(AnimalTag.id.in_(tag_ids)))

    if event_tag_filter != 'all':
        et_ids = AnimalEventTag.descendant_ids(db.session, int(event_tag_filter))
        stmt = stmt.where(Animal.events.any(
            AnimalEvent.tags.any(AnimalEventTag.id.in_(et_ids))
        ))

    if event_filter == 'has_events':
        stmt = stmt.where(Animal.events.any())
    elif event_filter == 'no_events':
        stmt = stmt.where(~Animal.events.any())
    elif event_filter == 'due_overdue':
        stmt = stmt.where(Animal.events.any(
            (AnimalEvent.scheduled_date <= today)
            & AnimalEvent.completion_date.is_(None)
        ))
    elif event_filter == 'overdue':
        stmt = stmt.where(Animal.events.any(
            (AnimalEvent.scheduled_date < today)
            & AnimalEvent.completion_date.is_(None)
        ))

    # Sorting — pushed into SQL. ``age`` orders by dob, so direction is
    # inverted (asc age = youngest = newest dob).
    if sort_by == 'event_date':
        last_event_subq = (
            select(
                AnimalEvent.animal_id.label('animal_id'),
                func.max(AnimalEvent.completion_date).label('last_event_date'),
            ).group_by(AnimalEvent.animal_id).subquery()
        )
        stmt = stmt.outerjoin(
            last_event_subq, last_event_subq.c.animal_id == Animal.id
        )
        col = last_event_subq.c.last_event_date
        order = col.desc().nullslast() if sort_dir == 'desc' else col.asc().nullsfirst()
    elif sort_by == 'age':
        col = Animal.dob
        order = col.asc() if sort_dir == 'desc' else col.desc()
    else:  # 'id'
        col = Animal.custom_id
        order = col.desc() if sort_dir == 'desc' else col.asc()

    animals = db.session.scalars(stmt.order_by(order)).unique().all()

    procedures = AnimalProcedure.get_ordered(db.session)
    animal_tags = AnimalTag.get_ordered(db.session)
    event_tags = AnimalEventTag.get_ordered(db.session)
    studies = db.session.scalars(
        select(Study).order_by(Study.name)
    ).all()

    return render_template(
        'animals.html',
        animals=animals,
        procedures=procedures,
        animal_tags=animal_tags,
        event_tags=event_tags,
        studies=studies,
        filters={
            'sort_by': sort_by,
            'sort_dir': sort_dir,
            'status_filter': status_filter,
            'sex_filter': sex_filter,
            'event_filter': event_filter,
            'study_filter': study_filter,
            'procedure_id': procedure_filter,
            'tag_id': tag_filter,
            'event_tag_id': event_tag_filter,
            'age_unit': age_unit,
            'search_query': search_query,
        },
    )


@animals_bp.route('/<int:animal_id>')
def view_animal(animal_id):
    # Eager-load the relationships the page touches per event row and
    # per file row. ``selectinload(Animal.events)`` chains into the
    # event's procedure / target / tags / data_files so the events
    # accordion + the events_by_date grouping don't fan out into N
    # queries.
    animal = db.session.scalars(
        select(Animal)
        .where(Animal.id == animal_id)
        .options(
            selectinload(Animal.events).joinedload(AnimalEvent.procedure),
            selectinload(Animal.events).joinedload(AnimalEvent.procedure_target),
            selectinload(Animal.events).selectinload(AnimalEvent.tags),
            selectinload(Animal.events).selectinload(AnimalEvent.data_files)
                .joinedload(Data.datatype),
            selectinload(Animal.data_files).joinedload(Data.datatype),
        )
    ).first()
    if animal is None:
        from flask import abort
        abort(404)

    feed = db.session.scalars(
        select(Feed).order_by(Feed.weight)
    ).all()

    # Files accordion: sort the already-loaded data_files list.
    animal_data_files = sorted(animal.data_files, key=lambda f: f.name)

    # Unassigned candidate event files (events accordion). Pre-filter to the
    # animal_event subset and eager-load each file's events so the
    # per-file ``f.events`` check doesn't issue its own query.
    candidate_event_files = db.session.scalars(
        select(AnimalEventData)
        .join(data_candidate_animals,
              AnimalEventData.id == data_candidate_animals.c.data_id)
        .where(data_candidate_animals.c.animal_id == animal_id)
        .options(selectinload(AnimalEventData.events),
                 joinedload(AnimalEventData.datatype))
    ).all()
    unassigned_files = [
        f for f in candidate_event_files
        if not any(ev.animal_id == animal_id for ev in f.events)
    ]

    return render_template(
        'view_animal.html',
        animal=animal,
        feeds=feed,
        animal_data_files=animal_data_files,
        unassigned_files=unassigned_files,
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
    animal = db.get_or_404(Animal, animal_id)
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
    animal = db.get_or_404(Animal, animal_id)
    if animal.breeding_pair_male or animal.breeding_pair_female:
        flash(f'Cannot delete animal {animal.display_id} because it is part of a breeding pair.', 'danger')
        return redirect(request.referrer or url_for('animals.list_animals'))
    db.session.delete(animal)
    db.session.commit()
    flash(f'Animal {animal.display_id} has been deleted.', 'success')
    return redirect(request.referrer or url_for('animals.list_animals'))


@animals_bp.route('/<int:animal_id>/terminate', methods=['POST'])
def terminate_animal(animal_id):
    animal = db.get_or_404(Animal, animal_id)
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
    event = db.get_or_404(AnimalEvent, event_id)
    form = AnimalEventEditForm()
    if form.validate_on_submit():
        form.populate_obj(event)
        db.session.commit()
        resync_event_files(event)
        db.session.commit()
        flash('Event updated successfully.', 'success')
    else:
        flash_form_errors(form, f'Error updating event')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=event.animal_id))


@animals_bp.route('/events/<int:event_id>/delete', methods=['POST'])
def delete_animal_event(event_id):
    event = db.get_or_404(AnimalEvent, event_id)
    animal_id = event.animal_id  # Grab this to redirect back to the right page
    db.session.delete(event)
    db.session.commit()
    # Flash messages are great for feedback
    flash("Event deleted successfully.", "success")
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal_id))

@animals_bp.route('/<int:animal_id>/weight-feed/create', methods=['POST'])
def create_animal_daily_log(animal_id):
    animal = db.get_or_404(Animal, animal_id)
    form = DailyLogForm()
    if form.validate_on_submit():
        logs = db.session.scalars(
            select(WeightLog).where(
                WeightLog.animal_id == animal.id,
                WeightLog.date == form.date.data,
            )
        ).all()
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
    animal = db.get_or_404(Animal, animal_id)
    weight = db.session.scalars(
        select(WeightLog).where(
            WeightLog.animal_id == animal.id,
            WeightLog.date == date,
        )
    ).one_or_none()
    if weight is not None:
        db.session.delete(weight)
    for entry in db.session.scalars(
        select(FeedLog).where(
            FeedLog.animal_id == animal.id,
            FeedLog.date == date,
        )
    ).all():
        db.session.delete(entry)
    db.session.commit()
    flash('Daily log deleted successfully.', 'success')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal.id))

@animals_bp.route('/<int:animal_id>/<date>/weight-feed/update', methods=['POST'])
def update_animal_daily_log(animal_id, date):
    animal = db.get_or_404(Animal, animal_id)
    form = DailyLogForm()
    if form.validate_on_submit():
        weight = db.session.scalars(
            select(WeightLog).where(
                WeightLog.animal_id == animal.id,
                WeightLog.date == date,
            )
        ).one()
        weight.weight = form.weight.data
        weight.notes = form.notes.data
        weight.baseline = form.baseline.data
        for feed_form in form.feedings:
            feeding = db.session.scalars(
                select(FeedLog).where(
                    FeedLog.animal_id == animal.id,
                    FeedLog.date == date,
                    FeedLog.feed_id == feed_form.feed_id.data,
                )
            ).one_or_none()
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
    cage = db.get_or_404(Cage, cage_id)
    # Prefill dob/sex from any existing animal in the cage so the user
    # only has to type the new ID. If the cage is empty, fall back to
    # the form defaults (today / male).
    animal = cage.animals[0] if cage.animals else None
    form = AnimalForm(
        cage=cage,
        dob=animal.dob if animal else None,
        sex=animal.sex if animal else None,
    )
    return render_modal(form, label='Create new animal',
                        submit_url=url_for('animals.create_animal'))


@animals_bp.route('/<int:animal_id>/edit_modal')
def edit_animal_modal(animal_id):
    animal = db.get_or_404(Animal, animal_id)
    return render_modal(AnimalForm(obj=animal), item=animal,
                        label=f'Edit {animal.display_id}',
                        submit_url=url_for('animals.update_animal', animal_id=animal.id))


@animals_bp.route('/<int:animal_id>/assign_id_modal')
def assign_animal_id_modal(animal_id):
    animal = db.get_or_404(Animal, animal_id)
    form = AnimalCustomIDForm(custom_id=f'{animal.cage.custom_id}-')
    return render_modal(form, item=animal,
                        label=f'Assign ID for {animal.display_id}',
                        submit_url=url_for('animals.update_animal', animal_id=animal.id))


@animals_bp.route('/<int:animal_id>/edit_note_modal')
def edit_animal_note_modal(animal_id):
    animal = db.get_or_404(Animal, animal_id)
    return render_modal(NoteForm(obj=animal), item=animal,
                        label=f'Edit note for {animal.display_id}',
                        submit_url=url_for('animals.update_animal', animal_id=animal.id))


@animals_bp.route('/<int:animal_id>/terminate_modal')
def terminate_animal_modal(animal_id):
    animal = db.get_or_404(Animal, animal_id)
    return render_modal(TerminationForm(obj=animal), item=animal,
                        label=f'Remove {animal.display_id}',
                        submit_url=url_for('animals.terminate_animal', animal_id=animal.id))


@animals_bp.route('/<int:animal_id>/quick_add_study_modal')
def add_study_modal(animal_id):
    animal = db.get_or_404(Animal, animal_id)
    return render_modal(QuickAddToStudyForm(), item=animal,
                        label=f'Add study for {animal.display_id}',
                        submit_url=url_for('studies.add_study_animal', animal_id=animal.id))

# --- Animal Event Modals ---
def _target_requires_side_map():
    return {
        str(t.id): bool(t.requires_side)
        for t in db.session.scalars(select(models.AnimalProcedureTarget)).all()
    }


@animals_bp.route('/<int:animal_id>/events/create_modal')
def create_animal_event_modal(animal_id):
    animal = db.get_or_404(Animal, animal_id)
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
    event = db.get_or_404(AnimalEvent, event_id)
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
    event = db.get_or_404(AnimalEvent, event_id)
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
    animal = db.get_or_404(Animal, animal_id)
    feed = db.session.scalars(
        select(Feed).order_by(Feed.weight)
    ).all()
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
    animal = db.get_or_404(Animal, animal_id)
    feed = db.session.scalars(
        select(Feed).order_by(Feed.weight)
    ).all()
    feed_data = []
    for f in feed:
        entry = db.session.scalars(
            select(FeedLog).where(
                FeedLog.animal_id == animal.id,
                FeedLog.date == date,
                FeedLog.feed_id == f.id,
            )
        ).one_or_none()
        feed_data.append({
            'feed_id': f.id,
            'feed_name': f.name,
            'feed_weight': f.weight,
            'quantity': entry.quantity if entry else 0,
        })

    weight_log = db.session.scalars(
        select(WeightLog).where(
            WeightLog.animal_id == animal.id,
            WeightLog.date == date,
        )
    ).one_or_none()
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
    animal = db.get_or_404(Animal, animal_id)
    return render_template(
        'partials/event_popover.html',
        animal=animal,
    )

@animals_bp.route('/<int:animal_id>/data/<int:data_id>/reassign', methods=['POST'])
def reassign_data(animal_id, data_id):
    """Attach/detach an AnimalEventData row to a single event for this animal."""
    data_file = db.get_or_404(AnimalEventData, data_id)
    event_id = request.form.get('event_id')

    # Drop any existing link to events belonging to this animal so we don't
    # leave duplicates after the user picks a different one.
    for ev in list(data_file.events):
        if ev.animal_id == animal_id:
            data_file.events.remove(ev)

    if event_id and event_id != '__None':
        event = db.get_or_404(AnimalEvent, int(event_id))
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
    from datetime import datetime

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    target_type_filter = request.args.get('target_type', 'all')
    datatype_id_filter = request.args.get('datatype_id', None, type=int)
    status_filter = request.args.get('status', 'all')
    search_filter = (request.args.get('q', '') or '').strip()
    date_from_raw = (request.args.get('date_from', '') or '').strip()
    date_to_raw = (request.args.get('date_to', '') or '').strip()
    sort = request.args.get('sort', 'date')
    direction = request.args.get('dir', 'desc')

    def _parse_date(raw):
        try:
            return datetime.strptime(raw, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None

    date_from = _parse_date(date_from_raw)
    date_to = _parse_date(date_to_raw)

    if target_type_filter == 'animal_event':
        stmt = select(AnimalEventData).where(~AnimalEventData.events.any())
    elif target_type_filter == 'confocal_image':
        stmt = select(ConfocalImageData).where(~ConfocalImageData.confocal_images.any())
    elif target_type_filter == 'animal':
        stmt = select(AnimalData).where(~AnimalData.animals.any())
    elif target_type_filter == 'ear':
        stmt = select(EarData).where(~EarData.ears.any())
    else:
        unmatched_ae_ids = select(AnimalEventData.id).where(~AnimalEventData.events.any())
        unmatched_ci_ids = select(ConfocalImageData.id).where(~ConfocalImageData.confocal_images.any())
        unmatched_a_ids = select(AnimalData.id).where(~AnimalData.animals.any())
        unmatched_e_ids = select(EarData.id).where(~EarData.ears.any())
        combined = union_all(unmatched_ae_ids, unmatched_ci_ids, unmatched_a_ids, unmatched_e_ids).subquery()
        stmt = select(Data).where(Data.id.in_(select(combined)))

    if datatype_id_filter:
        stmt = stmt.where(Data.datatype_id == datatype_id_filter)

    if status_filter and status_filter != 'all':
        stmt = stmt.where(Data.status == status_filter)

    if search_filter:
        like = f'%{search_filter}%'
        stmt = stmt.where(or_(Data.name.ilike(like), Data.relative_path.ilike(like)))

    if date_from is not None:
        stmt = stmt.where(Data.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Data.date <= date_to)

    sort_columns = {
        'date': Data.date,
        'name': Data.name,
        'datatype': DataType.name,
        'status': Data.status,
    }
    sort_col = sort_columns.get(sort, Data.date)
    if sort == 'datatype':
        stmt = stmt.join(DataType, Data.datatype_id == DataType.id)
    if direction == 'asc':
        stmt = stmt.order_by(sort_col.asc(), Data.name.asc())
    else:
        stmt = stmt.order_by(sort_col.desc(), Data.name.asc())

    pagination = db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    datatypes = db.session.scalars(
        select(DataType).order_by(DataType.name)
    ).all()
    return render_template(
        'unmatched_data.html',
        files=pagination.items,
        pagination=pagination,
        filters={
            'target_type': target_type_filter,
            'datatype_id': datatype_id_filter,
            'per_page': per_page,
            'status': status_filter,
            'q': search_filter,
            'date_from': date_from_raw,
            'date_to': date_to_raw,
            'sort': sort,
            'dir': direction,
        },
        datatypes=datatypes,
    )

@animals_bp.route('/unmatched-data/delete', methods=['POST'])
def delete_unmatched_data():
    """Bulk-delete selected Data rows (typically files marked 'missing').

    Posted from the unmatched-files table: a list of ``data_ids`` from
    the per-row checkboxes. No-op if the list is empty. Filter / sort
    state is preserved via query-string args round-tripped in the
    redirect; the form action carries them through ``request.referrer``.
    """
    data_ids = request.form.getlist('data_ids', type=int)
    if not data_ids:
        flash('No files selected.', 'warning')
        return redirect(request.referrer or url_for('animals.list_unmatched_data'))

    rows = db.session.scalars(
        select(Data).where(Data.id.in_(data_ids))
    ).all()
    for row in rows:
        db.session.delete(row)
    db.session.commit()
    flash(f'Deleted {len(rows)} file record(s).', 'success')
    return redirect(request.referrer or url_for('animals.list_unmatched_data'))


@animals_bp.route('/unmatched-data/auto-create', methods=['POST'])
def auto_create_unmatched_data():
    """Bulk-trigger ``auto_create_animal_event`` for selected files.

    For each selected AnimalEventData row with at least one
    ``candidate_animals`` entry, invoke the same auto-create flow the
    single-file "wand" button uses. Files that aren't AnimalEventData
    (e.g. confocal_image files), or that have no candidates, are
    skipped with a counted reason — auto_create_animal_event itself
    raises its own AutoCreateResult.error for further skip reasons
    (no default procedure, no parsed date, side required + missing).
    """
    data_ids = request.form.getlist('data_ids', type=int)
    if not data_ids:
        flash('No files selected.', 'warning')
        return redirect(request.referrer or url_for('animals.list_unmatched_data'))

    rows = db.session.scalars(
        select(Data).where(Data.id.in_(data_ids))
    ).all()

    totals = {
        'considered': 0,
        'events_created': 0,
        'events_reused': 0,
        'files_linked': 0,
        'not_animal_event': 0,
        'no_candidate': 0,
        'errored': 0,
    }
    for row in rows:
        totals['considered'] += 1
        if not isinstance(row, AnimalEventData):
            totals['not_animal_event'] += 1
            continue
        if not row.candidate_animals:
            totals['no_candidate'] += 1
            continue
        result = auto_create_animal_event(row.candidate_animals[0], row)
        if result.error:
            totals['errored'] += 1
            continue
        totals['events_created'] += result.created
        totals['events_reused'] += result.reused
        totals['files_linked'] += result.linked

    # Build a single readable summary message.
    parts = []
    if totals['events_created']:
        parts.append(f"{totals['events_created']} event(s) created")
    if totals['events_reused']:
        parts.append(f"{totals['events_reused']} reused")
    if totals['files_linked']:
        parts.append(f"{totals['files_linked']} sibling file(s) linked")
    skips = []
    if totals['not_animal_event']:
        skips.append(f"{totals['not_animal_event']} non-animal_event")
    if totals['no_candidate']:
        skips.append(f"{totals['no_candidate']} without candidates")
    if totals['errored']:
        skips.append(f"{totals['errored']} blocked by parser/datatype config")
    if skips:
        parts.append(f"skipped {', '.join(skips)}")

    if parts:
        flash(', '.join(parts).capitalize() + '.', 'success')
    else:
        flash('No files were processed.', 'warning')
    return redirect(request.referrer or url_for('animals.list_unmatched_data'))


@animals_bp.route('/<int:animal_id>/data/<int:data_id>/set_status', methods=['POST'])
def set_data_status(animal_id, data_id):
    """Toggle the status of a Data file (reviewed / excluded / unreviewed)."""
    data_file = db.get_or_404(Data, data_id)
    new_status = request.form.get('status', 'unreviewed')
    data_file.status = new_status
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return {'status': 'success', 'new_status': data_file.status}

    return redirect(url_for('animals.view_animal', animal_id=animal_id))

@animals_bp.route('/data/<int:data_id>/notes', methods=['POST'])
def update_data_notes(data_id):
    """Update the notes field on a Data file."""
    data_file = db.get_or_404(Data, data_id)
    data_file.notes = request.form.get('notes', '').strip() or None
    db.session.commit()
    return '', 204


@animals_bp.route('/<int:animal_id>/data/<int:data_id>/auto_create_event', methods=['POST'])
def auto_create_event(animal_id, data_id):
    """Auto-create an AnimalEvent for an unassigned AnimalEventData file, then link matching files."""
    animal = db.get_or_404(Animal, animal_id)
    data_file = db.get_or_404(AnimalEventData, data_id)
    result = auto_create_animal_event(animal, data_file)
    if result.error:
        flash(result.error, 'danger')
        return redirect(url_for('animals.view_animal', animal_id=animal_id))
    parts = []
    if result.created:
        parts.append(f'{result.created} event{"s" if result.created != 1 else ""} created')
    if result.reused:
        parts.append(f'{result.reused} reused')
    parts.append(f'{result.linked} file(s) linked')
    flash(', '.join(parts).capitalize() + '.', 'success')
    return redirect(url_for('animals.view_animal', animal_id=animal_id))

def _resolve_callback(data_id, callback_name):
    """Look up a Data row + DataTypeDescription callback.

    Returns ``(description_instance, callback_info)`` on success, or
    ``(None, (error_message, status_code))`` on failure.
    """
    import os
    from colony_manager.datatypes import load_description_class

    data_file = db.get_or_404(Data, data_id)
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


@animals_bp.route('/data/<int:data_id>/dict/<path:callback_name>')
def view_data_dict(data_id, callback_name):
    """Invoke a dict callback and render as an HTML partial."""
    pair, err = _resolve_callback(data_id, callback_name)
    if err:
        msg, status = err
        return msg, status
    desc, cb_info = pair
    try:
        result = desc.invoke_callback(callback_name)
        if not isinstance(result, dict):
            return (
                f"Callback did not return a dict: got "
                f"{type(result).__name__}"
            ), 500
        return render_template(
            'partials/data_file_dict.html',
            items=result,
            title=callback_name,
        )
    except Exception as e:
        return f"Error rendering callback: {str(e)}", 500


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