# File uploads

The sync core (`docs/jobs.md`) walks `DataLocation` directories and
ingests anything the parser can identify. This page covers the
**inverse on-ramp**: a researcher clicks "Upload" on an Animal or Ear
detail page, drops files into the modal, and each file is renamed by
the target's `DataTypeDescription` and persisted as a `Data` row
already linked to the chosen entities. The rest of the data-file UI
(thumbnails, callback buttons, status, notes, rematch) keeps working
unchanged because the rows are indistinguishable from sync-discovered
ones.

## Architecture

```
[view_animal.html / view_ear.html]
        │  "Upload" button — hx-get → #modalBody (shared editModal)
        ▼
GET  /data/upload/<target_type>/<id>/modal
        │  Modal opens with URL target as the first chip.
        │  ─ user types in the Targets input:
        ▼
GET  /data/upload/<target_type>/search?q=…   (HTMX typeahead)
        │  Returns up to 15 matches as clickable list-group buttons.
        │  ─ user picks DataType; if datatype changes:
        ▼
GET  /data/upload/<target_type>/<id>/locations?datatype=<id>
        │  swaps the Location <select>
        ▼  user picks Date + Files; per-file notes row appears for
        ▼  each picked file; user fills any notes, submits
POST /data/upload/<target_type>/<id>          (multipart/form-data)
        │
        ▼  one call per file:
services.uploads.handle_upload(...)
        │ 1. desc_cls.upload_filename(targets, original_name, date=, notes=)
        │ 2. resolve collisions: <stem>_1<ext>, <stem>_2<ext>, …
        │ 3. write file under DataLocation.base_path
        │ 4. compute file_hash via desc_cls.compute_hash
        │ 5. build DATA_SUBCLASSES[target_type] row + link every target
        │ 6. status='reviewed', mtime/discovered_at set,
        │    parsed_metadata seeded from the target list
        ▼
session.commit  →  redirect to entity detail page
```

## Adding upload support to a `DataTypeDescription`

A description class **opts in** by defining a `upload_filename`
classmethod. The base class deliberately does not define one — its
absence is the opt-out signal that
`colony_manager.datatypes.is_upload_capable` checks for. Description
classes without the method never appear in the modal's Type dropdown.

```python
from pathlib import Path
from colony_manager.datatypes import DataTypeDescription

class AnimalPhoto(DataTypeDescription):

    def parse(self):
        ...

    def hash_files(self):
        return [self.path]

    @classmethod
    def upload_filename(cls, targets, original_filename, *, date, notes):
        """Rename a user upload so the parser can re-identify it later.

        ``targets`` is always a non-empty list of target instances of
        the same type. Single-target classes can use ``targets[0]``;
        multi-target classes can join, e.g.::

            ids = ' '.join(t.custom_id for t in targets)

        which mirrors the sync parser's multi-animal filename
        convention (``G014-4L G018-3R - dissection notes.jpg``).
        """
        ext = Path(original_filename).suffix.lower() or '.jpg'
        ids = ' '.join(t.custom_id for t in targets)
        return f'{ids}_{date:%Y-%m-%d}{ext}'
```

The classmethod must:

* return either a **basename** (`A001_2026-06-03.jpg`) **or a
  forward-slash-separated relative path** with subdirectories
  (`A001/2026-06-03.jpg`). Subdirectories are auto-created under the
  chosen `DataLocation`. `..` segments and absolute paths are stripped
  by the sanitizer.
* be deterministic enough that re-running it on a duplicate is fine —
  the service handles `<stem>_1<ext>` suffixing on collision (the
  suffix attaches to the filename stem, not to a directory component).
* preserve the user's extension (or pick a sensible default for
  extension-less names) so the saved file opens with the right tools
  **and** so the UI's image bucket-sort renders thumbnails for image
  files.

Example with a per-animal subdirectory:

```python
@classmethod
def upload_filename(cls, targets, original_filename, *, date, notes):
    ext = Path(original_filename).suffix.lower() or '.jpg'
    target_str = ' '.join(t.custom_id for t in targets)
    date_str = date.strftime('%Y%m%d')
    notes_str = f' - {notes}' if notes else ''
    # Returns e.g. ``A001/20260603 - A001 - portrait.jpg``
    return f'{target_str}/{date_str} - {target_str}{notes_str}{ext}'
```

Sub-subclasses inherit upload capability automatically — `__mro__` is
walked, and any class except `DataTypeDescription`/`object` that
defines `upload_filename` counts.

## Extending to a new `target_type`

The upload pipeline is generic over `target_type`. Adding support for
`AnimalEvent`, `ConfocalImage`, or any future polymorphic `Data`
subclass takes three small edits:

1. **Register the loader + m2m attr** in
   `src/colony_manager_gui/services/uploads.py`:

   ```python
   TARGET_LOADERS = {
       'animal':           (lambda s, i: s.get(Animal, i),       'animals',         _animal_label),
       'ear':              (lambda s, i: s.get(Ear, i),          'ears',            _ear_label),
       'animal_event':     (lambda s, i: s.get(AnimalEvent, i),  'events',          _event_label),
       # ...
   }
   ```

   The middle element is the name of the m2m collection on the
   polymorphic `Data` subclass (`AnimalEventData.events`,
   `ConfocalImageData.confocal_images`, …) — they already exist on the
   model. The third element is a `(instance) -> str` label used by the
   chip and typeahead UI.

