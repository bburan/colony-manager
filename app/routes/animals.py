from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Animal, AnimalEvent, AnimalProcedure, Cage, Study, Ear
from app.forms import AnimalForm, AnimalEventForm, AnimalEventDeleteForm, AnimalCustomIDForm, NoteForm, TerminationForm, QuickAddToStudyForm

from app.routes.util import flash_form_errors

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
    return render_template('view_animal.html', animal=animal)


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
    form = AnimalEventDeleteForm(obj=event)
    return render_template('partials/form_modal.html', form=form, item=event,
                           label=f'Remove event for {event.animal.display_id}', submit_url=url_for('animals.delete_animal_event', event_id=event.id))

# --- AJAX Popover Routes ---
@animals_bp.route('/<int:animal_id>/events_popover')
def view_animal_events_popover(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    return render_template(
        'partials/event_popover.html',
        animal=animal,
    )
