"""
Pluggable callbacks used by DataType.

Two flavors:

* **Parse callbacks** — invoked by the nightly sync script. Take
  ``(relative_path, location)`` and return a metadata dict (or ``None`` to
  skip). Recognized keys depend on the DataType's ``target_type``:

    - animal_event:    {'animal_id': 'A001' | ['A001', 'A002'], 'date': date}
    - confocal_image:  {'animal_id': ..., 'side': 'L'|'R', 'frequency': 8.0,
                        'image_type': 'CtBP2', 'date': date (optional)}
    - animal:          {'animal_id': 'A001' | ['A001', 'A002'],
                        'date': date (optional)}
    - ear:             {'animal_id': ..., 'side': 'Left'|'Right',
                        'date': date (optional)}

* **Display callbacks** — invoked by the UI to render plots, PDFs, or images
  for a Data row. Take a ``Data`` instance and return a Plotly figure (plot),
  a path to a PDF (pdf), or a path to a JPG (image).
"""
import os
import re
from datetime import datetime


# --- Parse callbacks ----------------------------------------------------------

_DATE_FORMATS = ('%Y-%m-%d', '%Y%m%d', '%m-%d-%Y', '%Y_%m_%d')


def _parse_date(date_str):
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    return None


def parse_animal_event_filename(relative_path, location):
    """Default parser for animal-event files.

    Looks for ``<animal_id>`` and ``<date>`` substrings anywhere in the
    relative path. Animal IDs may be separated by ``,``, ``+``, ``&`` or ``|``
    when a single file applies to multiple animals (e.g., group exposures).
    """
    name = os.path.basename(relative_path)
    date_match = re.search(r'(\d{4}[-_]?\d{2}[-_]?\d{2})', name)
    if not date_match:
        return None
    parsed_date = _parse_date(date_match.group(1))
    if parsed_date is None:
        return None

    animal_match = re.search(r'([A-Za-z]+\d+(?:[,+&|][A-Za-z]+\d+)*)', name)
    animal_ids = []
    if animal_match:
        animal_ids = [a.strip() for a in re.split(r'[,+&|]', animal_match.group(1)) if a.strip()]
    return {'animal_id': animal_ids, 'date': parsed_date}


def parse_confocal_image_filename(relative_path, location):
    """Default parser for confocal-image files.

    Expects names like ``A001_L_8kHz_CtBP2.jpg``. Adjust on a per-DataType
    basis by writing your own callable and pointing parse_function at it.
    """
    name = os.path.basename(relative_path)
    stem, _ = os.path.splitext(name)
    parts = stem.split('_')
    if len(parts) < 4:
        return None
    animal_id, side, freq_token, image_type = parts[0], parts[1], parts[2], parts[3]
    freq_match = re.match(r'([\d.]+)', freq_token)
    if not freq_match:
        return None
    try:
        frequency = float(freq_match.group(1))
    except ValueError:
        return None
    if side not in ('L', 'R', 'Left', 'Right'):
        return None
    side = 'Left' if side in ('L', 'Left') else 'Right'
    return {
        'animal_id': [animal_id],
        'side': side,
        'frequency': frequency,
        'image_type': image_type,
    }


def parse_animal_image_filename(relative_path, location):
    """Default parser for animal-attached image files.

    Pulls every animal ID it can find in the basename so a single image can be
    associated with multiple animals (e.g., a litter portrait). Animal IDs may
    be separated by ``,``, ``+``, ``&`` or ``|``. An optional date substring
    is parsed if present.
    """
    name = os.path.basename(relative_path)
    stem, _ = os.path.splitext(name)

    animal_match = re.search(r'([A-Za-z]+\d+(?:[,+&|][A-Za-z]+\d+)*)', stem)
    if not animal_match:
        return None
    animal_ids = [a.strip() for a in re.split(r'[,+&|]', animal_match.group(1)) if a.strip()]
    if not animal_ids:
        return None

    parsed_date = None
    date_match = re.search(r'(\d{4}[-_]?\d{2}[-_]?\d{2})', stem)
    if date_match:
        parsed_date = _parse_date(date_match.group(1))

    return {'animal_id': animal_ids, 'date': parsed_date}


def parse_ear_image_filename(relative_path, location):
    """Default parser for ear-attached image files.

    Expects the side as a standalone ``L``/``R``/``Left``/``Right`` token in
    the basename, plus one or more animal IDs. Files are attached to one ear
    per matched animal.
    """
    name = os.path.basename(relative_path)
    stem, _ = os.path.splitext(name)

    animal_match = re.search(r'([A-Za-z]+\d+(?:[,+&|][A-Za-z]+\d+)*)', stem)
    if not animal_match:
        return None
    animal_ids = [a.strip() for a in re.split(r'[,+&|]', animal_match.group(1)) if a.strip()]
    if not animal_ids:
        return None

    side = None
    for token in re.split(r'[_\-\s]+', stem):
        if token in ('L', 'Left'):
            side = 'Left'
            break
        if token in ('R', 'Right'):
            side = 'Right'
            break
    if side is None:
        return None

    parsed_date = None
    date_match = re.search(r'(\d{4}[-_]?\d{2}[-_]?\d{2})', stem)
    if date_match:
        parsed_date = _parse_date(date_match.group(1))

    return {'animal_id': animal_ids, 'side': side, 'date': parsed_date}


# --- Display callbacks --------------------------------------------------------

def load_physiology(data_file):
    """Example plot loader for 'physiology' DataType."""
    full_path = os.path.join(data_file.location.base_path, data_file.relative_path)
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"File not found on disk: {full_path}")
    return {
        "status": "success",
        "message": f"Loaded physiology data from {full_path}",
        "raw_attributes": {"name": data_file.name},
    }


def load_noise_exposure(data_file):
    """Example plot loader for noise exposure data."""
    full_path = os.path.join(data_file.location.base_path, data_file.relative_path)
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"File not found on disk: {full_path}")
    return {
        "status": "success",
        "message": f"Loaded noise exposure summary from {full_path}",
    }


def view_confocal_image(data_file):
    """Example image callback. Returns a path to a JPG on disk."""
    full_path = os.path.join(data_file.location.base_path, data_file.relative_path)
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"File not found on disk: {full_path}")
    return full_path