2. **Add a detail-page endpoint** in
   `src/colony_manager_gui/routes/data_files.py`:

   ```python
   _TARGET_DETAIL_ENDPOINT = {
       'animal': ('animals.view_animal', 'animal_id'),
       'ear':    ('histology.view_ear',  'ear_id'),
       'animal_event': ('animals.view_animal_event', 'event_id'),
   }
   ```

   The post-upload redirect uses this.

3. **Optional**: extend `search_targets` in `services/uploads.py` with
   a branch for the new type if the existing `Animal.custom_id`
   typeahead is not enough — e.g. `AnimalEvent` may want to search by
   procedure + date.

4. Add an **"Upload" button** on the entity's detail template using
   `target_type=<new>`:

   ```jinja
   <button type="button"
           hx-get="{{ url_for('data_files.upload_modal',
                              target_type='animal_event',
                              target_id=event.id) }}"
           hx-target="#modalBody">
       <i class="fas fa-upload me-1"></i> Upload
   </button>
   ```

No routes, form, or `handle_upload` change is needed.

## Drag-and-drop and additive staging

The file input is wrapped in a drop zone with hover feedback
(`base.html`'s `colonyUploadModal` Alpine helper). Both the browse
button and drag-drop **append** to a JS-owned staging array — picking
files repeatedly accumulates them rather than replacing the prior
selection. Each staged row carries its own filename label, X button,
and per-file notes input.

The underlying `<input type="file">` is **not** the source of truth.
Browse calls clear the input immediately (so the user can re-pick the
same file later if they removed it from the staging list). The
form's `@submit` handler rebuilds a fresh `FileList` from the staged
array via `DataTransfer` → `input.files` right before multipart
serialization. From the route's perspective, the upload looks
identical to a single-shot browse — `request.files.getlist('files')`
returns the staged files in staging order, and `file_notes` rows
pair positionally.

If JS is disabled or the `@submit` handler doesn't run, the form
falls back to whatever the input natively holds — a graceful
degradation to single-shot browse behavior.

## Per-file notes

The modal renders one notes input per file the user picks (Alpine
re-syncs the rows whenever the file input fires `change`). Each
notes value is sent as a `file_notes` form part in document order;
the route zips them positionally with `request.files.getlist('files')`
and passes the matching string to `handle_upload` as the row's
`notes` field. Empty / missing entries are stored as `NULL`.

`upload_filename` receives this per-file notes value via its
keyword-only `notes=` parameter, so a description class can fold the
notes into the filename if it wants to disambiguate batch uploads
(e.g. `f'… - {notes}{ext}'`).

## Filename collisions

If the description class's `upload_filename` returns a name that
already exists in the target `DataLocation`, the service appends
`_1`, `_2`, … to the stem (extension preserved) until the path is
free. Both files coexist; neither is overwritten. The DB unique
constraint on `(location_id, relative_path)` means a concurrent
second writer with the same name would also be rejected at commit,
but request-thread serialization makes that vanishingly rare.

## Status and metadata

Uploaded rows land as:

* `status = 'reviewed'` — the user just acted deliberately, so they
  skip the unreviewed queue. (Sync-discovered rows default to
  `'unreviewed'`.)
* `discovered_at = now()`.
* `mtime = os.stat(file).st_mtime`, `ctime = os.stat(file).st_ctime`.
* `parsed_metadata` seeded from the target list rather than re-parsed
  from the filename — the target is authoritative at upload time.
  Shape mirrors what the sync parser would have produced
  (`{'animal_id': [...], 'side': [...], 'date': ISO}`) so the existing
  rematch path keeps working unchanged.
* `file_hash` computed via the description class's
  `compute_hash(path)`. Description classes whose `hash_files()`
  returns `[]` get `file_hash = None` (same convention as sync).

## Limits and errors

* **Max upload size** is set via `MAX_CONTENT_LENGTH`, overridable
  with the `COLONY_MANAGER_MAX_UPLOAD_MB` env var (default 100 MiB).
  A request exceeding this returns Flask's 413 before reaching the
  route.
* **No upload-capable DataType** — the modal renders an empty-state
  alert and disables the submit button. Admins must register a
  DataType whose description class defines `upload_filename` and
  configure at least one `DataLocation`.
* **No DataLocation for the chosen DataType** — the Location select
  renders a single disabled "(no location configured)" option, the
  form fails to validate, and the user is redirected back with a
  flash. The DataType list already filters out locationless types, so
  this only triggers if the admin deletes a location between the
  modal load and the submit.
* **Forged target ids** — `resolve_targets` refuses unknown ids and
  ids of the wrong polymorphic type (e.g. an `ear` id POSTed to the
  `/animal/...` route). The user gets a flash; nothing is written.

## Source map

| Concern | File |
|---|---|
| Description-class opt-in helper | `src/colony_manager/datatypes.py` (`is_upload_capable`) |
| Per-file pipeline + helpers | `src/colony_manager_gui/services/uploads.py` |
| Form | `src/colony_manager_gui/forms.py` (`UploadFilesForm`) |
| Routes | `src/colony_manager_gui/routes/data_files.py` |
| Modal | `src/colony_manager_gui/templates/partials/upload_modal.html` |
| Location cascade | `src/colony_manager_gui/templates/partials/upload_locations_select.html` |
| Typeahead | `src/colony_manager_gui/templates/partials/upload_target_results.html` |
| Buttons | `view_animal.html` (Files accordion), `view_ear.html` (Files card) |
| Tests | `tests/test_uploads.py`, `tests/_description_fakes.py` |
