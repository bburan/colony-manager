"""Database query and filtering logic for the cage list view."""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from colony_manager.models import (
    Animal, AnimalEvent, AnimalProcedure, AnimalTag, Cage, Source,
)


def get_filtered_cages(session, filters: dict):
    """Return all cages matching ``filters``.

    Expected filter keys (all optional, with defaults):
        sort_by (str)          — 'custom_id' | 'age' | 'animal_count' |
                                  'active_count'
        sort_dir (str)         — 'asc' | 'desc'
        status_filter (str)    — 'active' | 'inactive' | 'all'
        sex_filter (str)       — 'male' | 'female' | 'mixed' | 'all'
        source_id (str)        — Source.id or 'all'
        occupancy_filter (str) — 'empty' | 'single' | 'multi' | 'all'
        notes_filter (str)     — 'yes' | 'no' | 'all'
        tag_id (str)           — AnimalTag.id or 'all'
        procedure_id (str)     — AnimalProcedure.id or 'all'
        species_id (int)       — -1 means no species filter
    """
    stmt = select(Cage).options(
        joinedload(Cage.species),
        selectinload(Cage.animals).joinedload(Animal.source),
    )

    species_id = filters.get('species_id', -1)
    if species_id != -1:
        stmt = stmt.where(Cage.species_id == species_id)

    status_filter = filters.get('status_filter', 'active')
    if status_filter == 'active':
        stmt = stmt.where(Cage.animals.any(Animal.terminated == False))  # noqa: E712
    elif status_filter == 'inactive':
        stmt = stmt.where(~Cage.animals.any(Animal.terminated == False))  # noqa: E712

    sex_filter = filters.get('sex_filter', 'all')
    if sex_filter in ('male', 'female'):
        other = 'female' if sex_filter == 'male' else 'male'
        stmt = stmt.where(
            Cage.animals.any(Animal.sex == sex_filter)
            & ~Cage.animals.any(Animal.sex == other)
        )
    elif sex_filter == 'mixed':
        stmt = stmt.where(
            Cage.animals.any(Animal.sex == 'male')
            & Cage.animals.any(Animal.sex == 'female')
        )

    source_id = filters.get('source_id', 'all')
    if source_id != 'all':
        stmt = stmt.where(Cage.animals.any(Animal.source_id == int(source_id)))

    notes_filter = filters.get('notes_filter', 'all')
    if notes_filter == 'yes':
        stmt = stmt.where(
            Cage.notes.is_not(None) & (func.trim(Cage.notes) != '')
        )
    elif notes_filter == 'no':
        stmt = stmt.where(or_(
            Cage.notes.is_(None), func.trim(Cage.notes) == ''
        ))

    tag_id = filters.get('tag_id', 'all')
    if tag_id != 'all':
        tag_ids = AnimalTag.descendant_ids(session, int(tag_id))
        stmt = stmt.where(Cage.animals.any(
            Animal.tags.any(AnimalTag.id.in_(tag_ids))
        ))

    procedure_id = filters.get('procedure_id', 'all')
    if procedure_id != 'all':
        proc_ids = AnimalProcedure.descendant_ids(session, int(procedure_id))
        stmt = stmt.where(Cage.animals.any(
            Animal.events.any(AnimalEvent.procedure_id.in_(proc_ids))
        ))

    # Subqueries for occupancy filtering and sorting.
    active_count_subq = (
        select(
            Animal.cage_id.label('cage_id'),
            func.count(Animal.id).label('active_count'),
        )
        .where(Animal.terminated == False)  # noqa: E712
        .group_by(Animal.cage_id)
        .subquery()
    )
    total_count_subq = (
        select(
            Animal.cage_id.label('cage_id'),
            func.count(Animal.id).label('total_count'),
            func.min(Animal.dob).label('min_dob'),
            func.max(Animal.dob).label('max_dob'),
        )
        .group_by(Animal.cage_id)
        .subquery()
    )

    stmt = (
        stmt
        .outerjoin(active_count_subq, active_count_subq.c.cage_id == Cage.id)
        .outerjoin(total_count_subq, total_count_subq.c.cage_id == Cage.id)
    )

    active_count_col = func.coalesce(active_count_subq.c.active_count, 0)
    total_count_col = func.coalesce(total_count_subq.c.total_count, 0)

    occupancy_filter = filters.get('occupancy_filter', 'all')
    if occupancy_filter == 'empty':
        stmt = stmt.where(active_count_col == 0)
    elif occupancy_filter == 'single':
        stmt = stmt.where(active_count_col == 1)
    elif occupancy_filter == 'multi':
        stmt = stmt.where(active_count_col > 1)

    sort_by = filters.get('sort_by', 'custom_id')
    sort_dir = filters.get('sort_dir', 'asc')

    if sort_by == 'age':
        # asc age = youngest first = max(dob) desc
        col = total_count_subq.c.max_dob
        order = col.asc().nullslast() if sort_dir == 'desc' else col.desc().nullslast()
    elif sort_by == 'animal_count':
        col = total_count_col
        order = col.desc() if sort_dir == 'desc' else col.asc()
    elif sort_by == 'active_count':
        col = active_count_col
        order = col.desc() if sort_dir == 'desc' else col.asc()
    else:  # 'custom_id'
        col = Cage.custom_id
        order = col.desc() if sort_dir == 'desc' else col.asc()

    return session.scalars(stmt.order_by(order)).unique().all()


def get_cage_filter_options(session):
    """Return lookup lists for the cage list filter UI."""
    return {
        'sources': session.scalars(select(Source).order_by(Source.name)).all(),
        'animal_tags': AnimalTag.get_ordered(session),
        'procedures': AnimalProcedure.get_ordered(session),
    }
