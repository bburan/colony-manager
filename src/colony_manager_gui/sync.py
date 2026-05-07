"""Importable sync core.

Walks ``DataLocation`` rows on disk, parses metadata via the configured
``DataTypeDescription`` subclass, and inserts/updates ``Data`` rows in
the database. The CLI wrapper at ``scripts/sync_data.py`` re-exports
:func:`sync_locations` and :func:`rehash_legacy`; the Flask app calls
:func:`sync_locations` (with ``filter_datatype_id`` set) right after a
DataType is created or updated.
"""
import logging
import os
from datetime import datetime

from sqlalchemy import func as sa_func
from sqlalchemy.orm import joinedload

from colony_manager.datatypes import load_description_class
from colony_manager.models import (
    DataLocation, Data, Animal, Ear,
    DATA_SUBCLASSES, _expand_sides,
)

from . import db


log = logging.getLogger(__name__)

XXH3_128_HEX_LEN = 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candidate_animals_for(parsed):
    """Return Animals matching parsed['animal_id'] (single value or list)."""
    raw = parsed.get('animal_id')
    if not raw:
        return []
    ids = raw if isinstance(raw, (list, tuple)) else [raw]
    animals = []
    for aid in ids:
        animal = Animal.query.filter_by(custom_id=aid).first()
        if animal:
            animals.append(animal)
    return animals


def _candidate_ears_for(parsed, candidate_animals):
    """Return Ears matching the parsed side for each candidate animal.

    Supports either a scalar ``side`` (one side for every animal_id) or
    a list parallel to ``animal_id`` so multi-animal photos like
    ``G014-4L G018-3R - dissection notes.jpg`` can resolve each
    animal's specific ear.
    """
    raw_ids = parsed.get('animal_id')
    if not raw_ids or not candidate_animals:
        return []
    ids = list(raw_ids) if isinstance(raw_ids, (list, tuple)) else [raw_ids]
    sides = _expand_sides(parsed.get('side') or parsed.get('ear'), len(ids))
    if sides is None:
        return []
    by_custom_id = {a.custom_id: a for a in candidate_animals}
    ears = []
    for aid, side in zip(ids, sides):
        if side not in ('Left', 'Right'):
            continue
        animal = by_custom_id.get(aid)
        if not animal:
            continue
        ear = Ear.query.filter_by(animal_id=animal.id, side=side).first()
        if ear:
            ears.append(ear)
    return ears


