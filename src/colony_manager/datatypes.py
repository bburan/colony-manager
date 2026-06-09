"""
Base class and decorators for DataType descriptions.

A ``DataTypeDescription`` subclass encapsulates everything needed to work
with a particular kind of experimental data file (or folder): parsing,
hashing, and visualization callbacks.

Examples
--------
Define a new data type::

    from colony_manager.datatypes import (
        DataTypeDescription, plot_callback, pdf_callback,
    )

    class ABR(DataTypeDescription):

        def parse(self):
            ...
            return {'animal_id': ['A001'], 'date': some_date}

        def hash_files(self):
            return [self.path / 'eeg_summary.csv']

        @plot_callback('Waveforms')
        def load_waveforms(self):
            ...
            return plotly_fig

        @pdf_callback('Waveforms PDF')
        def get_waveforms_pdf(self):
            return self.path / 'waveforms.pdf'

Use it::

    >>> obj = ABR('/data/20220601 A001 abr_io')
    >>> obj.parse()
    {'animal_id': ['A001'], 'date': datetime.date(2022, 6, 1)}
    >>> ABR.get_callbacks()
    {'Waveforms': {'type': 'plot', 'method_name': 'load_waveforms'}, ...}
"""

import importlib
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

import xxhash

from .models import Data


# Files smaller than ``2 * HASH_CHUNK`` are hashed in full; larger files
# fold size + first chunk + last chunk into the digest. For non-malicious
# data the collision probability is effectively zero, and the cost is
# constant (~2 MiB per file) regardless of file size.
HASH_CHUNK = 1 << 20  # 1 MiB


def cache_root(namespace):
    """Return the on-disk cache directory for a given namespace.

    Uses the ``COLONY_MANAGER_CACHE_DIR`` env var as the root, falling
    back to ``<tempdir>/colony_manager``. ``namespace`` becomes a
    subdirectory (e.g. ``'thumbnails'``, ``'czi-maxproj'``) so different
    artifact kinds don't collide. The directory is *not* created here —
    callers should ``mkdir(parents=True, exist_ok=True)`` as needed.

    Parameters
    ----------
    namespace : str
        Subdirectory name distinguishing this artifact kind.

    Returns
    -------
    pathlib.Path
    """
    base = os.environ.get('COLONY_MANAGER_CACHE_DIR') or os.path.join(
        tempfile.gettempdir(), 'colony_manager',
    )
    return Path(base) / namespace


# ---------------------------------------------------------------------------
# Callback decorators
# ---------------------------------------------------------------------------

def plot_callback(name, icon=None):
    """Mark a method as a Plotly-figure callback.

    Parameters
    ----------
    name : str
        Friendly name shown in the UI (e.g. ``'Waveforms'``).
    icon : str, optional
        Font Awesome icon name override (e.g. ``'fa-brain'``). Falls back to
        ``fa-chart-line`` when not provided.
    """
    def decorator(method):
        method._callback_type = 'plot'
        method._callback_name = name
        method._callback_icon = icon
        return method
    return decorator


def pdf_callback(name, icon=None):
    """Mark a method as a PDF-path callback.

    Parameters
    ----------
    name : str
        Friendly name shown in the UI (e.g. ``'Waveforms PDF'``).
    icon : str, optional
        Font Awesome icon name override (e.g. ``'fa-file-waveform'``). Falls
        back to ``fa-file-pdf`` when not provided.
    """
    def decorator(method):
        method._callback_type = 'pdf'
        method._callback_name = name
        method._callback_icon = icon
        return method
    return decorator


def dict_callback(name, icon=None):
    """Mark a method as a dict-returning callback (e.g. experiment settings).

    The method should return a flat ``{label: value}`` mapping that will
    be rendered in the UI as a definition list inside a modal popup.

    Parameters
    ----------
    name : str
        Friendly name shown in the UI (e.g. ``'Settings'``).
    icon : str, optional
        Font Awesome icon name override (e.g. ``'fa-sliders'``). Falls back to
        ``fa-list`` when not provided.
    """
    def decorator(method):
        method._callback_type = 'dict'
        method._callback_name = name
        method._callback_icon = icon
        return method
    return decorator


