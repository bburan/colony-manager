from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Ear, Animal, ConfocalImage, ImmunolabelingPanel, ConfocalImageType
from app.forms import HistologyForm, NoteForm, ConfocalImageForm
from app.routes.util import flash_form_errors

histology_bp = Blueprint('histology', __name__)

@histology_bp.route('/')
def list_histology():
    query = Ear.query.join(Animal)

    immunolabel_filter = request.args.get('immunolabel_filter', 'all')
    if immunolabel_filter == 'labeled':
        query = query.filter(Ear.immunolabel_date != None)
    elif immunolabel_filter == 'not_labeled':
        query = query.filter(Ear.immunolabel_date == None)

    sort_by = request.args.get('sort_by', 'id')
    if sort_by == 'euthanasia':
        query = query.order_by(Animal.termination_date.desc().nulls_last())
    else:
        query = query.order_by(Ear.id.desc())

    analysis_filter = request.args.get('analysis_filter', 'all')
    if analysis_filter != 'all':
        query = query.join(ConfocalImage).filter(ConfocalImage.status == analysis_filter)

    ears = query.distinct().all()
    panels = ImmunolabelingPanel.query.all()

    return render_template(
        'histology.html',
        ears=ears,
        #panels=panels,
        filters={
            'immunolabel_filter': immunolabel_filter,
            'sort_by': sort_by,
            'analysis_filter': analysis_filter,
        },
    )


@histology_bp.route('/ears/<int:ear_id>')
def view_ear(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    return render_template('view_ear.html', ear=ear)


@histology_bp.route('/ears/<int:ear_id>/update', methods=['POST'])
def update_ear(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = HistologyForm(obj=ear)
    if form.validate_on_submit():
        form.populate_obj(ear)
        db.session.commit()
        flash('Ear updated.', 'success')
    else:
        flash_form_errors(form, title="Error updating ear")
    return redirect(request.referrer or url_for('histology.list_histology'))


# --- Confocal Image Routes ---
@histology_bp.route('/ears/<int:ear_id>/confocal_images/create', methods=['POST'])
def create_confocal_image(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = ConfocalImageForm()
    form.image_type.choices = [(t.id, t.name) for t in ConfocalImageType.query.all()]

    if form.validate_on_submit():
        for freq_str in form.frequencies.data:
            new_image = ConfocalImage(
                ear_id=ear.id,
                frequency=float(freq_str),
                image_type=form.image_type.data,
                notes=form.notes.data,
                status='pending',
            )
            db.session.add(new_image)
        db.session.commit()
        flash(f'Images added for {ear.animal.custom_id} {ear.side}', 'success')
    else:
        flash_form_errors(form, title="Error adding images")
    return redirect(request.referrer or url_for('histology.list_histology'))

@histology_bp.route('/confocal_images/<int:image_id>/update', methods=['POST'])
def update_confocal_image(image_id):
    img = ConfocalImage.query.get_or_404(image_id)
    img.status = request.form.get('status')
    img.notes = request.form.get('notes')
    db.session.commit()
    return redirect(request.referrer or url_for('histology.list_histology'))

@histology_bp.route('/confocal_images/<int:image_id>/delete', methods=['POST'])
def delete_confocal_image(image_id):
    img = ConfocalImage.query.get_or_404(image_id)
    try:
        db.session.delete(img)
        db.session.commit()
        flash('Imaging record deleted successfully.', 'info')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting record', 'danger')
    return redirect(request.referrer or url_for('histology.list_histology'))

# --- Modal Routes ---
@histology_bp.route('/ears/<int:ear_id>/edit_note_modal')
def edit_ear_note_modal(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = NoteForm(obj=ear)
    return render_template('partials/form_modal.html', form=form, item=ear,
                           label=f'Edit note for {ear.animal.custom_id} {ear.side}', submit_url=url_for('histology.update_ear', ear_id=ear.id))

@histology_bp.route('/ears/<int:ear_id>/edit_histology_modal')
def edit_ear_histology_modal(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = HistologyForm(obj=ear)
    return render_template('partials/form_modal.html', form=form, item=ear,
                           label=f'Edit histology for {ear.animal.custom_id} {ear.side}', submit_url=url_for('histology.update_ear', ear_id=ear.id))

@histology_bp.route('/ears/<int:ear_id>/confocal_images/create_modal')
def create_confocal_images_modal(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    form = ConfocalImageForm()
    return render_template('partials/form_modal.html', form=form, item=ear,
                           label=f'Add images for {ear.animal.custom_id} {ear.side}', submit_url=url_for('histology.create_confocal_image', ear_id=ear.id))

# --- AJAX Popover Routes ---
@histology_bp.route('/ears/<int:ear_id>/images_popover')
def view_ear_images_popover(ear_id):
    ear = Ear.query.get_or_404(ear_id)
    return render_template(
        'partials/ear_images_popover.html',
        ear=ear,
    )