"""Nightly sync script for discovering and cataloguing data files.

Walks each ``DataLocation``'s filesystem, uses the configured
``DataTypeDescription`` subclass to parse metadata and compute content
hashes, and either creates new ``Data`` rows or updates existing ones
when a file has been moved/renamed.

Usage
-----
::

    python sync_data.py
    python sync_data.py --dry-run
"""
import argparse
import logging
import os
import sys
from datetime import datetime

from sqlalchemy.orm import joinedload

from colony_manager_gui import create_app, db
from colony_manager.datatypes import load_description_class
from colony_manager.models import (
    DataLocation, DataType, Data, Animal, DATA_SUBCLASSES,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
)
log = logging.getLogger(__name__)


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


def _stat_timestamps(full_path):
    """Return ``(mtime, ctime)`` as datetimes, or ``(None, None)`` on failure."""
    try:
        st = os.stat(full_path)
    except OSError:
        return None, None
    return datetime.fromtimestamp(st.st_mtime), datetime.fromtimestamp(st.st_ctime)


def _find_orphaned_by_hash(file_hash, datatype_id, data_class):
    """Find a DB row whose path no longer exists on disk but whose hash matches.

    Parameters
    ----------
    file_hash : str
        SHA-256 hex digest of the new file.
    datatype_id : int
        The DataType this file belongs to.
    data_class : type
        The polymorphic Data subclass to query.

    Returns
    -------
    Data or None
        The orphaned row if found, otherwise ``None``.
    """
    candidates = data_class.query.filter_by(
        datatype_id=datatype_id,
        file_hash=file_hash,
    ).all()
    for candidate in candidates:
        full = os.path.join(candidate.location.base_path, candidate.relative_path)
        if not os.path.exists(full):
            return candidate
    return None


def sync_locations(dry_run=False):
    """Walk every DataLocation and synchronize files with the database."""
    locations = DataLocation.query.options(
        joinedload(DataLocation.datatype)
    ).all()

    if not locations:
        log.info('No DataLocations found in the database.')
        return

    for location in locations:
        datatype = location.datatype
        base_path = location.base_path

        if not os.path.exists(base_path):
            log.warning('[%s] Base path does not exist: %s', datatype.name, base_path)
            continue

        if not datatype.description_class:
            log.info('[%s] Skipping: no description_class configured.', datatype.name)
            continue

        try:
            desc_cls = load_description_class(datatype.description_class)
        except Exception as e:
            log.error('[%s] Could not import description_class %r: %s',
                      datatype.name, datatype.description_class, e)
            continue

        data_class = DATA_SUBCLASSES.get(datatype.target_type)
        if data_class is None:
            log.error('[%s] Unknown target_type %r.', datatype.name, datatype.target_type)
            continue

        log.info('[%s] Scanning directory: %s', datatype.name, base_path)
        added_count = 0
        moved_count = 0
        skipped_count = 0
        unmatched_count = 0

        for root, dirs, files in os.walk(base_path):
            items_to_check = dirs if datatype.is_folder else files
            for item_name in items_to_check:
                full_path = os.path.join(root, item_name)
                relative_path = os.path.relpath(full_path, base_path).replace("\\", "/")

                # --- Already catalogued? ---
                existing = data_class.query.filter_by(
                    location_id=location.id,
                    relative_path=relative_path,
                ).first()
                if existing:
                    skipped_count += 1
                    continue

                # --- Parse metadata ---
                try:
                    desc = desc_cls(full_path)
                    parsed = desc.parse()
                except Exception as e:
                    log.warning('  [WARN] %s: parser raised %r', relative_path, e)
                    continue
                if not parsed:
                    continue

                # --- Compute content hash (if description supports it) ---
                file_hash = None
                try:
                    hash_files = desc.hash_files()
                    if hash_files:
                        file_hash = desc_cls.compute_hash(full_path)
                except Exception as e:
                    log.warning('  [WARN] %s: hash computation failed: %r',
                                relative_path, e)

                # --- Check for moved/renamed file by hash ---
                if file_hash:
                    # First check if hash already exists in DB
                    hash_match = data_class.query.filter_by(
                        datatype_id=datatype.id,
                        file_hash=file_hash,
                    ).first()
                    if hash_match:
                        # Hash exists — check if the matched row is orphaned
                        match_full = os.path.join(
                            hash_match.location.base_path,
                            hash_match.relative_path,
                        )
                        if not os.path.exists(match_full):
                            # Orphaned row: update path instead of creating
                            log.info('  [MOVE] %s -> %s (hash %s)',
                                     hash_match.relative_path, relative_path,
                                     file_hash[:12])
                            if not dry_run:
                                hash_match.location_id = location.id
                                hash_match.relative_path = relative_path
                                hash_match.name = item_name
                                hash_match.status = hash_match.status if hash_match.status != 'missing' else 'unreviewed'
                            moved_count += 1
                            continue
                        else:
                            # Hash exists and the file is still on disk —
                            # this is a genuine duplicate; log and create new.
                            log.info('  [DUP]  %s has same hash as %s',
                                     relative_path, hash_match.relative_path)

                # --- Match targets ---
                targets = datatype.match_targets(parsed)
                candidate_animals = _candidate_animals_for(parsed)
                if not targets:
                    unmatched_count += 1

                if dry_run:
                    log.info(
                        '  [DRY RUN] Would add: %s | animals=%s | '
                        'targets=%d | hash=%s',
                        relative_path,
                        [a.display_id for a in candidate_animals],
                        len(targets),
                        (file_hash or 'none')[:12],
                    )
                    added_count += 1
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
                # Subclass-specific target M2M assignment
                if datatype.target_type == 'animal_event':
                    new_data.events = list(targets)
                elif datatype.target_type == 'confocal_image':
                    new_data.confocal_images = list(targets)
                elif datatype.target_type == 'animal':
                    new_data.animals = list(targets)
                elif datatype.target_type == 'ear':
                    new_data.ears = list(targets)
                new_data.candidate_animals = candidate_animals
                db.session.add(new_data)
                added_count += 1

        # --- Flag missing files ---
        if not dry_run:
            all_data = data_class.query.filter_by(
                datatype_id=datatype.id,
                location_id=location.id,
            ).all()
            missing_count = 0
            for data_file in all_data:
                full = os.path.join(base_path, data_file.relative_path)
                if not os.path.exists(full) and data_file.status != 'missing':
                    data_file.status = 'missing'
                    missing_count += 1
            if missing_count:
                log.info('[%s] Flagged %d file(s) as missing.', datatype.name, missing_count)

        if not dry_run and (added_count > 0 or moved_count > 0):
            db.session.commit()
            log.info(
                '[%s] Saved %d new, %d moved (%d unmatched). '
                'Skipped %d existing.',
                datatype.name, added_count, moved_count,
                unmatched_count, skipped_count,
            )
        elif dry_run:
            log.info(
                '[%s] Dry run finished. Would have added %d, '
                'moved %d (%d unmatched).',
                datatype.name, added_count, moved_count, unmatched_count,
            )
        else:
            if not dry_run:
                db.session.commit()
            log.info(
                '[%s] Synchronization finished. No new files. '
                'Skipped %d existing.',
                datatype.name, skipped_count,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sync data files from DataLocations to the Database.",
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help="Scan files without saving to the database.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        sync_locations(dry_run=args.dry_run)
