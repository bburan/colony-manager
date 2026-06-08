"""Database query and filtering logic for the animal list view."""
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from colony_manager.models import (
    Animal, AnimalEvent, AnimalProcedure, AnimalTag, AnimalEventTag, Study,
)


def get_filtered_animals(session: Session, filters: dict[str, Any]) -> list[Animal]:
    """Return all animals matching ``filters``.

    Expected filter keys (all optional, with defaults):
        sort_by (str)         — 'id' | 'age' | 'event_date'
        sort_dir (str)        — 'asc' | 'desc'
        status_filter (str)   — 'active' | 'terminated' | 'all'
        sex_filter (str)      — 'male' | 'female' | 'all'
        event_filter (str)    — 'all' | 'has_events' | 'no_events' |
                                 'due_overdue' | 'overdue'
        study_filter (str)    — Study.id or 'all'
        procedure_id (str)    — AnimalProcedure.id or 'all'
        tag_id (str)          — AnimalTag.id or 'all'
        event_tag_id (str)    — AnimalEventTag.id or 'all'
        search_query (str)    — substring match on custom_id
        species_id (int)      — -1 means no species filter
    """
    today = date.today()

    stmt = select(Animal).options(
        joinedload(Animal.species),
        joinedload(Animal.cage),
        selectinload(Animal.events),
        selectinload(Animal.studies),
    ).where(Animal.custom_id.is_not(None))

    species_id = filters.get('species_id', -1)
    if species_id != -1:
        stmt = stmt.where(Animal.species_id == species_id)

    search_query = filters.get('search_query', '')
    if search_query:
        stmt = stmt.where(Animal.custom_id.ilike(f'%{search_query}%'))

    status_filter = filters.get('status_filter', 'active')
    if status_filter == 'active':
        stmt = stmt.where(Animal.terminated == False)  # noqa: E712
    elif status_filter == 'terminated':
        stmt = stmt.where(Animal.terminated == True)  # noqa: E712

    sex_filter = filters.get('sex_filter', 'all')
    if sex_filter in ('male', 'female'):
        stmt = stmt.where(Animal.sex == sex_filter)

    study_filter = filters.get('study_filter', 'all')
    if study_filter != 'all':
        stmt = stmt.where(Animal.studies.any(Study.id == int(study_filter)))

    procedure_id = filters.get('procedure_id', 'all')
    if procedure_id != 'all':
        proc_ids = AnimalProcedure.descendant_ids(session, int(procedure_id))
        stmt = stmt.where(
            Animal.events.any(AnimalEvent.procedure_id.in_(proc_ids))
        )

    tag_id = filters.get('tag_id', 'all')
    if tag_id != 'all':
        tag_ids = AnimalTag.descendant_ids(session, int(tag_id))
        stmt = stmt.where(Animal.tags.any(AnimalTag.id.in_(tag_ids)))

    event_tag_id = filters.get('event_tag_id', 'all')
    if event_tag_id != 'all':
        et_ids = AnimalEventTag.descendant_ids(session, int(event_tag_id))
        stmt = stmt.where(Animal.events.any(
            AnimalEvent.tags.any(AnimalEventTag.id.in_(et_ids))
        ))

    event_filter = filters.get('event_filter', 'all')
    if event_filter == 'has_events':
        stmt = stmt.where(Animal.events.any())
    elif event_filter == 'no_events':
        stmt = stmt.where(~Animal.events.any())
    elif event_filter == 'due_overdue':
        stmt = stmt.where(Animal.events.any(
            (AnimalEvent.scheduled_date <= today)
            & AnimalEvent.completion_date.is_(None)
        ))
    elif event_filter == 'overdue':
        stmt = stmt.where(Animal.events.any(
            (AnimalEvent.scheduled_date < today)
            & AnimalEvent.completion_date.is_(None)
        ))

    sort_by = filters.get('sort_by', 'id')
    sort_dir = filters.get('sort_dir', 'asc')

    if sort_by == 'event_date':
        last_event_subq = (
            select(
                AnimalEvent.animal_id.label('animal_id'),
                func.max(AnimalEvent.completion_date).label('last_event_date'),
            ).group_by(AnimalEvent.animal_id).subquery()
        )
        stmt = stmt.outerjoin(
            last_event_subq, last_event_subq.c.animal_id == Animal.id
        )
        col = last_event_subq.c.last_event_date
        order = col.desc().nullslast() if sort_dir == 'desc' else col.asc().nullsfirst()
    elif sort_by == 'age':
        col = Animal.dob
        # asc age = youngest first = newest dob = dob desc
        order = col.asc() if sort_dir == 'desc' else col.desc()
    else:  # 'id'
        col = Animal.custom_id
        order = col.desc() if sort_dir == 'desc' else col.asc()

    return session.scalars(stmt.order_by(order)).unique().all()


def get_animal_filter_options(session: Session) -> dict[str, list[Any]]:
    """Return lookup lists for the animal list filter UI."""
    return {
        'procedures': AnimalProcedure.get_ordered(session),
        'animal_tags': AnimalTag.get_ordered(session),
        'event_tags': AnimalEventTag.get_ordered(session),
        'studies': session.scalars(select(Study).order_by(Study.name)).all(),
    }
