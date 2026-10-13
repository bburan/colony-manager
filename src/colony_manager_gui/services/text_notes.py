"""Text notes — Markdown files written in the app rather than uploaded.

A text note is an ordinary data file: it is written into a ``DataLocation``
by :func:`services.uploads.handle_upload`, named by the DataType's
description class, and listed on the target's Files like any upload. The
only differences are where the bytes come from (the editor's textarea
instead of a file picker) and that it can be read and edited in place.

Which DataTypes can hold one is the description class's call — it opts in
with ``text_note_suffix`` (see ``colony_manager.datatypes.
is_text_note_capable``), which is also the extension the file is written
with, so its own ``parse()`` can re-identify the file on a later sync.

The text itself is Markdown, rendered by the help system's renderer
(:func:`colony_manager_gui.helpdocs.render_markdown`). Rich text pasted
from Word or Outlook is converted to Markdown in the browser
(``static/js/markdown-paste.js``) before it ever reaches the server.
"""
import io
import os
from datetime import datetime

from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage
from werkzeug.utils import safe_join

from colony_manager.datatypes import is_text_note_capable, load_description_class
from colony_manager.models import Data, DataType

from .uploads import UploadError, UploadResult, handle_upload


# Extensions shown through the in-app viewer. Wider than what the editor
# writes (whatever ``text_note_suffix`` says), so a .txt / .md dropped
# into a location by hand still reads as text rather than a download.
VIEWABLE_SUFFIXES = ('.md', '.markdown', '.txt')

# A note is prose. Anything bigger is not something to render into a
# modal (or to accept from a textarea).
MAX_NOTE_BYTES = 1024 * 1024

AUTO_LABEL_PREFIX = 'note'


def is_viewable(data_file: Data) -> bool:
    """Whether ``data_file`` opens in the text viewer."""
    return data_file.name.lower().endswith(VIEWABLE_SUFFIXES)


def is_editable(data_file: Data) -> bool:
    """Whether ``data_file`` is a text note the editor may overwrite.

    Only a file of a text-note-capable DataType, carrying that class's
    suffix — i.e. one the editor could have written. A ``.txt`` an
    instrument produced alongside its data is viewable, never editable.
    """
    cls = _description_class(data_file)
    if cls is None or not is_text_note_capable(cls):
        return False
    return data_file.name.lower().endswith(cls.text_note_suffix.lower())


def _description_class(data_file):
    if not data_file.datatype.description_class:
        return None
    try:
        return load_description_class(data_file.datatype.description_class)
    except Exception:
        return None


def _encode(text: str) -> bytes:
    """Normalize line endings (a textarea posts CRLF) and encode as UTF-8."""
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    if text and not text.endswith('\n'):
        text += '\n'
    data = text.encode('utf-8')
    if len(data) > MAX_NOTE_BYTES:
        raise UploadError(
            f'Note is too long ({len(data) // 1024} KiB; the limit is '
            f'{MAX_NOTE_BYTES // 1024} KiB).'
        )
    return data


def create_text_note(
    session: Session,
    *,
    target_type: str,
    targets: list,
    datatype_id: int,
    location_id: int,
    date,
    label: str | None,
    text: str,
) -> UploadResult:
    """Write ``text`` as a new note file and stage its ``Data`` row.

    Goes through :func:`handle_upload`, so naming, collision handling,
    location checks and target linking are exactly those of a file
    upload. A blank ``label`` auto-numbers as ``note 1``, ``note 2``, ...
    Does not commit.
    """
    if not (text or '').strip():
        raise UploadError('The note is empty.')
    datatype = session.get(DataType, datatype_id)
    if datatype is None:
        raise UploadError(f'Unknown DataType id {datatype_id}.')
    try:
        cls = load_description_class(datatype.description_class)
    except Exception as exc:
        raise UploadError(
            f'Could not load description class '
            f'{datatype.description_class!r}: {exc}'
        ) from exc
    if not is_text_note_capable(cls):
        raise UploadError(
            f'DataType {datatype.name!r} cannot hold text notes.'
        )
    storage = FileStorage(
        stream=io.BytesIO(_encode(text)),
        filename=f'{AUTO_LABEL_PREFIX}{cls.text_note_suffix}',
        content_type='text/markdown',
    )
    return handle_upload(
        session,
        target_type=target_type,
        targets=targets,
        datatype_id=datatype_id,
        location_id=location_id,
        date=date,
        label=label,
        notes=None,
        file_storage=storage,
        auto_label_prefix=AUTO_LABEL_PREFIX,
    )


def note_path(data_file: Data) -> str:
    """Absolute path of ``data_file``, refusing anything outside its location.

    Same containment rule as ``routes/data_files.py:_resolve_disk_path``,
    raising instead of aborting so the service stays Flask-free.
    """
    base = os.path.realpath(data_file.location.base_path)
    candidate = safe_join(base, data_file.relative_path)
    if candidate is None:
        raise UploadError('Unsafe file path.')
    full = os.path.realpath(candidate)
    if os.path.commonpath([base, full]) != base:
        raise UploadError('Unsafe file path.')
    return full


def read_text_note(data_file: Data) -> str:
    """Return the file's text. Raises :class:`UploadError` if unreadable."""
    full = note_path(data_file)
    try:
        if os.path.getsize(full) > MAX_NOTE_BYTES:
            raise UploadError('This file is too large to show as a note.')
        with open(full, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError as exc:
        raise UploadError(f'Could not read {data_file.name}: {exc}') from exc


def update_text_note(data_file: Data, text: str) -> None:
    """Overwrite an editable note with ``text`` and refresh its row.

    Re-hashes and re-stamps ``mtime`` so the next sync sees the row as
    current rather than as a changed file. Does not commit.
    """
    if not is_editable(data_file):
        raise UploadError(f'{data_file.name} is not an editable text note.')
    if not (text or '').strip():
        raise UploadError('The note is empty — delete the file instead.')
    data = _encode(text)
    full = note_path(data_file)
    if not os.path.exists(full):
        raise UploadError(f'{data_file.name} is no longer on disk.')
    with open(full, 'wb') as fh:
        fh.write(data)

    cls = _description_class(data_file)
    try:
        data_file.file_hash = cls.compute_hash(full)
    except Exception:
        # ``ValueError`` is a class opting out of hashing; anything else
        # leaves the hash NULL, as ``handle_upload`` does.
        data_file.file_hash = None
    stat = os.stat(full)
    data_file.mtime = datetime.fromtimestamp(stat.st_mtime)