def image_callback(name, icon=None):
    """Mark a method as an image callback (returns path or BytesIO).

    Parameters
    ----------
    name : str
        Friendly name shown in the UI (e.g. ``'Thumbnail'``).
    icon : str, optional
        Font Awesome icon name override (e.g. ``'fa-microscope'``). Falls back
        to ``fa-image`` when not provided.
    """
    def decorator(method):
        method._callback_type = 'image'
        method._callback_name = name
        method._callback_icon = icon
        return method
    return decorator


def video_callback(name, icon=None):
    """Mark a method as a video callback (returns a file path or BytesIO).

    The method should return either an absolute path to a video file or a
    ``BytesIO`` object containing video data.  The result is streamed to the
    browser and displayed in an embedded ``<video>`` player inside a modal.

    Parameters
    ----------
    name : str
        Friendly name shown in the UI (e.g. ``'Behaviour'``).
    icon : str, optional
        Font Awesome icon name override (e.g. ``'fa-film'``). Falls back to
        ``fa-video`` when not provided.
    """
    def decorator(method):
        method._callback_type = 'video'
        method._callback_name = name
        method._callback_icon = icon
        return method
    return decorator


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class DataTypeDescription(ABC):
    """Base class for data type descriptions.

    Subclasses define how to parse, hash, and visualize a particular
    kind of experimental data file (or folder).

    Parameters
    ----------
    path : str or Path
        Absolute path to the data file or folder on disk.
    """

    def __init_subclass__(cls, **kwargs):
        """Collect decorated callback methods into a class-level registry."""
        super().__init_subclass__(**kwargs)
        callbacks = {}
        for attr_name in dir(cls):
            try:
                method = getattr(cls, attr_name, None)
            except Exception:
                continue
            if callable(method) and hasattr(method, '_callback_type'):
                callbacks[method._callback_name] = {
                    'type': method._callback_type,
                    'method_name': attr_name,
                    'icon': method._callback_icon,
                }
        cls._callbacks = callbacks

    def __init__(self, obj):
        if isinstance(obj, (Path, str)):
            self.path = Path(obj)
        elif isinstance(obj, Data):
            self.path = Path(obj.location.base_path) / obj.relative_path
        else:
            raise ValueError(f'Unrecognized object type: {type(obj)}')

    # -- Abstract interface --------------------------------------------------

    @abstractmethod
    def parse(self):
        """Parse the file/folder and return a metadata dictionary.

        Returns
        -------
        dict or None
            Metadata for matching against database entities. Return
            ``None`` if the path cannot be parsed by this description.
            Expected keys depend on the DataType's ``target_type``:

            - ``animal_event``: ``{'animal_id', 'date', 'side'?}``
            - ``confocal_image``: ``{'animal_id', 'ear', 'frequency',
              'image_type'}``
            - ``animal``: ``{'animal_id', 'date'?}``
            - ``ear``: ``{'animal_id', 'side', 'date'?}``
        """
        ...

    @abstractmethod
    def hash_files(self):
        """Return paths whose content should be hashed to identify this data.

        For a single-file DataType, return ``[self.path]``.  For a
        folder DataType, return the subset of files that uniquely
        identify the dataset.  Return an empty list to skip hashing.

        Returns
        -------
        list of Path
            File paths used for generating a content hash.
        """
        ...

    # -- Rating / scoring status ---------------------------------------------

    supports_rating: bool = False
    """Set to ``True`` on subclasses that can report whether their data
    has been scored or rated (e.g. peak-picked ABR waveforms).  The
    nightly ``flask data sync-rating`` job skips any DataTypeDescription
    whose class has this set to ``False``."""

    def get_rating_status(self):
        """Return rating completeness, or ``None`` if not applicable.

        Called by the nightly sync job; result is cached in
        ``Data.is_rated`` / ``Data.rating_note``.

        Returns
        -------
        dict or None
            ``{'is_rated': bool, 'note': str | None}`` when
            ``supports_rating`` is ``True``; ``None`` otherwise.
        """
        return None

    # -- Upload contract -----------------------------------------------------
    #
    # Subclasses opt in to the upload-from-UI flow by defining a
    # ``upload_filename`` classmethod. The base class deliberately does NOT
    # define one — its absence is the opt-out signal that
    # :func:`is_upload_capable` checks for. See ``docs/uploads.md``.
    #
    # Expected signature::
    #
    #   @classmethod
    #   def upload_filename(cls, targets, original_filename, *, date, notes):
    #       '''Return the relative path to use when ``targets`` upload
    #       ``original_filename``.
    #
    #       ``targets`` is a non-empty list of target instances (Animal,
    #       Ear, ...), all of the same target_type. Single-target
    #       descriptions can use ``targets[0]``; multi-target descriptions
    #       can join e.g. ``' '.join(t.custom_id for t in targets)`` to
    #       mirror the sync parser's multi-animal filename convention.
    #
    #       Return either a plain basename
    #       (``A001_2026-06-03.jpg``) or a forward-slash-separated
    #       relative path with subdirectories
    #       (``A001/2026-06-03.jpg``). Subdirectories are auto-created
    #       under the chosen ``DataLocation``; ``..`` segments are
    #       rejected by the service. Preserve the original file
    #       extension so the UI's image bucket-sort can render
    #       thumbnails.
    #       '''

    # -- Callback introspection & invocation ---------------------------------

    @classmethod
    def get_callbacks(cls):
        """Return the registered callbacks for this description class.

        Returns
        -------
        dict
            ``{friendly_name: {'type': str, 'method_name': str}}``.
        """
        return cls._callbacks

    def invoke_callback(self, callback_name):
        """Invoke a named callback method.

        Parameters
        ----------
        callback_name : str
            The friendly name passed to the decorator.

        Returns
        -------
        object
            The return value of the callback (Plotly figure, file path,
            image buffer, etc.).

        Raises
        ------
        KeyError
            If no callback with the given name is registered.
        """
        info = self._callbacks[callback_name]
        method = getattr(self, info['method_name'])
        return method()

    # -- Hashing -------------------------------------------------------------

    @classmethod
    def compute_hash(cls, path):
        """Compute a stable content hash for the data at *path*.

        Instantiates the description, calls ``hash_files()``, and folds
        the sorted file list into a single 128-bit ``xxh3_128`` digest.
        For each file, the size and head/tail bytes are mixed in:

        * Files ≤ ``2 * HASH_CHUNK`` are read in full.
        * Larger files contribute ``size`` + first ``HASH_CHUNK`` bytes
          + last ``HASH_CHUNK`` bytes.

        xxh3_128 is non-cryptographic but is typically 5–20× faster than
        SHA-256 and disk-bound rather than CPU-bound. The head/tail
        scheme keeps hashing cost roughly constant per file regardless
        of size — appropriate for move-tracking, where collision
        resistance on non-malicious data is the only concern.

        Parameters
        ----------
        path : str or Path
            Absolute path to the data file or folder.

        Returns
        -------
        str
            32-character hex xxh3_128 digest.

        Raises
        ------
        ValueError
            If ``hash_files()`` returns an empty list.
        """
        instance = cls(path)
        files = sorted(instance.hash_files())
        if not files:
            raise ValueError(
                f'{cls.__name__}.hash_files() returned an empty list for '
                f'{path}; cannot compute a content hash.'
            )
        hasher = xxhash.xxh3_128()
        for f in files:
            _hash_file_into(hasher, f)
        return hasher.hexdigest()


