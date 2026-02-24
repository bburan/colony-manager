from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import BreedingPair, Litter, Animal, Cage
from app.forms import BreedingPairForm, LitterForm, LitterDeleteForm, WeaningForm

from app.routes.util import flash_form_errors

breeding_bp = Blueprint('breeding', __name__)

@breeding_bp.route('/')
def list_breeding_pairs():
    pairs = BreedingPair.query.order_by(BreedingPair.is_active.desc(), BreedingPair.id.desc()).all()
    return render_template('breeding.html', pairs=pairs)

@breeding_bp.route('/<int:breeding_pair_id>')
def view_breeding_pair(breeding_pair_id):
    breeding_pair = BreedingPair.query.get_or_404(breeding_pair_id)
    return render_template('view_breeding_pair.html', pair=breeding_pair)

@breeding_bp.route('/create', methods=['POST'])
def create_breeding_pair():
    form = BreedingPairForm()
    if form.validate_on_submit():
        if form.male_animal.data is None:
            male_animal = Animal(
                custom_id=f'{form.custom_id.data}-M',
                species=form.male_species.data,
                dob=form.male_dob.data,
                source=form.male_source.data,
                notes=form.male_notes.data,
                sex='male',
            )
            db.session.add(male_animal)
        else:
            male_animal = form.male_animal.data
        if form.female_animal.data is None:
            female_animal = Animal(
                custom_id=f'{form.custom_id.data}-F',
                species=form.female_species.data,
                dob=form.female_dob.data,
                source=form.female_source.data,
                notes=form.female_notes.data,
                sex='female',
            )
            db.session.add(female_animal)
        else:
            female_animal = form.female_animal.data

        if female_animal.species != male_animal.species:
            flash('Species of male and female must be the same.', 'danger')
            return redirect(request.referrer or url_for('view_breeding_pairs'))

        cage = Cage(
            custom_id=form.custom_id.data,
            species=form.male_species.data,
        )
        male_animal.cage = cage
        female_animal.cage = cage
        db.session.add(cage)

        pair = BreedingPair(
            custom_id=form.custom_id.data,
            male=male_animal,
            female=female_animal,
            start_date=form.start_date.data,
        )
        db.session.add(pair)
        db.session.commit()
        flash('New breeding pair created successfully.', 'success')
    else:
        flash_form_errors(form, 'Error creating breeding pair')
    return redirect(request.referrer or url_for('breeding.list_breeding_pairs'))


@breeding_bp.route('/<int:breeding_pair_id>/deactivate', methods=['POST'])
def deactivate_breeding_pair(breeding_pair_id):
    breeding_pair = BreedingPair.query.get_or_404(breeding_pair_id)
    breeding_pair.is_active = False
    db.session.commit()
    flash(f'Breeding pair {breeding_pair.custom_id} deactivated.', 'info')
    return redirect(request.referrer or url_for('breeding.list_breeding_pairs'))

@breeding_bp.route('/<int:breeding_pair_id>/reactivate', methods=['POST'])
def reactivate_breeding_pair(breeding_pair_id):
    pair = BreedingPair.query.get_or_404(pair_id)
    pair.is_active = True
    db.session.commit()
    flash(f'Breeding pair {pair.custom_id} reactivated.', 'success')
    return redirect(request.referrer or url_for('view_breeding_pairs'))


# Nested Litter Routes
@breeding_bp.route('/<int:breeding_pair_id>/litters/create', methods=['POST'])
def create_litter(breeding_pair_id):
    pair = BreedingPair.query.get_or_404(breeding_pair_id)
    form = LitterForm()
    if form.validate_on_submit():
        litter = Litter(breeding_pair=pair)
        form.populate_obj(litter)
        db.session.add(litter)
        db.session.commit()
        flash(f'Litter recorded for breeding pair {pair.custom_id}.', 'success')
    else:
        flash_form_errors(form.errors, 'Error creating litter')
    return redirect(request.referrer or url_for('breeding.view_breeding_pair', breeding_pair_id=pair.id))

@breeding_bp.route('/litters/<int:litter_id>/update', methods=['POST'])
def update_litter(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    form = LitterForm()
    if form.validate_on_submit():
        form.populate_obj(litter)
        db.session.commit()
        flash('Litter updated successfully.', 'success')
    else:
        flash_form_errors(form.errors, 'Error updating litter')
    return redirect(request.referrer or url_for('breeding.view_breeding_pair', pair_id=litter.breeding_pair_id))


@breeding_bp.route('/litters/<int:litter_id>/delete', methods=['POST'])
def delete_litter(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    pair_id = litter.breeding_pair_id
    db.session.delete(litter)
    db.session.commit()
    flash('Litter has been removed.', 'success')
    return redirect(request.referrer or url_for('breeding.view_breeding_pair', pair_id=pair_id))


@breeding_bp.route('/litters/<int:litter_id>/wean', methods=['GET', 'POST'])
def wean_litter(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    form = WeaningForm()
    if form.validate_on_submit():
        for cage_data in form.cages:
            cage = Cage(
                custom_id=cage_data['custom_id'].data,
                species=litter.breeding_pair.male.species,
            )
            for i in range(cage_data['count'].data):
                animal = Animal(
                    cage=cage,
                    sex=cage_data['sex'].data,
                    dob=litter.dob,
                    species=cage.species,
                    breeding_pair=litter.breeding_pair,
                )
                db.session.add(animal)
            db.session.add(cage)
        litter.wean_date = form.wean_date.data
        db.session.commit()
        flash(f'Litter weaned into {len(form.cages)} new cages.', 'success')
    else:
        flash_form_errors(form, 'Error weaning litter')
    return redirect(request.referrer or url_for('breeding_pair_detail', pair_id=litter.breeding_pair_id))

# --- Modal Routes ---

@breeding_bp.route('/create_modal')
def create_breeding_pair_modal():
    form = BreedingPairForm()
    return render_template('partials/bp_form_modal.html', form=form, item=None,
                           label='Add Breeding Pair', submit_url=url_for('breeding.create_breeding_pair'))

@breeding_bp.route('/<int:breeding_pair_id>/litters/create_modal')
def create_litter_modal(breeding_pair_id):
    pair = BreedingPair.query.get_or_404(breeding_pair_id)
    form = LitterForm()
    return render_template('partials/form_modal.html', form=form, item=pair,
                           label=f'Add litter for {pair.custom_id}', submit_url=url_for('breeding.create_litter', breeding_pair_id=pair.id))

@breeding_bp.route('/litters/<int:litter_id>/edit_modal')
def edit_litter_modal(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    form = LitterForm(obj=litter)
    return render_template('partials/form_modal.html', form=form, item=litter,
                           label=f'Edit litter for {litter.breeding_pair.custom_id}', submit_url=url_for('breeding.update_litter', litter_id=litter.id))

@breeding_bp.route('/litters/<int:litter_id>/delete_modal')
def delete_litter_modal(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    form = LitterDeleteForm(obj=litter)
    return render_template('partials/form_modal.html', form=form, item=litter,
                           label=f'Delete litter from {litter.breeding_pair.custom_id}', submit_url=url_for('breeding.delete_litter', litter_id=litter.id))

@breeding_bp.route('/litters/<int:litter_id>/wean_modal')
def wean_litter_modal(litter_id):
    litter = Litter.query.get_or_404(litter_id)
    form = WeaningForm()
    return render_template('partials/bp_wean_form_modal.html', form=form, item=litter,
                           label=f'Wean litter from {litter.breeding_pair.custom_id}', submit_url=url_for('breeding.wean_litter', litter_id=litter.id))