"""Generic Data file serving routes.

These work for any DataType — the file on disk is streamed directly with a
guessed MIME type, and image files get an on-disk-cached JPEG thumbnail.

This module also hosts the per-target user-upload flow (the ``/data/upload/...``
endpoints): a modal that lets a user attach files to one or more
Animal / Ear instances. See ``docs/uploads.md`` and
:mod:`colony_manager_gui.services.uploads`.
"""
import hashlib
import logging
import mimetypes
import os

from flask import (
    Blueprint, Response, abort, current_app, flash, redirect, render_template,
    request, send_file, url_for,
)
from werkzeug.utils import safe_join

from colony_manager.models import Data

from .. import db
from ..forms.common import UploadFilesForm
from ..services import uploads as upload_service
from .util import flash_form_errors, get_or_404


log = logging.getLogger(__name__)

data_files_bp = Blueprint('data_files', __name__)


# Target_type → endpoint the user should land on after an upload finishes.
# Lives here (not in the service) so the routes module owns URL-shape
# concerns; extending to a new target_type adds an entry alongside the
# ``TARGET_LOADERS`` entry in the service.
_TARGET_DETAIL_ENDPOINT = {
    'animal': ('animals.view_animal', 'animal_id'),
    'ear':    ('histology.view_ear',  'ear_id'),
}


def _detail_url(target_type, target_id):
    """Return the entity-detail URL for redirecting after an upload."""
    endpoint, arg = _TARGET_DETAIL_ENDPOINT[target_type]
    return url_for(endpoint, **{arg: target_id})


IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff', '.webp'}


def _resolve_disk_path(data_file):
    """Return the absolute on-disk path, ensuring it stays under the location root."""
    base = os.path.realpath(data_file.location.base_path)
    candidate = safe_join(base, data_file.relative_path)
    if candidate is None:
        abort(404)
    full = os.path.realpath(candidate)
    if os.path.commonpath([base, full]) != base:
        abort(404)
    if not os.path.exists(full):
        abort(404)
    return full


def _is_image(name):
    ext = os.path.splitext(name)[1].lower()
    return ext in IMAGE_EXTS


@data_files_bp.route('/data/<int:data_id>/raw')
def view_raw(data_id) -> Response | str:
    data_file = get_or_404(Data, data_id)
    full = _resolve_disk_path(data_file)
    mimetype, _ = mimetypes.guess_type(full)
    return send_file(full, mimetype=mimetype or 'application/octet-stream')


@data_files_bp.route('/data/<int:data_id>/thumbnail')
def view_thumbnail(data_id) -> Response | str:
    data_file = get_or_404(Data, data_id)
    if not _is_image(data_file.name):
        abort(404)

    full = _resolve_disk_path(data_file)
    cache_dir = current_app.config['THUMBNAIL_CACHE_DIR']
    max_size = current_app.config['THUMBNAIL_MAX_SIZE']

    # Cache key incorporates source path + mtime + size so a re-saved file
    # invalidates automatically.
    stat = os.stat(full)
    key = hashlib.sha1(
        f'{full}|{stat.st_mtime_ns}|{stat.st_size}|{max_size}'.encode('utf-8')
    ).hexdigest()
    cache_path = os.path.join(cache_dir, key[:2], key[2:] + '.jpg')

    if not os.path.exists(cache_path):
        from PIL import Image, ImageOps

        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with Image.open(full) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            img.thumbnail((max_size, max_size))
            img.save(cache_path, format='JPEG', quality=82, optimize=True)

    return send_file(cache_path, mimetype='image/jpeg')


# ---------------------------------------------------------------------------
# Upload-from-UI flow
# ---------------------------------------------------------------------------

def _resolve_target_or_404(target_type, target_id):
    """Load the launching target instance, 404 if unknown / wrong type."""
    if target_type not in upload_service.TARGET_LOADERS:
        abort(404, description=f'Unknown target_type {target_type!r}')
    loader, _, _ = upload_service.TARGET_LOADERS[target_type]
    instance = loader(db.session, target_id)
    if instance is None:
        abort(404, description=f'{target_type} {target_id} not found')
    return instance


def _populate_form_choices(form, target_type, *, datatype_id=None,
                           datatypes=None):
    """Populate the cascading datatype + location selects on the form.

    Used by both ``upload_modal`` (initial render) and ``upload_files``
    (post-submit revalidation). Returns ``(datatypes, locations)`` so
    the modal route can hand the resolved ``locations`` to the initial
    template render — without that, the included
    ``upload_locations_select.html`` partial would see ``locations``
    undefined and render the empty-state.
    """
    if datatypes is None:
        datatypes = upload_service.candidate_datatypes(db.session, target_type)
    form.datatype.choices = [(d.id, d.name) for d in datatypes]

    if datatype_id is None and datatypes:
        datatype_id = datatypes[0].id
    if datatype_id is not None:
        locations = upload_service.candidate_locations(db.session, datatype_id)
    else:
        locations = []
    form.location.choices = [(loc.id, loc.base_path) for loc in locations]
    return datatypes, locations


