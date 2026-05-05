"""Generic Data file serving routes.

These work for any DataType — the file on disk is streamed directly with a
guessed MIME type, and image files get an on-disk-cached JPEG thumbnail.
"""
import hashlib
import mimetypes
import os

from flask import Blueprint, abort, current_app, send_file
from werkzeug.utils import safe_join

from colony_manager.models import Data


data_files_bp = Blueprint('data_files', __name__)


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
def view_raw(data_id):
    data_file = Data.query.get_or_404(data_id)
    full = _resolve_disk_path(data_file)
    mimetype, _ = mimetypes.guess_type(full)
    return send_file(full, mimetype=mimetype or 'application/octet-stream')


@data_files_bp.route('/data/<int:data_id>/thumbnail')
def view_thumbnail(data_id):
    data_file = Data.query.get_or_404(data_id)
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