def _hash_file_into(hasher, path):
    """Fold a single file's identity (size + head + tail) into *hasher*."""
    size = os.path.getsize(path)
    hasher.update(size.to_bytes(8, 'little'))
    with open(path, 'rb') as fh:
        if size <= 2 * HASH_CHUNK:
            while True:
                chunk = fh.read(HASH_CHUNK)
                if not chunk:
                    break
                hasher.update(chunk)
        else:
            hasher.update(fh.read(HASH_CHUNK))
            fh.seek(size - HASH_CHUNK)
            hasher.update(fh.read(HASH_CHUNK))


# ---------------------------------------------------------------------------
# Description-class registry
# ---------------------------------------------------------------------------
#
# ``DataType.description_class`` stores an opaque short key (e.g. ``'ABR'``)
# rather than a Python import path. The host project provides a registry
# module pointed at by the ``COLONY_MANAGER_DESCRIPTION_REGISTRY`` env var.
# That module must expose a ``DESCRIPTION_CLASSES`` mapping of
# ``{key: DataTypeDescription subclass}``. Example::
#
#     # mmm_db/registry.py
#     from mmm_db.cftsdata import ABR, DPOAE
#     DESCRIPTION_CLASSES = {'ABR': ABR, 'DPOAE': DPOAE}
#
# Storing a short key (instead of ``'mmm_db.cftsdata.ABR'``) decouples DB
# rows from the host project's module layout: renaming or moving the class
# doesn't require touching the database. It also closes the previous RCE
# vector — the admin-controlled column is now an opaque identifier, not an
# importable dotted path.

