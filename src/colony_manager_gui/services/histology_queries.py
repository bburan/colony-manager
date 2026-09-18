"""Database query and filtering logic for the histology list and grid views."""
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Select, exists, or_, select
from sqlalchemy.orm import Session, contains_eager, selectinload

from colony_manager.enums import ConfocalImageStatus
from colony_manager.models import (
    Animal, AnimalEvent, AnimalProcedure, AnimalTag, AnimalEventTag,
    Ear, EarTag, Study, ConfocalImage,
)

# Choices for the Analysis filter, rendered by ``partials/ear_filter_card.html``
# and resolved by ``_analysis_filter_clause`` below. The two used to be
# written separately — the card offered 'pending' / 'needs_review' / 'done'
# while the query compared them straight against ``ConfocalImage.status``,
# whose values are 'imaged' / 'analyzed' / 'need_review' / 'region_missing' /
# 'region_bad'. Only 'imaged' ever matched; the other three silently returned
# no ears at all. Keeping the list here means a new option has to be given a
# clause before it can be offered.
EAR_ANALYSIS_FILTERS = [
    ('all', 'All'),
    ('pending', 'Pending'),
    ('imaged', 'Imaged'),
    ('needs_review', 'Needs Review'),
    ('done', 'Done'),
]

# Statuses that still represent outstanding work. The other three are
# terminal: ``analyzed`` is finished, and ``region_missing`` / ``region_bad``
# say there is nothing to analyze — an ear whose every image is one of those
# is as done as it will ever be.
_OUTSTANDING_STATUSES = (
    ConfocalImageStatus.IMAGED,
    ConfocalImageStatus.NEED_REVIEW,
)

_EAR_SORT_DIR_DEFAULTS = {
    'id': 'asc',
    'euthanasia': 'desc',
    'cryoprotection': 'desc',
    'dissection': 'desc',
    'immunolabel': 'desc',
}


def _ear_sort_cols():
    return {
        'id': Animal.custom_id,
        'euthanasia': Animal.termination_date,
        'cryoprotection': Ear.cryoprotection_date,
        'dissection': Ear.dissection_date,
        'immunolabel': Ear.immunolabel_date,
    }


def parse_ear_filters(args: Mapping[str, str], species_id: int = -1) -> dict[str, Any]:
    """Parse filter parameters from a request.args-like mapping.

    ``species_id`` must be resolved by the caller from the Flask session
    (it is not read here so this function stays framework-independent).
    Returns a dict suitable for ``apply_ear_filters`` and ``apply_ear_sort``.
    """
    sort_by = args.get('sort_by', 'id')
    sort_dir = args.get('sort_dir', '')
    if sort_dir not in ('asc', 'desc'):
        sort_dir = _EAR_SORT_DIR_DEFAULTS.get(sort_by, 'asc')
    return {
        'sort_by': sort_by,
        'sort_dir': sort_dir,
        'immunolabel_filter': args.get('immunolabel_filter', 'all'),
        'analysis_filter': args.get('analysis_filter', 'all'),
        'side_filter': args.get('side_filter', 'all'),
        'tag_id': args.get('tag_id', 'all'),
        'cryo_filter': args.get('cryo_filter', 'all'),
        'sex_filter': args.get('sex_filter', 'all'),
        'procedure_id': args.get('procedure_id', 'all'),
        'animal_tag_id': args.get('animal_tag_id', 'all'),
        'event_tag_id': args.get('event_tag_id', 'all'),
        'study_id': args.get('study_id', 'all'),
        'species_id': species_id,
    }


def _has_image(*status_clauses):
    """``EXISTS`` over this ear's confocal images, narrowed by *status_clauses*."""
    return exists().where(ConfocalImage.ear_id == Ear.id, *status_clauses)


def _status_in(statuses):
    """Match ``ConfocalImage.status`` against *statuses*, NULL reading as imaged.

    The column is nullable and every other reader treats NULL as
    ``imaged`` (``ConfocalImage.conflict``, ``grid_status_square.html``).
    Without the same fold here a never-touched image would count as
    terminal, and an ear full of them would file itself under *Done*.
    """
    clause = ConfocalImage.status.in_([str(s) for s in statuses])
    if ConfocalImageStatus.IMAGED in statuses:
        clause = or_(clause, ConfocalImage.status.is_(None))
    return clause


