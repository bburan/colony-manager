import argparse
import importlib
import os
import sys
from sqlalchemy.orm import joinedload

from colony_manager_gui import create_app
from colony_manager_gui import db
from colony_manager.models import (
    DataLocation, DataType, Animal, DATA_SUBCLASSES,
)


_PARSE_CACHE = {}


def _resolve_callable(dotted_path):
    if dotted_path in _PARSE_CACHE:
        return _PARSE_CACHE[dotted_path]
    module_name, func_name = dotted_path.rsplit('.', 1)
    module = importlib.import_module(module_name)
    fn = getattr(module, func_name)
    _PARSE_CACHE[dotted_path] = fn
    return fn


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


def sync_locations(dry_run=False):
    locations = DataLocation.query.options(joinedload(DataLocation.datatype)).all()

    if not locations:
        print("No DataLocations found in the database.")
        return

    for location in locations:
        datatype = location.datatype
        base_path = location.base_path

        if not os.path.exists(base_path):
            print(f"[{datatype.name}] Warning: Base path {base_path} does not exist.")
            continue

        if not datatype.parse_function:
            print(f"[{datatype.name}] Skipping: no parse_function configured.")
            continue

        try:
            parser = _resolve_callable(datatype.parse_function)
        except Exception as e:
            print(f"[{datatype.name}] Could not import parse_function {datatype.parse_function!r}: {e}")
            continue

        data_class = DATA_SUBCLASSES.get(datatype.target_type)
        if data_class is None:
            print(f"[{datatype.name}] Unknown target_type {datatype.target_type!r}.")
            continue

        print(f"[{datatype.name}] Scanning directory: {base_path}")
        added_count = 0
        skipped_count = 0
        unmatched_count = 0

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
                    skipped_count += 1
                    continue

                try:
                    parsed = parser(relative_path, location)
                except Exception as e:
                    print(f"  [WARN] {relative_path}: parser raised {e!r}")
                    continue
                if not parsed:
                    continue

                targets = datatype.match_targets(parsed)
                candidate_animals = _candidate_animals_for(parsed)
                if not targets:
                    unmatched_count += 1

                if dry_run:
                    print(
                        f"  [DRY RUN] Would Add: {relative_path} | "
                        f"animals={[a.display_id for a in candidate_animals]} | "
                        f"targets={len(targets)}"
                    )
                    added_count += 1
                    continue

                new_data = data_class(
                    datatype_id=datatype.id,
                    location_id=location.id,
                    relative_path=relative_path,
                    name=item_name,
                    date=parsed.get('date'),
                    status='unreviewed',
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

        if not dry_run and added_count > 0:
            db.session.commit()
            print(
                f"[{datatype.name}] Saved {added_count} new files "
                f"({unmatched_count} unmatched). Skipped {skipped_count} existing."
            )
        elif dry_run:
            print(
                f"[{datatype.name}] Dry run finished. Would have added "
                f"{added_count} files ({unmatched_count} unmatched)."
            )
        else:
            print(
                f"[{datatype.name}] Synchronization finished. No new files. "
                f"Skipped {skipped_count} existing."
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync data files from DataLocations to the Database.")
    parser.add_argument('--dry-run', action='store_true', help="Scan files without saving to the database.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        sync_locations(dry_run=args.dry_run)