@data_files_bp.route('/data/upload/<target_type>/<int:target_id>/modal')
def upload_modal(target_type, target_id) -> Response | str:
    """Render the upload modal body. Loaded via ``hx-get`` into ``#modalBody``."""
    target = _resolve_target_or_404(target_type, target_id)
    form = UploadFilesForm()
    datatypes, locations = _populate_form_choices(form, target_type)
    if datatypes:
        form.datatype.data = datatypes[0].id
        if form.location.choices:
            form.location.data = form.location.choices[0][0]
    return render_template(
        'partials/upload_modal.html',
        form=form,
        target=target,
        target_type=target_type,
        initial_label=upload_service.target_label(target_type, target),
        has_choices=bool(datatypes),
        locations=locations,
    )


@data_files_bp.route('/data/upload/<target_type>/search')
def upload_target_search(target_type) -> Response | str:
    """Typeahead endpoint for the Targets picker."""
    if target_type not in upload_service.TARGET_LOADERS:
        abort(404, description=f'Unknown target_type {target_type!r}')
    q = request.args.get('q', '')
    try:
        matches = upload_service.search_targets(db.session, target_type, q)
    except upload_service.UploadError:
        matches = []
    return render_template(
        'partials/upload_target_results.html',
        matches=matches,
    )


@data_files_bp.route('/data/upload/<target_type>/<int:target_id>/locations')
def upload_locations(target_type, target_id) -> Response | str:
    """HTMX cascade: render the Location ``<select>`` for a chosen DataType."""
    if target_type not in upload_service.TARGET_LOADERS:
        abort(404, description=f'Unknown target_type {target_type!r}')
    raw = request.args.get('datatype', '')
    try:
        datatype_id = int(raw) if raw else None
    except ValueError:
        datatype_id = None
    locations = (
        upload_service.candidate_locations(db.session, datatype_id)
        if datatype_id is not None else []
    )
    return render_template(
        'partials/upload_locations_select.html',
        locations=locations,
    )


@data_files_bp.route('/data/upload/<target_type>/<int:target_id>',
                     methods=['POST'])
def upload_files(target_type, target_id):
    """Handle the multipart upload. One service call per file; one commit."""
    _resolve_target_or_404(target_type, target_id)  # 404 on bad URL
    detail_url = _detail_url(target_type, target_id)

    form = UploadFilesForm()
    # Repopulate choices so SelectField.validate accepts the posted ids
    # (WTForms refuses values absent from ``choices``).
    posted_dt = request.form.get('datatype', type=int)
    _populate_form_choices(form, target_type, datatype_id=posted_dt)

    if not form.validate_on_submit():
        flash_form_errors(form)
        return redirect(detail_url)

    raw_target_ids = request.form.getlist('targets')
    try:
        target_ids = [int(x) for x in raw_target_ids if x]
    except ValueError:
        flash('Invalid target ids submitted.', 'danger')
        return redirect(detail_url)
    if not target_ids:
        flash('At least one target is required.', 'danger')
        return redirect(detail_url)

    try:
        targets = upload_service.resolve_targets(
            db.session, target_type, target_ids,
        )
    except upload_service.UploadError as exc:
        flash(str(exc), 'danger')
        return redirect(detail_url)

    files = request.files.getlist('files')
    files = [fs for fs in files if fs and fs.filename]
    if not files:
        flash('No files were uploaded.', 'danger')
        return redirect(detail_url)

    # Per-file notes arrive in document order (one ``<input
    # name="file_notes">`` per file rendered by Alpine). Pad with
    # empty strings if the user removed a file from the OS dialog
    # without the picker re-firing; truncate if somehow more notes
    # than files.
    raw_notes = request.form.getlist('file_notes')
    per_file_notes = (raw_notes + [''] * len(files))[:len(files)]

    written_paths = []
    try:
        for fs, file_notes in zip(files, per_file_notes):
            result = upload_service.handle_upload(
                db.session,
                target_type=target_type,
                targets=targets,
                datatype_id=form.datatype.data,
                location_id=form.location.data,
                date=form.date.data,
                notes=(file_notes or None),
                file_storage=fs,
            )
            written_paths.append(result.full_path)
        db.session.commit()
    except upload_service.UploadError as exc:
        db.session.rollback()
        _cleanup_paths(written_paths)
        flash(str(exc), 'danger')
        return redirect(detail_url)
    except Exception:
        db.session.rollback()
        _cleanup_paths(written_paths)
        log.exception('Upload failed for %s %s', target_type, target_id)
        flash('Upload failed unexpectedly; see server logs.', 'danger')
        return redirect(detail_url)

    flash(
        f'Uploaded {len(written_paths)} '
        f'file{"" if len(written_paths) == 1 else "s"}.',
        'success',
    )
    return redirect(detail_url)


def _cleanup_paths(paths):
    """Best-effort removal of files written by a partially-failed batch."""
    for p in paths:
        try:
            os.remove(p)
        except OSError as exc:
            log.warning('Could not remove partial upload %s: %s', p, exc)
