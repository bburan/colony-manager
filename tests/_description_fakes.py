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
from pathlib import Path

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


class _UploadableAnimalDescription(_FilenameAnimalDescription):
    """Animal-target description that opts in to the upload flow.

    Renames uploads to ``<animal_ids>_<YYYY-MM-DD><ext>`` so the
    round-trip (upload → sync → re-parse) lands on the same animal(s).
    Inherits ``hash_files() -> []`` from the parent so uploaded rows
    skip content hashing.
    """

    @classmethod
    def upload_filename(cls, targets, original_filename, *, date, notes):
        ext = Path(original_filename).suffix.lower() or '.bin'
        ids = ' '.join(t.custom_id for t in targets)
        return f'{ids}_{date:%Y-%m-%d}{ext}'


class _UploadableAnimalDescriptionSubclass(_UploadableAnimalDescription):
    """Inherits upload capability without redefining ``upload_filename``.

    Used by ``test_is_upload_capable_walks_mro`` to confirm an indirect
    subclass still registers as upload-capable.
    """


class _HashingUploadableAnimalDescription(_HashingAnimalDescription):
    """Upload-capable animal description that also hashes content.

    Mirrors ``_UploadableAnimalDescription`` but participates in the
    hash path — used to test that ``handle_upload`` populates
    ``file_hash`` for description classes whose ``hash_files()`` is
    non-empty.
    """

    @classmethod
    def upload_filename(cls, targets, original_filename, *, date, notes):
        ext = Path(original_filename).suffix.lower() or '.bin'
        ids = ' '.join(t.custom_id for t in targets)
        return f'{ids}_{date:%Y-%m-%d}{ext}'


class _MultiAnimalDescription(DataTypeDescription):
    """Parses a space-separated list of animal IDs from the filename.

    e.g. ``M-001 M-002 M-999.txt`` → animal_id=['M-001','M-002','M-999'].
    Used to exercise the partial-match flag (``has_unmatched_animals``)
    when a filename names animals that don't all exist in the colony.
    """

    def parse(self):
        ids = [p for p in self.path.stem.split(' ') if p]
        if not ids:
            return None
        return {'animal_id': ids}

    def hash_files(self):
        return []


class _UploadableEarDescription(DataTypeDescription):
    """Ear-target description that opts in to the upload flow."""

    def parse(self):
        return None  # filename → metadata mapping not relevant to upload tests

    def hash_files(self):
        return []

    @classmethod
    def upload_filename(cls, targets, original_filename, *, date, notes):
        ext = Path(original_filename).suffix.lower() or '.bin'
        parts = [f'{t.animal.custom_id}-{t.side[0]}' for t in targets]
        return f'{" ".join(parts)}_{date:%Y-%m-%d}{ext}'


# The registry shape the production loader expects: a module-level
# ``DESCRIPTION_CLASSES`` dict mapping short keys to subclasses.
DESCRIPTION_CLASSES = {
    'fake_animal_event': _FilenameAnimalEventDescription,
    'fake_animal': _FilenameAnimalDescription,
    'fake_animal_event_hashed': _HashingAnimalEventDescription,
    'fake_animal_hashed': _HashingAnimalDescription,
    'fake_animal_upload': _UploadableAnimalDescription,
    'fake_animal_upload_subclass': _UploadableAnimalDescriptionSubclass,
    'fake_animal_upload_hashed': _HashingUploadableAnimalDescription,
    'fake_ear_upload': _UploadableEarDescription,
    'fake_multi_animal': _MultiAnimalDescription,
}
