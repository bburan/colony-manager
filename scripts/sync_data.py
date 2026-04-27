import argparse
import os
import re
from datetime import datetime
from sqlalchemy.orm import joinedload
import sys

# Add src directories to sys.path so we can import the app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from colony_manager_gui import create_app
from colony_manager_gui import db
from colony_manager.models import DataType, DataLocation, Data, Animal, AnimalEvent

def parse_date(date_str):
    for fmt in ('%Y-%m-%d', '%Y%m%d', '%m-%d-%Y', '%Y_%m_%d'):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    return None

def find_animals_from_string(animal_id_str):
    """
    Attempt to find animals based on the extracted string.
    Supports basic splitting by comma if multiple are present.
    """
    if not animal_id_str:
        return []

    tokens = [t.strip() for t in re.split(r'[,+&|]', animal_id_str) if t.strip()]
    animals = []
    for token in tokens:
        animal = Animal.query.filter_by(custom_id=token).first()
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
            
        print(f"[{datatype.name}] Scanning directory: {base_path}")
        try:
            regex = re.compile(datatype.filename_regex)
        except re.error as e:
            print(f"  [ERROR] Invalid regex for DataType {datatype.name}: {e}")
            continue

        added_count = 0
        skipped_count = 0

        # Recursively walk the directory
        for root, dirs, files in os.walk(base_path):
            items_to_check = dirs if datatype.is_folder else files
            for item_name in items_to_check:
                full_path = os.path.join(root, item_name)
                relative_path = os.path.relpath(full_path, base_path)
                
                # Normalize slashes for consistency
                relative_path = relative_path.replace("\\", "/")

                # Check if it's already in the database
                existing_data = Data.query.filter_by(location_id=location.id, relative_path=relative_path).first()
                if existing_data:
                    skipped_count += 1
                    continue

                extracted_date = None
                matched_animals = []
                
                # Apply Regex parsing
                match = regex.search(relative_path)
                if not match:
                    continue

                groupdict = match.groupdict()
                print(groupdict)
                if 'date' in groupdict and groupdict['date']:
                    extracted_date = parse_date(groupdict['date'])
                if 'animal_id' in groupdict and groupdict['animal_id']:
                    matched_animals = find_animals_from_string(groupdict['animal_id'])
                    
                # Auto-map to Event if DataType has default_procedure_id
                matched_event_id = None
                if datatype.default_procedure_id and extracted_date and len(matched_animals) > 0:
                    for a in matched_animals:
                        event = AnimalEvent.query.filter_by(
                            animal_id=a.id, 
                            procedure_id=datatype.default_procedure_id
                        ).filter(
                            db.or_(
                                AnimalEvent.scheduled_date == extracted_date,
                                AnimalEvent.completion_date == extracted_date
                            )
                        ).first()
                        if event:
                            matched_event_id = event.id
                            break
                            
                if dry_run:
                    print(f"  [DRY RUN] Would Add: {relative_path} | Animals matched: {[a.display_id for a in matched_animals]} | Event: {matched_event_id}")
                    added_count += 1
                else:
                    new_data = Data(
                        datatype_id=datatype.id,
                        location_id=location.id,
                        event_id=matched_event_id,
                        relative_path=relative_path,
                        name=item_name,
                        date=extracted_date,
                        status='unreviewed'
                    )
                    
                    # Associate mapped animals
                    for animal in matched_animals:
                        new_data.animals.append(animal)
                        
                    db.session.add(new_data)
                    added_count += 1
                    
        if not dry_run and added_count > 0:
            db.session.commit()
            print(f"[{datatype.name}] Saved {added_count} new files into the database. Skipped {skipped_count} existing.")
        elif dry_run:
            print(f"[{datatype.name}] Dry run finished. Would have added {added_count} files.")
        else:
            print(f"[{datatype.name}] Synchronization finished. No new files found. Skipped {skipped_count} existing.")
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync data files from DataLocations to the Database.")
    parser.add_argument('--dry-run', action='store_true', help="Scan files without saving to the database.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        sync_locations(dry_run=args.dry_run)