def _stat_timestamps(full_path):
    """Return ``(mtime, ctime)`` as datetimes, or ``(None, None)`` on failure."""
    try:
        st = os.stat(full_path)
    except OSError:
        return None, None
    return datetime.fromtimestamp(st.st_mtime), datetime.fromtimestamp(st.st_ctime)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def _sync_location(location, dry_run=False, debug=False):
    """Walk a single DataLocation. Returns counts dict."""
    counts = {'added': 0, 'moved': 0, 'skipped': 0, 'unmatched': 0, 'missing': 0}

    datatype = location.datatype
    base_path = location.base_path

    if not os.path.exists(base_path):
        log.warning('[%s] Base path does not exist: %s', datatype.name, base_path)
        return counts

    if not datatype.description_class:
        log.info('[%s] Skipping: no description_class configured.', datatype.name)
        return counts

    try:
        desc_cls = load_description_class(datatype.description_class)
    except Exception as e:
        log.error('[%s] Could not import description_class %r: %s',
                  datatype.name, datatype.description_class, e)
        return counts

    data_class = DATA_SUBCLASSES.get(datatype.target_type)
    if data_class is None:
        log.error('[%s] Unknown target_type %r.', datatype.name, datatype.target_type)
        return counts

    log.info('[%s] Scanning directory: %s', datatype.name, base_path)

    for root, dirs, files in os.walk(base_path):
        items_to_check = dirs if datatype.is_folder else files
        for item_name in items_to_check:
            full_path = os.path.join(root, item_name)
            relative_path = os.path.relpath(full_path, base_path).replace("\\", "/")

            existing = data_class.query.filter_by(
                location_id=location.id,
                relative_path=relative_path,
            ).first()
            if existing:
                counts['skipped'] += 1
                continue

            try:
                desc = desc_cls(full_path)
                parsed = desc.parse()
            except Exception as e:
                log.warning('  [WARN] %s: parser raised %r', relative_path, e)
                if debug:
                    raise
                continue
            if not parsed:
                continue

            file_hash = None
            try:
                hash_files = desc.hash_files()
                if hash_files:
                    file_hash = desc_cls.compute_hash(full_path)
            except Exception as e:
                log.warning('  [WARN] %s: hash computation failed: %r',
                            relative_path, e)

            if file_hash:
                hash_match = data_class.query.filter_by(
                    datatype_id=datatype.id,
                    file_hash=file_hash,
                ).first()
                if hash_match:
                    match_full = os.path.join(
                        hash_match.location.base_path,
                        hash_match.relative_path,
                    )
                    if not os.path.exists(match_full):
                        log.info('  [MOVE] %s -> %s (hash %s)',
                                 hash_match.relative_path, relative_path,
                                 file_hash[:12])
                        if not dry_run:
                            hash_match.location_id = location.id
                            hash_match.relative_path = relative_path
                            hash_match.name = item_name
                            if hash_match.status == 'missing':
                                hash_match.status = 'unreviewed'
                        counts['moved'] += 1
                        continue
                    else:
                        log.info('  [DUP]  %s has same hash as %s',
                                 relative_path, hash_match.relative_path)

            targets = datatype.match_targets(parsed)
            candidate_animals = _candidate_animals_for(parsed)
            candidate_ears = _candidate_ears_for(parsed, candidate_animals)
            if not targets:
                counts['unmatched'] += 1

            if dry_run:
                log.info(
                    '  [DRY RUN] Would add: %s | animals=%s | '
                    'ears=%s | targets=%d | hash=%s',
                    relative_path,
                    [a.display_id for a in candidate_animals],
                    [e.full_display for e in candidate_ears],
                    len(targets),
                    (file_hash or 'none')[:12],
                )
                counts['added'] += 1
                continue

            mtime, ctime = _stat_timestamps(full_path)
            new_data = data_class(
                datatype_id=datatype.id,
                location_id=location.id,
                relative_path=relative_path,
                name=item_name,
                date=parsed.get('date'),
                file_hash=file_hash,
                status='unreviewed',
                mtime=mtime,
                ctime=ctime,
                discovered_at=datetime.now(),
            )
            if datatype.target_type == 'animal_event':
                new_data.events = list(targets)
            elif datatype.target_type == 'confocal_image':
                new_data.confocal_images = list(targets)
            elif datatype.target_type == 'animal':
                new_data.animals = list(targets)
            elif datatype.target_type == 'ear':
                new_data.ears = list(targets)
            new_data.candidate_animals = candidate_animals
            new_data.candidate_ears = candidate_ears
            db.session.add(new_data)
            counts['added'] += 1

    if not dry_run:
        all_data = data_class.query.filter_by(
            datatype_id=datatype.id,
            location_id=location.id,
        ).all()
        for data_file in all_data:
            full = os.path.join(base_path, data_file.relative_path)
            if not os.path.exists(full) and data_file.status != 'missing':
                data_file.status = 'missing'
                counts['missing'] += 1

        db.session.commit()

    log.info(
        '[%s] %s — added=%d moved=%d unmatched=%d skipped=%d missing=%d',
        datatype.name, 'dry-run' if dry_run else 'done',
        counts['added'], counts['moved'], counts['unmatched'],
        counts['skipped'], counts['missing'],
    )
    return counts


def sync_locations(dry_run=False, filter_datatype_id=None, debug=False):
    """Walk every DataLocation (or just one DataType's) and sync.

    Parameters
    ----------
    dry_run : bool, default False
        If True, log what would change without writing to the DB.
    filter_datatype_id : int or None
        Restrict to locations belonging to this DataType. ``None`` walks
        every DataLocation in the system.

    Returns
    -------
    dict
        Aggregated counts: ``added``, ``moved``, ``unmatched``,
        ``skipped``, ``missing``.
    """
    query = DataLocation.query.options(joinedload(DataLocation.datatype))
    if filter_datatype_id is not None:
        query = query.filter(DataLocation.datatype_id == filter_datatype_id)
    locations = query.all()

    totals = {'added': 0, 'moved': 0, 'skipped': 0, 'unmatched': 0, 'missing': 0}
    if not locations:
        log.info('No DataLocations found%s.',
                 f' for datatype {filter_datatype_id}' if filter_datatype_id else '')
        return totals

    for location in locations:
        counts = _sync_location(location, dry_run=dry_run, debug=debug)
        for k, v in counts.items():
            totals[k] += v
    return totals


# ---------------------------------------------------------------------------
# Rematch
# ---------------------------------------------------------------------------

_TARGET_M2M_ATTR = {
    'animal_event': 'events',
    'confocal_image': 'confocal_images',
    'animal': 'animals',
    'ear': 'ears',
}


def _is_unmatched(row, target_type):
    """Return True if ``row`` has no targets for its discriminator."""
    attr = _TARGET_M2M_ATTR.get(target_type)
    if attr is None:
        return True
    return not list(getattr(row, attr))


