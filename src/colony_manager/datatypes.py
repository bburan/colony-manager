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

import hashlib
import importlib
from abc import ABC, abstractmethod
from pathlib import Path


# ---------------------------------------------------------------------------
# Callback decorators
# ---------------------------------------------------------------------------

def plot_callback(name):
    """Mark a method as a Plotly-figure callback.

    Parameters
    ----------
    name : str
        Friendly name shown in the UI (e.g. ``'Waveforms'``).
    """
    def decorator(method):
        method._callback_type = 'plot'
        method._callback_name = name
        return method
    return decorator


def pdf_callback(name):
    """Mark a method as a PDF-path callback.

    Parameters
    ----------
    name : str
        Friendly name shown in the UI (e.g. ``'Waveforms PDF'``).
    """
    def decorator(method):
        method._callback_type = 'pdf'
        method._callback_name = name
        return method
    return decorator


def image_callback(name):
    """Mark a method as an image callback (returns path or BytesIO).

    Parameters
    ----------
    name : str
        Friendly name shown in the UI (e.g. ``'Thumbnail'``).
    """
    def decorator(method):
        method._callback_type = 'image'
        method._callback_name = name
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
                }
        cls._callbacks = callbacks

    def __init__(self, path):
        self.path = Path(path)

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

        Instantiates the description, calls ``hash_files()``, and
        produces a hex-digest from the sorted concatenation of each
        file's SHA-256.

        Parameters
        ----------
        path : str or Path
            Absolute path to the data file or folder.

        Returns
        -------
        str
            Hex SHA-256 hash string.

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
        hasher = hashlib.sha256()
        for f in files:
            with open(f, 'rb') as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    hasher.update(chunk)
        return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Dynamic class loading
# ---------------------------------------------------------------------------

_DESCRIPTION_CACHE = {}


def load_description_class(dotted_path):
    """Import and return a DataTypeDescription subclass by dotted path.

    Parameters
    ----------
    dotted_path : str
        Fully-qualified class name, e.g. ``'mmm_db.cftsdata.ABR'``.

    Returns
    -------
    type
        A subclass of :class:`DataTypeDescription`.

    Raises
    ------
    ImportError
        If the module cannot be imported.
    AttributeError
        If the class does not exist on the module.
    TypeError
        If the resolved object is not a ``DataTypeDescription`` subclass.
    """
    if dotted_path in _DESCRIPTION_CACHE:
        return _DESCRIPTION_CACHE[dotted_path]
    module_name, class_name = dotted_path.rsplit('.', 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    if not (isinstance(cls, type) and issubclass(cls, DataTypeDescription)):
        raise TypeError(
            f'{dotted_path} is not a DataTypeDescription subclass'
        )
    _DESCRIPTION_CACHE[dotted_path] = cls
    return cls
