"""User-driven file uploads — the per-file pipeline used by the upload routes.

The sync core (``colony_manager_gui.sync``) discovers files dropped into
``DataLocation`` directories. This module is the inverse on-ramp: a user
picks one or more targets (Animal, Ear, ...) on an entity detail page,
drops files into the upload modal, and each file is renamed by the
target's :class:`DataTypeDescription` subclass, written into the chosen
``DataLocation``, and persisted as a polymorphic ``Data`` row already
linked to every chosen target.

Generic over ``target_type`` via :data:`TARGET_LOADERS`: supporting a new
target type (``animal_event``, ``confocal_image``, ...) is one entry there
and a button on the entity template — no new routes / forms / services.

See ``docs/uploads.md`` for the user-facing contract.
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List

from sqlalchemy import select
from werkzeug.utils import safe_join

from colony_manager.datatypes import is_upload_capable, load_description_class
from colony_manager.enums import DataStatus
from colony_manager.models import (
    Animal, DATA_SUBCLASSES, Data, DataLocation, DataType, Ear,
)

from .data_linking import to_json_safe


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extension point
# ---------------------------------------------------------------------------
#
# To support a new target_type:
#   1. Add an entry below — ``(loader_fn, m2m_attr, label_fn)``.
#   2. Make sure the polymorphic ``Data`` subclass for that target_type
#      already has the m2m collection ``m2m_attr`` (the existing ones do).
#   3. Add an Upload button on the entity's detail template using
#      ``target_type=<new>``. No route / form / service changes needed.
#
# ``loader_fn(session, id)``  → instance or None
# ``m2m_attr``                → name of the ``Data`` subclass collection
#                               (matches ``sync._TARGET_M2M_ATTR``)
# ``label_fn(instance)``      → short user-facing label used in chips +
#                               typeahead results.

def _animal_label(animal):
    return animal.custom_id or f'Animal #{animal.id}'


def _ear_label(ear):
    cid = ear.animal.custom_id if ear.animal else f'#{ear.animal_id}'
    return f'{cid} {ear.side}'


TARGET_LOADERS = {
    'animal': (lambda s, i: s.get(Animal, i), 'animals', _animal_label),
    'ear':    (lambda s, i: s.get(Ear, i),    'ears',    _ear_label),
}


def target_label(target_type, instance):
    """Return the chip/typeahead label for ``instance``.

    Convenience wrapper exposed for templates (registered as a jinja
    global by the routes module).
    """
    _, _, label_fn = TARGET_LOADERS[target_type]
    return label_fn(instance)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class UploadError(Exception):
    """A user-correctable error in the upload flow.

    The route catches this, flashes the message, and redirects back
    rather than letting a 500 escape.
    """


# ---------------------------------------------------------------------------
# Candidate filtering (drives the modal's Type / Location dropdowns)
# ---------------------------------------------------------------------------

def candidate_datatypes(session, target_type):
    """DataTypes that can receive a user upload for ``target_type``.

    A DataType qualifies when all three hold:
      * ``target_type`` matches (polymorphic discriminator);
      * a ``description_class`` is configured and loads successfully;
      * the loaded class :func:`is_upload_capable` (defines ``upload_filename``);
      * at least one ``DataLocation`` exists (nowhere to write otherwise).

    Returns DataTypes ordered by name.
    """
    rows = session.scalars(
        select(DataType)
        .where(DataType.target_type == target_type)
        .where(DataType.description_class.is_not(None))
        .order_by(DataType.name)
    ).all()
    out = []
    for dt in rows:
        if not dt.locations:
            continue
        try:
            cls = load_description_class(dt.description_class)
        except Exception:
            continue
        if not is_upload_capable(cls):
            continue
        out.append(dt)
    return out


def candidate_locations(session, datatype_id):
    """Locations attached to ``datatype_id``, ordered by base_path."""
    return session.scalars(
        select(DataLocation)
        .where(DataLocation.datatype_id == datatype_id)
        .order_by(DataLocation.base_path)
    ).all()


# ---------------------------------------------------------------------------
# Target picker (typeahead + post-submit resolution)
# ---------------------------------------------------------------------------

def search_targets(session, target_type, q, *, limit=15):
    """Typeahead match for the modal's Targets picker.

    Returns up to ``limit`` items, each ``(id, label)``. Case-insensitive
    substring match on ``Animal.custom_id``. Empty/whitespace ``q``
    returns ``[]`` so the dropdown stays empty until the user types.
    """
    q = (q or '').strip()
    if not q:
        return []

    pattern = f'%{q}%'
    if target_type == 'animal':
        stmt = (
            select(Animal)
            .where(Animal.custom_id.ilike(pattern))
            .order_by(Animal.custom_id)
            .limit(limit)
        )
        return [(a.id, _animal_label(a)) for a in session.scalars(stmt).all()]
    if target_type == 'ear':
        stmt = (
            select(Ear).join(Animal, Ear.animal_id == Animal.id)
            .where(Animal.custom_id.ilike(pattern))
            .order_by(Animal.custom_id, Ear.side)
            .limit(limit)
        )
        return [(e.id, _ear_label(e)) for e in session.scalars(stmt).all()]
    raise UploadError(f'Unknown target_type: {target_type!r}')


def resolve_targets(session, target_type, target_ids):
    """Load each id, refusing if any is missing or of the wrong type.

    Used at POST time to turn ``request.form.getlist('targets')`` into a
    concrete list of model instances, and to refuse forged ids whose
    polymorphic identity does not match the URL's ``target_type``.

    Returns the instances in the order requested.

    Raises
    ------
    UploadError
        If any id is unknown or mismatches ``target_type``.
    """
    if target_type not in TARGET_LOADERS:
        raise UploadError(f'Unknown target_type: {target_type!r}')
    loader, _, _ = TARGET_LOADERS[target_type]

    out = []
    seen = set()
    for tid in target_ids:
        if tid in seen:
            continue
        seen.add(tid)
        instance = loader(session, tid)
        if instance is None:
            raise UploadError(f'No {target_type} with id {tid}.')
        out.append(instance)
    if not out:
        raise UploadError('At least one target is required.')
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _seeded_metadata(target_type, targets, date):
    """Build a ``parsed_metadata`` dict equivalent to what a sync re-parse
    would have produced.

    Re-using the parser's key shape (lists for ``animal_id`` / ``side``)
    means the existing rematch / candidate paths keep working unchanged
    against uploaded rows — uploads are indistinguishable from
    sync-discovered rows once on disk.
    """
    if target_type == 'animal':
        meta = {'animal_id': [t.custom_id for t in targets]}
    elif target_type == 'ear':
        meta = {
            'animal_id': [t.animal.custom_id for t in targets],
            'side': [t.side for t in targets],
        }
    else:
        meta = {}
    if date is not None:
        meta['date'] = date
    return to_json_safe(meta)


def _sanitize_relative_path(raw):
    """Normalize a description-class-returned path into a safe relative path.

    Accepts either a plain basename (``A001.jpg``) or a slash-separated
    relative path (``A001/photos/2026-06-03.jpg``). The description
    class is trusted to produce a sensible name, so unlike
    ``werkzeug.utils.secure_filename`` we deliberately preserve spaces
    and the broader ASCII printable range — the sync parser's
    multi-animal filename convention
    (``G014-4L G018-3R - dissection notes.jpg``) uses spaces, and
    forcing underscores here would break round-trip re-parsing.

    What we DO strip / normalize:
      * backslashes are folded to forward slashes so the DB stores one
        canonical separator (matches sync's ``replace("\\\\", "/")``).
      * NUL + ASCII control characters (anything < 0x20 or == 0x7F).
      * leading dots on every segment (no hidden files / Unix dotfiles).
      * leading/trailing whitespace per segment.
      * empty segments and ``.`` / ``..`` segments (so a stray
        ``A001/../B005/...`` cannot escape the directory tree even
        before ``safe_join`` sees it).

    Returns the cleaned forward-slash relative path. May be ``''`` if
    the input had no usable content.
    """
    parts = raw.replace('\\', '/').split('/')
    cleaned_parts = []
    for part in parts:
        cleaned = ''.join(c for c in part if ord(c) >= 0x20 and ord(c) != 0x7F)
        cleaned = cleaned.strip().lstrip('.')
        if not cleaned or cleaned in ('.', '..'):
            continue
        cleaned_parts.append(cleaned)
    return '/'.join(cleaned_parts)


def _resolve_relative_path(location_dir, rel_path):
    """Suffix the *filename* of ``rel_path`` until the path is free.

    Both the on-disk file and the ``(location_id, relative_path)``
    unique constraint in the DB are namespaced by location, so checking
    the filesystem is sufficient — the route is single-threaded per
    request and a same-instant duplicate is fine to surface as an
    IntegrityError.

    The suffix attaches to the basename stem, not to a directory
    component, so a collision between ``A001/x.jpg`` and an existing
    ``A001/x.jpg`` resolves to ``A001/x_1.jpg`` (not ``A001_1/x.jpg``).
    """
    parts = rel_path.split('/')
    if os.path.exists(os.path.join(location_dir, *parts)):
        dir_parts, filename = parts[:-1], parts[-1]
        stem, ext = os.path.splitext(filename)
        counter = 1
        while True:
            candidate_name = f'{stem}_{counter}{ext}'
            candidate_parts = dir_parts + [candidate_name]
            if not os.path.exists(os.path.join(location_dir, *candidate_parts)):
                parts = candidate_parts
                break
            counter += 1
    return '/'.join(parts)


# ---------------------------------------------------------------------------
# Result + main entry point
# ---------------------------------------------------------------------------

@dataclass
class UploadResult:
    """Outcome of :func:`handle_upload` — used by the route for rollback.

    ``full_path`` is the absolute realpath where the file was written.
    The route accumulates these so a partial-batch failure can remove
    the already-written files before re-raising / flashing.
    """
    row: Data
    full_path: str


def handle_upload(
    session, *,
    target_type,
    targets: List,
    datatype_id,
    location_id,
    date,
    notes,
    file_storage,
):
    """Persist one uploaded ``FileStorage`` as a polymorphic ``Data`` row.

    Parameters
    ----------
    session
        SQLAlchemy session. The function ``session.add()``s but does
        NOT commit — the route commits once per request so a batch
        upload is atomic.
    target_type : str
        Polymorphic discriminator. Must be a key of :data:`TARGET_LOADERS`.
    targets : list
        Non-empty list of target instances (resolved by
        :func:`resolve_targets`). The new ``Data`` row is linked to
        every entry via the polymorphic m2m collection.
    datatype_id, location_id : int
        Chosen DataType and DataLocation. Validated to be consistent
        with ``target_type`` and with each other.
    date : datetime.date
        User-supplied date written to ``Data.date`` and forwarded into
        ``parsed_metadata['date']``.
    notes : str | None
        User-supplied notes written to ``Data.notes``.
    file_storage : werkzeug.datastructures.FileStorage
        The uploaded file. Its ``.filename`` is fed into
        ``upload_filename``; its bytes are streamed to disk via
        ``FileStorage.save``.

    Returns
    -------
    UploadResult

    Raises
    ------
    UploadError
        On validation failures (wrong target_type, missing description
        class, non-upload-capable description class, empty rename,
        ...). The route catches and surfaces these as flash messages.
    """
    if target_type not in TARGET_LOADERS:
        raise UploadError(f'Unknown target_type: {target_type!r}')
    if not targets:
        raise UploadError('At least one target is required.')

    datatype = session.get(DataType, datatype_id)
    if datatype is None:
        raise UploadError(f'Unknown DataType id {datatype_id}.')
    if datatype.target_type != target_type:
        raise UploadError(
            f'DataType {datatype.name!r} targets {datatype.target_type!r}, '
            f'not {target_type!r}.'
        )

    location = session.get(DataLocation, location_id)
    if location is None:
        raise UploadError(f'Unknown DataLocation id {location_id}.')
    if location.datatype_id != datatype_id:
        raise UploadError(
            f'DataLocation {location_id} does not belong to DataType '
            f'{datatype_id}.'
        )

    if not datatype.description_class:
        raise UploadError(
            f'DataType {datatype.name!r} has no description class — '
            f'cannot rename the upload.'
        )
    try:
        desc_cls = load_description_class(datatype.description_class)
    except Exception as exc:
        raise UploadError(
            f'Could not load description class '
            f'{datatype.description_class!r}: {exc}'
        ) from exc
    if not is_upload_capable(desc_cls):
        raise UploadError(
            f'Description class {datatype.description_class!r} does not '
            f'define ``upload_filename`` — it cannot accept uploads.'
        )

    try:
        raw = desc_cls.upload_filename(
            targets, file_storage.filename, date=date, notes=notes,
        )
    except TypeError as exc:
        # The most common cause is a subclass defining ``upload_filename``
        # as a plain function (with ``cls`` as the first parameter) instead
        # of a ``@classmethod``. In that case Python doesn't auto-pass the
        # class, so the first positional arg gets eaten by ``cls`` and the
        # error is opaque ("missing 1 required positional argument:
        # 'original_filename'"). Surface a clearer pointer to the contract.
        raise UploadError(
            f'{datatype.description_class}.upload_filename raised TypeError: '
            f'{exc}. Check the method signature — it must be declared as '
            f'``@classmethod`` with signature '
            f'``upload_filename(cls, targets, original_filename, *, date, notes)``. '
            f'See docs/uploads.md.'
        ) from exc
    if not isinstance(raw, str) or not raw.strip():
        raise UploadError(
            f'{datatype.description_class}.upload_filename returned '
            f'an empty / non-string name.'
        )
    relative_path = _sanitize_relative_path(raw)
    if not relative_path:
        raise UploadError(
            f'After sanitization, {datatype.description_class}.upload_filename '
            f'returned an empty name for {raw!r}.'
        )

    base_real = os.path.realpath(location.base_path)
    if not os.path.isdir(base_real):
        raise UploadError(
            f'DataLocation base_path {location.base_path!r} does not '
            f'exist on disk.'
        )

    relative_path = _resolve_relative_path(base_real, relative_path)
    candidate = safe_join(base_real, relative_path)
    if candidate is None:
        raise UploadError(f'Unsafe filename: {relative_path!r}.')
    full = os.path.realpath(candidate)
    # safe_join already rejects ``..`` segments; the commonpath check
    # mirrors ``routes/data_files.py:_resolve_disk_path`` so a symlink
    # in the base_path can't redirect us outside the tree.
    if os.path.commonpath([base_real, full]) != base_real:
        raise UploadError(f'Unsafe filename: {relative_path!r}.')

    # Description classes that return ``A001/photo.jpg`` expect the
    # subdirectory to be auto-created. ``exist_ok=True`` is the right
    # default — uploads to the same animal+date land in the same dir.
    os.makedirs(os.path.dirname(full), exist_ok=True)
    file_storage.save(full)

    try:
        file_hash = desc_cls.compute_hash(full)
    except ValueError:
        # ``hash_files()`` returned [] — the description class
        # deliberately opts out of content hashing (same convention as
        # ``sync.py``).
        file_hash = None
    except Exception as exc:
        log.warning(
            'compute_hash failed for %s: %s; leaving file_hash NULL.',
            full, exc,
        )
        file_hash = None

    data_cls = DATA_SUBCLASSES[target_type]
    stat = os.stat(full)
    # ``relative_path`` holds the full slash-separated path under
    # ``base_path`` (matches sync's storage shape); ``name`` is just the
    # filename basename, used by the entity_data_files template's
    # image-extension bucket sort.
    name = relative_path.rsplit('/', 1)[-1]
    row = data_cls(
        datatype_id=datatype_id,
        location_id=location_id,
        relative_path=relative_path,
        name=name,
        date=date,
        notes=(notes or None),
        file_hash=file_hash,
        status=DataStatus.REVIEWED,
        mtime=datetime.fromtimestamp(stat.st_mtime),
        ctime=datetime.fromtimestamp(stat.st_ctime),
        discovered_at=datetime.now(),
        parsed_metadata=_seeded_metadata(target_type, targets, date),
    )
    _, m2m_attr, _ = TARGET_LOADERS[target_type]
    setattr(row, m2m_attr, list(targets))
    session.add(row)
    return UploadResult(row=row, full_path=full)