def rematch_datatype(datatype_id, force=False, dry_run=False):
    """Re-parse and re-match Data rows for a single DataType.

    Parameters
    ----------
    datatype_id : int
        The DataType to operate on.
    force : bool, default False
        When False, only walks rows that currently have no linked
        targets. When True, walks every row for the DataType — clears
        existing target links, candidate animals, and candidate ears,
        then re-resolves them via the description class. Use this after
        changing a parser regex or matching rules so already-matched
        rows pick up the new behavior.
    dry_run : bool, default False
        If True, do not commit changes.

    Returns
    -------
    dict
        Counts: ``walked``, ``matched``, ``unmatched``, ``skipped``,
        ``failed``.
    """
    from colony_manager.models import DataType, DATA_SUBCLASSES

    counts = {'walked': 0, 'matched': 0, 'unmatched': 0, 'skipped': 0, 'failed': 0}

    dt = DataType.query.get(datatype_id)
    if dt is None:
        log.error('No DataType with id=%s.', datatype_id)
        return counts
    if not dt.description_class:
        log.warning('[%s] No description_class configured.', dt.name)
        return counts

    try:
        desc_cls = load_description_class(dt.description_class)
    except Exception as e:
        log.error('[%s] Could not load description_class %r: %s',
                  dt.name, dt.description_class, e)
        return counts

    data_class = DATA_SUBCLASSES.get(dt.target_type)
    if data_class is None:
        log.error('[%s] Unknown target_type %r.', dt.name, dt.target_type)
        return counts

    rows = data_class.query.filter_by(datatype_id=dt.id).all()
    target_attr = _TARGET_M2M_ATTR.get(dt.target_type)

    for row in rows:
        if not force and not _is_unmatched(row, dt.target_type):
            counts['skipped'] += 1
            continue
        counts['walked'] += 1

        full_path = os.path.join(row.location.base_path, row.relative_path)
        if not os.path.exists(full_path):
            counts['skipped'] += 1
            continue

        try:
            parsed = desc_cls(full_path).parse()
        except Exception as e:
            log.warning('  [WARN] %s: parser raised %r', row.relative_path, e)
            counts['failed'] += 1
            continue
        if not parsed:
            counts['skipped'] += 1
            continue

        targets = dt.match_targets(parsed)
        candidate_animals = _candidate_animals_for(parsed)
        candidate_ears = _candidate_ears_for(parsed, candidate_animals)

        if dry_run:
            log.info(
                '  [DRY RUN] %s: targets=%d animals=%s ears=%s',
                row.relative_path, len(targets),
                [a.display_id for a in candidate_animals],
                [e.full_display for e in candidate_ears],
            )
        else:
            # Single-assign the desired collections so SQLAlchemy diffs
            # against the current state. A clear-then-set sequence in the
            # same transaction would make sqlalchemy_continuum log both a
            # delete and an insert for unchanged items, blowing up on the
            # (data_id, target_id, transaction_id) version PK.
            if target_attr is not None:
                if force or targets:
                    setattr(row, target_attr, list(targets))
            row.candidate_animals = candidate_animals
            row.candidate_ears = candidate_ears

        if targets:
            counts['matched'] += 1
        else:
            counts['unmatched'] += 1

    if not dry_run:
        db.session.commit()

    log.info(
        '[%s] Rematch %s: walked=%d matched=%d unmatched=%d skipped=%d failed=%d',
        dt.name, 'force' if force else 'unmatched-only',
        counts['walked'], counts['matched'], counts['unmatched'],
        counts['skipped'], counts['failed'],
    )
    return counts


# ---------------------------------------------------------------------------
# Re-hash
# ---------------------------------------------------------------------------

def rehash_legacy(dry_run=False):
    """Re-hash any Data row whose stored ``file_hash`` isn't xxh3_128."""
    rows = Data.query.filter(
        Data.file_hash.isnot(None),
        sa_func.length(Data.file_hash) != XXH3_128_HEX_LEN,
    ).all()
    if not rows:
        log.info('No legacy hashes found.')
        return {'rehashed': 0, 'skipped': 0, 'failed': 0}

    log.info('Found %d row(s) with legacy hashes to re-hash.', len(rows))
    counts = {'rehashed': 0, 'skipped': 0, 'failed': 0}

    desc_cache = {}
    for row in rows:
        full_path = os.path.join(row.location.base_path, row.relative_path)
        if not os.path.exists(full_path):
            counts['skipped'] += 1
            continue

        dotted = row.datatype.description_class
        if not dotted:
            counts['skipped'] += 1
            continue
        if dotted not in desc_cache:
            try:
                desc_cache[dotted] = load_description_class(dotted)
            except Exception as e:
                log.error('Could not load %s: %s', dotted, e)
                desc_cache[dotted] = None
        desc_cls = desc_cache[dotted]
        if desc_cls is None:
            counts['failed'] += 1
            continue

        try:
            new_hash = desc_cls.compute_hash(full_path)
        except Exception as e:
            log.warning('  %s: re-hash failed: %r', row.relative_path, e)
            counts['failed'] += 1
            continue

        log.info('  [REHASH] %s: %s -> %s',
                 row.relative_path,
                 (row.file_hash or '')[:12], new_hash[:12])
        if not dry_run:
            row.file_hash = new_hash
        counts['rehashed'] += 1

    if not dry_run and counts['rehashed']:
        db.session.commit()

    log.info(
        'Re-hash %s. %d updated, %d skipped, %d failed.',
        'dry-run' if dry_run else 'complete',
        counts['rehashed'], counts['skipped'], counts['failed'],
    )
    return counts
