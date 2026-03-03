import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Animal, AnimalEvent, AnimalProcedure, Cage, Study, Ear, Feed, FeedLog, WeightLog
from app.forms import AnimalForm, AnimalEventForm, AnimalCustomIDForm, NoteForm, TerminationForm, QuickAddToStudyForm, DailyLogForm, mark_disabled
from app.routes.util import flash_form_errors

from app import forms

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
    weights = WeightLog.query.filter_by(animal_id=animal_id).order_by(WeightLog.date.asc()).all()
    feedings = FeedLog.query.filter_by(animal_id=animal_id).all()
    history = {}
    last_baseline = None
    for w in weights:
        if w.baseline:
            last_baseline = w.weight
            baseline_pct = None
        elif last_baseline is None:
            baseline_pct = None
        else:
            baseline_pct = int(round((w.weight / last_baseline) * 100))
        history[w.date] = {
            'weight': w.weight,
            'baseline_pct': baseline_pct,
            'notes': w.notes,
            'feed': {},
            'total_feed': 0,
            'baseline': w.baseline
        }
    for f in feedings:
        day = history.setdefault(f.date, {'weight': '&emdash;', 'note': '', 'feed': {}, 'total_feed': 0})
        day['feed'][f.feed_id] = f.quantity
        day['total_feed'] += (f.quantity * f.feed_type.weight)
    history = dict(sorted(history.items(), key=lambda item: item[0], reverse=True))
    return render_template('view_animal.html', animal=animal, weight_history=history, feeds=feed)


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
        animal.termination_date = form.termination_date.data
        animal.termination_reason = form.termination_reason.data
        animal.ears_extracted = form.ears_extracted.data
        if animal.ears_extracted in ['Left', 'Both']:
            db.session.add(Ear(animal_id=animal.id, side='Left'))
        if animal.ears_extracted in ['Right', 'Both']:
            db.session.add(Ear(animal_id=animal.id, side='Right'))
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
        form.populate_obj(event)
        db.session.add(event)
        db.session.commit()
        flash('Event created successfully.', 'success')
    else:
        flash_form_errors(form, f'Error creating event')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=event.animal_id))

@animals_bp.route('/events/<int:event_id>/update', methods=['POST'])
def update_animal_event(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    form = AnimalEventForm()
    if form.validate_on_submit():
        form.populate_obj(event)
        db.session.commit()
        flash('Event updated successfully.', 'success')
    else:
        flash_form_errors(form, f'Error updating event')
    return redirect(request.referrer or url_for('animals.view_animal', animal_id=event.animal_id))


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
    logs = WeightLog.query.filter_by(animal_id=animal.id, date=form.date.data).all()
    if len(logs) != 0:
        flash(f'Log for {animal.display_id} already exists for {form.date.data.strftime("%B %d, %Y")}.', 'danger')
        return redirect(request.referrer or url_for('animals.view_animal', animal_id=animal.id))

    if form.validate_on_submit():
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
    weight = WeightLog.query.filter_by(animal_id=animal.id, date=date).one()
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
    return render_template('partials/form_modal.html', form=form, item=animal,
                           label=f'Create event for {animal.display_id}', submit_url=url_for('animals.create_animal_event', animal_id=animal.id))

@animals_bp.route('/events/<int:event_id>/edit_modal')
def edit_animal_event_modal(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    form = AnimalEventForm(obj=event)
    return render_template('partials/form_modal.html', form=form, item=event,
                           label=f'Edit event for {event.animal.display_id}', submit_url=url_for('animals.update_animal_event', event_id=event.id))

@animals_bp.route('/events/<int:event_id>/delete_modal')
def delete_animal_event_modal(event_id):
    event = AnimalEvent.query.get_or_404(event_id)
    form = AnimalEventForm(obj=event)
    mark_disabled(form)
    return render_template('partials/form_modal.html', form=form, item=event,
                           label=f'Remove event for {event.animal.display_id}', submit_url=url_for('animals.delete_animal_event', event_id=event.id))


# --- Animal Weight/Feed Modals ---
@animals_bp.route('/<int:animal_id>/weight-feed/create_modal')
def create_animal_daily_log_modal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    feed = Feed.query.order_by(Feed.weight).all()
    feed_data = [{'feed_id': f.id, 'feed_name': f.name, 'feed_weight': f.weight, 'amount': 0} for f in feed]
    form = DailyLogForm(feedings=feed_data)
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
    weight_log = WeightLog.query.filter_by(animal_id=animal.id, date=date).one()
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
    return animal, DailyLogForm(
        feedings=feed_data,
        date=date,
        weight=weight_log.weight,
        notes=weight_log.notes,
        baseline=weight_log.baseline,
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