def _analysis_filter_clause(value):
    """Return the WHERE clause for one Analysis filter value, or None.

    None means "no filtering" — either the *All* option or a value that is
    not offered at all.
    """
    if value == 'imaged':
        return _has_image(_status_in([ConfocalImageStatus.IMAGED]))
    if value == 'needs_review':
        return _has_image(_status_in([ConfocalImageStatus.NEED_REVIEW]))
    if value == 'pending':
        # Any image still to be worked — the union of the two above.
        return _has_image(_status_in(_OUTSTANDING_STATUSES))
    if value == 'done':
        # Imaged at all, and nothing left outstanding. The first half
        # matters: an ear with no images has no outstanding work either,
        # and calling that "done" would fill the filter with ears nobody
        # has started.
        return _has_image() & ~_has_image(_status_in(_OUTSTANDING_STATUSES))
    return None


def apply_ear_filters(query: Select[Any], filters: dict[str, Any], session: Session) -> Select[Any]:
    """Apply every filter from ``parse_ear_filters`` to ``query``.

    Assumes ``query`` is rooted on ``Ear`` and already joined to ``Animal``
    (needed for sex / sort by custom_id or termination_date).
    """
    # An ear is "labeled" once it has an immunolabeling panel assigned —
    # not by the date, which is sometimes left blank even after labeling.
    if filters['immunolabel_filter'] == 'labeled':
        query = query.where(Ear.panel_id.is_not(None))
    elif filters['immunolabel_filter'] == 'pending':
        query = query.where(Ear.panel_id.is_(None))

    if filters['cryo_filter'] == 'done':
        query = query.where(Ear.cryoprotection_date.is_not(None))
    elif filters['cryo_filter'] == 'pending':
        query = query.where(Ear.cryoprotection_date.is_(None))

    if filters['side_filter'] in ('Left', 'Right'):
        query = query.where(Ear.side == filters['side_filter'])

    if filters['tag_id'] != 'all':
        ids = EarTag.descendant_ids(session, int(filters['tag_id']))
        query = query.where(Ear.tags.any(EarTag.id.in_(ids)))

    if filters['sex_filter'] in ('male', 'female'):
        query = query.where(Animal.sex == filters['sex_filter'])

    if filters['procedure_id'] != 'all':
        ids = AnimalProcedure.descendant_ids(session, int(filters['procedure_id']))
        query = query.where(Animal.events.any(
            AnimalEvent.procedure_id.in_(ids)
        ))

    if filters['animal_tag_id'] != 'all':
        ids = AnimalTag.descendant_ids(session, int(filters['animal_tag_id']))
        query = query.where(Animal.tags.any(AnimalTag.id.in_(ids)))

    if filters['event_tag_id'] != 'all':
        ids = AnimalEventTag.descendant_ids(session, int(filters['event_tag_id']))
        query = query.where(Animal.events.any(
            AnimalEvent.tags.any(AnimalEventTag.id.in_(ids))
        ))

    if filters['study_id'] != 'all':
        query = query.where(Animal.studies.any(
            Study.id == int(filters['study_id'])
        ))

    clause = _analysis_filter_clause(filters['analysis_filter'])
    if clause is not None:
        query = query.where(clause)

    species_id = filters.get('species_id', -1)
    if species_id != -1:
        query = query.where(Animal.species_id == species_id)

    return query


def apply_ear_sort(query: Select[Any], filters: dict[str, Any]) -> Select[Any]:
    col = _ear_sort_cols().get(filters['sort_by'], Animal.custom_id)
    if filters['sort_dir'] == 'desc':
        order = col.desc().nullslast()
    else:
        order = col.asc().nullsfirst()
    return query.order_by(order, Ear.side)


def get_ear_filter_options(session: Session) -> dict[str, list[Any]]:
    """Return lookup lists for the histology filter UI."""
    return {
        # Static rather than a lookup, but it belongs with the rest of what
        # the filter card needs: the card renders whatever is here, so an
        # option can't be offered without ``_analysis_filter_clause``
        # knowing how to answer it.
        'analysis_filters': EAR_ANALYSIS_FILTERS,
        'ear_tags': EarTag.get_ordered(session),
        'procedures': AnimalProcedure.get_ordered(session),
        'animal_tags': AnimalTag.get_ordered(session),
        'event_tags': AnimalEventTag.get_ordered(session),
        'studies': session.scalars(select(Study).order_by(Study.name)).all(),
    }


def get_filtered_ears(session: Session, filters: dict[str, Any]) -> list[Ear]:
    """Return ears matching ``filters`` (convenience wrapper for list view)."""
    stmt = apply_ear_filters(
        select(Ear).join(Animal).options(
            contains_eager(Ear.animal),
            selectinload(Ear.tags),
        ),
        filters,
        session,
    )
    return session.scalars(apply_ear_sort(stmt, filters)).all()
