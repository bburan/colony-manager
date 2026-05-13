"""Business logic for linking ``Data`` files to events / images / ears.

These helpers used to live as private ``_parse_orphan_*`` / ``_resync_*``
functions inside the route modules. They all share the same shape — load a
file's description class, re-parse it, then match parsed fields against an
entity — so they're consolidated here.

``parse()`` on a description class is cheap (filename regex, no disk I/O)
but loading the class itself isn't, so callers that iterate many files
should reuse a ``desc_cache`` dict.
"""
import os
from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import or_

from colony_manager.datatypes import load_description_class
from colony_manager.models import (
    Animal, AnimalEvent, AnimalEventData, AnimalEventDataType,
    _canonical_side, _expand_sides,
)
from colony_manager_gui import db


def to_json_safe(value):
    """Recursively convert a parsed dict so it round-trips through JSON.

    Date / datetime values become ISO strings; tuples become lists. Other
    types pass through and rely on the JSON encoder. Used when persisting
    ``Data.parsed_metadata`` so the column can hold whatever a description
    class's ``parse()`` returns.
    """
    if isinstance(value, dict):
        return {k: to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# File parsing helpers
# ---------------------------------------------------------------------------

def parsed_animal_sides(f, animal_custom_id):
    """Sides the parser assigns to ``animal_custom_id`` in file ``f``.

    Returns ``None`` when the parser does not see this animal in this file,
    or a list of canonical sides otherwise. An empty list means "animal is
    present but no side was parsed". Reads from ``f.parsed_metadata`` when
    available; falls back to a live parse for legacy rows.
    """
    parsed = f.parsed_metadata
    if parsed is None:
        try:
            cls = f.datatype.get_description()
            parsed = cls(f).parse() or {}
        except Exception:
            return None
    raw_ids = parsed.get('animal_id')
    if not raw_ids:
        return None
    ids = list(raw_ids) if isinstance(raw_ids, (list, tuple)) else [raw_ids]
    if animal_custom_id not in ids:
        return None
    sides = _expand_sides(parsed.get('side') or parsed.get('ear'), len(ids))
    if sides is None:
        return []
    return [s for aid, s in zip(ids, sides) if aid == animal_custom_id and s]


def parse_confocal_file(f, desc_cache=None):
    """Return the parsed metadata for a ``ConfocalImageData`` file.

    Prefers the cached ``f.parsed_metadata`` column (populated by sync /
    rematch). Falls back to running the description class's ``parse()``
    for legacy rows that pre-date the column — admins who want everything
    fast should run a force-rematch to backfill.

    Callers iterating many files should pass a shared ``desc_cache`` dict
    so each description class is only loaded once on the fallback path.
    """
    if f.parsed_metadata is not None:
        return f.parsed_metadata

    dotted = f.datatype.description_class
    if not dotted:
        return None
    if desc_cache is None:
        desc_cache = {}
    if dotted not in desc_cache:
        try:
            desc_cache[dotted] = load_description_class(dotted)
        except Exception:
            desc_cache[dotted] = None
    desc_cls = desc_cache[dotted]
    if desc_cls is None:
        return None
    full_path = os.path.join(f.location.base_path, f.relative_path)
    try:
        return desc_cls(full_path).parse() or {}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Confocal image linking
# ---------------------------------------------------------------------------

def parse_orphan_confocal_files(ear):
    """Re-parse unmatched ``ConfocalImageData`` candidates attached to ``ear``.

    Returns a list of dicts with keys ``file``, ``frequency``,
    ``image_type_name``, ``side``. Files whose parsed side conflicts with
    the ear's side are dropped; files with no parsed frequency are skipped.
    """
    results = []
    desc_cache = {}
    for f in ear.candidate_data_files:
        if f.target_type != 'confocal_image' or f.confocal_images:
            continue
        parsed = parse_confocal_file(f, desc_cache)
        if parsed is None:
            continue
        try:
            freq = float(parsed.get('frequency'))
        except (TypeError, ValueError):
            continue
        side = _canonical_side(parsed.get('side') or parsed.get('ear'))
        if side and side != ear.side:
            continue
        results.append({
            'file': f,
            'frequency': freq,
            'image_type_name': parsed.get('image_type'),
            'side': side,
        })
    return results


def resync_confocal_image(image):
    """Link unmatched ``ConfocalImageData`` rows whose parsed metadata matches *image*.

    Walks ``image.ear.candidate_data_files`` filtered to unmatched confocal
    rows and links those whose parsed frequency, image type, and side line up.
    Returns the number of newly-linked files.
    """
    if image.frequency is None or image.image_type_id is None:
        return 0
    image_type_name = image.image_type.name
    desc_cache = {}
    linked = 0
    for f in image.ear.candidate_data_files:
        if f.target_type != 'confocal_image' or f.confocal_images:
            continue
        parsed = parse_confocal_file(f, desc_cache)
        if parsed is None:
            continue
        try:
            parsed_freq = float(parsed.get('frequency'))
        except (TypeError, ValueError):
            continue
        if parsed_freq != image.frequency:
            continue
        if parsed.get('image_type') != image_type_name:
            continue
        side = _canonical_side(parsed.get('side') or parsed.get('ear'))
        if side and side != image.ear.side:
            continue
        f.confocal_images.append(image)
        linked += 1
    return linked


# ---------------------------------------------------------------------------
# Animal-event file linking
# ---------------------------------------------------------------------------

def resync_event_files(event):
    """Unlink files whose date or parsed side no longer matches *event*, then link matching files."""
    new_date = event.completion_date or event.scheduled_date
    animal_custom_id = event.animal.custom_id

    # Unlink files (this event only) whose date or parsed side no longer
    # matches. A file with no parsed side is allowed to stay linked — same
    # convention as the initial sync match.
    for f in list(event.data_files):
        if f.date != new_date:
            f.events.remove(event)
            continue
        if event.side is not None:
            f_sides = parsed_animal_sides(f, animal_custom_id)
            if f_sides and event.side not in set(f_sides):
                f.events.remove(event)

    # Link AnimalEventData files matching date, animal candidacy, and the
    # DataType's default procedure. Side must match when both the event
    # and the file's parser specify one.
    candidate_files = AnimalEventData.query.filter(
        AnimalEventData.date == new_date,
    ).all()
    for f in candidate_files:
        dt = f.datatype
        if getattr(dt, 'default_procedure_id', None) != event.procedure_id:
            continue
        if event in f.events:
            continue
        if not any(a.id == event.animal_id for a in f.candidate_animals):
            continue
        if event.side is not None:
            f_sides = parsed_animal_sides(f, animal_custom_id)
            if f_sides and event.side not in set(f_sides):
                continue
        f.events.append(event)


@dataclass
class AutoCreateResult:
    """Outcome of :func:`auto_create_animal_event`.

    ``error`` is set when the operation could not proceed (no default
    procedure, no parsed date, side required but unresolved, …); the
    counts describe what actually happened on the success path.
    """
    error: str | None = None
    created: int = 0
    reused: int = 0
    linked: int = 0


def auto_create_animal_event(animal, data_file):
    """Auto-create an ``AnimalEvent`` for an unassigned file, then link siblings.

    Reuses an existing matching event if one is already on the animal —
    avoids duplicates when the user wand-clicks a second sibling file or
    re-clicks the same file after the event already exists.

    Commits the session before returning. Returns an :class:`AutoCreateResult`.
    """
    datatype = data_file.datatype
    if not getattr(datatype, 'default_procedure_id', None):
        return AutoCreateResult(error='Cannot auto-create: DataType has no Default Procedure configured.')
    if not data_file.date:
        return AutoCreateResult(error='Cannot auto-create: file has no parsed date.')

    animal_custom_id = animal.custom_id
    target = datatype.default_procedure_target
    if target is not None and target.requires_side:
        own_sides = parsed_animal_sides(data_file, animal_custom_id)
        sides = sorted(set(own_sides)) if own_sides else []
        if not sides:
            return AutoCreateResult(error=(
                'Cannot auto-create: target requires a side but the parser '
                'did not resolve one for this animal.'))
    else:
        sides = [None]

    target_events = []
    created_count = 0
    for side in sides:
        query = AnimalEvent.query.filter_by(
            animal_id=animal.id,
            procedure_id=datatype.default_procedure_id,
            procedure_target_id=datatype.default_procedure_target_id,
        ).filter(
            or_(
                AnimalEvent.scheduled_date == data_file.date,
                AnimalEvent.completion_date == data_file.date,
            )
        )
        if side is None:
            query = query.filter(AnimalEvent.side.is_(None))
        else:
            query = query.filter(AnimalEvent.side == side)
        existing = query.first()
        if existing:
            target_events.append(existing)
        else:
            event = AnimalEvent(
                animal_id=animal.id,
                procedure_id=datatype.default_procedure_id,
                procedure_target_id=datatype.default_procedure_target_id,
                side=side,
                scheduled_date=data_file.date,
                completion_date=data_file.date,
            )
            db.session.add(event)
            target_events.append(event)
            created_count += 1
    db.session.flush()

    # Link any AnimalEventData on this date whose datatype shares the
    # event's procedure — covers same-datatype siblings *and* sister
    # datatypes (e.g. ABR + DPOAE both defaulting to Physiology).
    # ``candidate_animals`` is deliberately not in the SQL filter: it can
    # be stale (file synced before the animal existed) and would silently
    # drop files the parser would otherwise place on this animal. The
    # reparse below is the authoritative animal/side check.
    candidate_files = AnimalEventData.query.join(
        AnimalEventDataType,
        AnimalEventData.datatype_id == AnimalEventDataType.id,
    ).filter(
        AnimalEventDataType.default_procedure_id == datatype.default_procedure_id,
        AnimalEventData.date == data_file.date,
    ).all()
    linked_count = 0
    for f in candidate_files:
        f_sides = parsed_animal_sides(f, animal_custom_id)
        if f_sides is None:
            continue
        f_sides = set(f_sides)
        for event in target_events:
            if event in f.events:
                continue
            if event.side is not None and f_sides and event.side not in f_sides:
                continue
            f.events.append(event)
            linked_count += 1

    db.session.commit()
    return AutoCreateResult(
        created=created_count,
        reused=len(target_events) - created_count,
        linked=linked_count,
    )