_REGISTRY_ENV_VAR = 'COLONY_MANAGER_DESCRIPTION_REGISTRY'
_REGISTRY_ATTR = 'DESCRIPTION_CLASSES'
_REGISTRY_CACHE = None


def _load_registry():
    """Import and validate the configured registry module.

    Returns
    -------
    dict
        ``{key: DataTypeDescription subclass}`` from the host's registry.

    Raises
    ------
    RuntimeError
        If the env var is unset, the module is missing, or the module's
        ``DESCRIPTION_CLASSES`` attribute is missing or malformed.
    """
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE

    module_path = os.environ.get(_REGISTRY_ENV_VAR, '').strip()
    if not module_path:
        raise RuntimeError(
            f'{_REGISTRY_ENV_VAR} is not set. Point it at a Python module '
            f'that defines DESCRIPTION_CLASSES (e.g. "mmm_db.registry").'
        )

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        # Convert to RuntimeError so the dropdown-fallback in
        # ``get_allowed_description_classes`` catches it and renders
        # "no choices" instead of bubbling up to a 500.
        raise RuntimeError(
            f'{_REGISTRY_ENV_VAR}={module_path!r} could not be imported: {exc}'
        ) from exc
    raw = getattr(module, _REGISTRY_ATTR, None)
    if raw is None:
        raise RuntimeError(
            f'{module_path} has no {_REGISTRY_ATTR} attribute.'
        )
    if not isinstance(raw, dict):
        raise RuntimeError(
            f'{module_path}.{_REGISTRY_ATTR} must be a dict mapping '
            f'short keys to DataTypeDescription subclasses; got '
            f'{type(raw).__name__}.'
        )

    registry = {}
    for key, cls in raw.items():
        if not isinstance(key, str) or not key:
            raise RuntimeError(
                f'{module_path}.{_REGISTRY_ATTR} keys must be non-empty '
                f'strings; got {key!r}.'
            )
        if not (isinstance(cls, type) and issubclass(cls, DataTypeDescription)):
            raise RuntimeError(
                f'{module_path}.{_REGISTRY_ATTR}[{key!r}] is not a '
                f'DataTypeDescription subclass: {cls!r}.'
            )
        registry[key] = cls

    _REGISTRY_CACHE = registry
    return registry


def reset_registry_cache():
    """Clear the cached registry. Test/migration helper."""
    global _REGISTRY_CACHE
    _REGISTRY_CACHE = None


def get_allowed_description_classes():
    """Return the sorted list of registered description-class keys."""
    try:
        return sorted(_load_registry().keys())
    except RuntimeError:
        # Misconfigured/missing registry shouldn't crash the dropdown that
        # renders the settings page. Surface it as "no choices" instead.
        return []


def get_description_class_registry():
    """Return a copy of the full ``{key: class}`` registry."""
    return dict(_load_registry())


def load_description_class(key):
    """Return the ``DataTypeDescription`` subclass registered under *key*.

    Parameters
    ----------
    key : str
        Short identifier as stored in ``DataType.description_class``
        (e.g. ``'ABR'``).

    Raises
    ------
    ValueError
        If *key* is not present in the configured registry.
    RuntimeError
        If the registry is unconfigured or malformed (see
        :func:`_load_registry`).
    """
    registry = _load_registry()
    try:
        return registry[key]
    except KeyError:
        raise ValueError(
            f'{key!r} is not registered in {_REGISTRY_ENV_VAR}. '
            f'Known keys: {sorted(registry)}.'
        )


def is_upload_capable(description_cls):
    """True if *description_cls* opts in to the upload-from-UI flow.

    The opt-in is presence of an ``upload_filename`` method anywhere in
    the MRO except the abstract base. Walking the MRO lets a subclass
    inherit upload capability from a parent without redeclaring the
    method, while keeping :class:`DataTypeDescription` itself out (it
    intentionally does not define one).
    """
    for cls in description_cls.__mro__:
        if cls in (DataTypeDescription, object):
            continue
        if 'upload_filename' in cls.__dict__:
            return True
    return False
