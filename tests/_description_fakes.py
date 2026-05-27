"""Fake ``DataTypeDescription`` subclasses for sync orchestration tests.

The real ``load_description_class`` function reads a registry from the
module pointed at by ``COLONY_MANAGER_DESCRIPTION_REGISTRY``. Tests
set the env var to ``tests._description_fakes`` and then look up the
fakes below by their short keys.

The fakes are deliberately minimal: filename-based parsers, no hashing.
That keeps the tests focused on sync-orchestration behavior (walking
the directory, matching candidates, auto-creating events, persisting
Data rows) rather than file-content semantics.
"""
import re
from datetime import date

from colony_manager.datatypes import DataTypeDescription


class _FilenameAnimalEventDescription(DataTypeDescription):
    """Parses ``<animal_id>_<YYYY-MM-DD>[_<side>].<ext>``.

    Example matches:
      ``M-001_2025-06-15.txt``           → animal_id='M-001', date=2025-06-15
      ``M-001_2025-06-15_Left.txt``      → ... side='Left'
    """

    def parse(self):
        stem = self.path.stem
        m = re.match(
            r'^([\w-]+)_(\d{4}-\d{2}-\d{2})(?:_(Left|Right))?$', stem,
        )
        if not m:
            return None
        result = {
            'animal_id': m.group(1),
            'date': date.fromisoformat(m.group(2)),
        }
        if m.group(3):
            result['side'] = m.group(3)
        return result

    def hash_files(self):
        return []  # no hash → no file-move detection


class _FilenameAnimalDescription(DataTypeDescription):
    """Parses ``<animal_id>.<ext>`` for ``animal``-target DataTypes."""

    def parse(self):
        stem = self.path.stem
        if not re.match(r'^[\w-]+$', stem):
            return None
        return {'animal_id': stem}

    def hash_files(self):
        return []


class _HashingAnimalEventDescription(_FilenameAnimalEventDescription):
    """Same parser, but participates in the hash-based move-detection path.

    Returning the file itself from ``hash_files()`` causes
    ``_sync_location`` to compute and store a content hash, which is
    what the cross-rename matcher uses.
    """

    def hash_files(self):
        return [self.path]


class _HashingAnimalDescription(_FilenameAnimalDescription):
    """Same as _FilenameAnimalDescription, but with hashing for move detection.

    Used to test AnimalDataType (e.g. surgery photos) with the MOVE path.
    """

    def hash_files(self):
        return [self.path]


# The registry shape the production loader expects: a module-level
# ``DESCRIPTION_CLASSES`` dict mapping short keys to subclasses.
DESCRIPTION_CLASSES = {
    'fake_animal_event': _FilenameAnimalEventDescription,
    'fake_animal': _FilenameAnimalDescription,
    'fake_animal_event_hashed': _HashingAnimalEventDescription,
    'fake_animal_hashed': _HashingAnimalDescription,
}
