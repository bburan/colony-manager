"""Declarative base, shared mixins, helper functions, and association tables.

Every other model module imports from here.  Nothing in this file
imports from other model modules, so there are no circular dependencies.
"""
import re

from sqlalchemy import (
    Column, ForeignKey, Index, Integer, MetaData, String, Table,
    UniqueConstraint, orm,
)
from sqlalchemy.orm import backref, declarative_base, declared_attr, relationship


# Sentinel for cache-miss checks on optional cached attributes.
# ``None`` is a valid cached value (no baseline), so it can't mean "unset".
_MISSING = object()


Base = declarative_base(
    metadata=MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    ),
)


# ---------------------------------------------------------------------------
# Association tables
# All are defined here so any model module can import the Table objects it
# needs without risking circular imports.
# ---------------------------------------------------------------------------

study_animals = Table(
    'study_animals', Base.metadata,
    Column('study_id',  Integer, ForeignKey('study.id'),  primary_key=True),
    Column('animal_id', Integer, ForeignKey('animal.id'), primary_key=True),
)

user_roles = Table(
    'user_roles', Base.metadata,
    Column('user_id', Integer, ForeignKey('user.id'),      primary_key=True),
    Column('role_id', Integer, ForeignKey('user_role.id'), primary_key=True),
)

animal_tags = Table(
    'animal_tags', Base.metadata,
    Column('animal_id', Integer, ForeignKey('animal.id'),    primary_key=True),
    Column('tag_id',    Integer, ForeignKey('animal_tag.id'), primary_key=True),
)

animal_event_tags = Table(
    'animal_event_tags', Base.metadata,
    Column('animal_event_id', Integer, ForeignKey('animal_event.id'),     primary_key=True),
    Column('tag_id',          Integer, ForeignKey('animal_event_tag.id'), primary_key=True),
)

ear_tags = Table(
    'ear_tags', Base.metadata,
    Column('ear_id', Integer, ForeignKey('ear.id'),     primary_key=True),
    Column('tag_id', Integer, ForeignKey('ear_tag.id'), primary_key=True),
)

data_candidate_animals = Table(
    'data_candidate_animals', Base.metadata,
    Column('data_id',   Integer, ForeignKey('data.id'),   primary_key=True),
    Column('animal_id', Integer, ForeignKey('animal.id'), primary_key=True),
)

data_candidate_ears = Table(
    'data_candidate_ears', Base.metadata,
    Column('data_id', Integer, ForeignKey('data.id'), primary_key=True),
    Column('ear_id',  Integer, ForeignKey('ear.id'),  primary_key=True),
)

animal_event_data_targets = Table(
    'animal_event_data_targets', Base.metadata,
    Column('animal_event_data_id', Integer, ForeignKey('animal_event_data.id'), primary_key=True),
    Column('animal_event_id',      Integer, ForeignKey('animal_event.id'),      primary_key=True),
)

confocal_image_data_targets = Table(
    'confocal_image_data_targets', Base.metadata,
    Column('confocal_image_data_id', Integer, ForeignKey('confocal_image_data.id'), primary_key=True),
    Column('confocal_image_id',      Integer, ForeignKey('confocal_image.id'),      primary_key=True),
)

animal_data_targets = Table(
    'animal_data_targets', Base.metadata,
    Column('animal_data_id', Integer, ForeignKey('animal_data.id'), primary_key=True),
    Column('animal_id',      Integer, ForeignKey('animal.id'),      primary_key=True),
)

ear_data_targets = Table(
    'ear_data_targets', Base.metadata,
    Column('ear_data_id', Integer, ForeignKey('ear_data.id'), primary_key=True),
    Column('ear_id',      Integer, ForeignKey('ear.id'),      primary_key=True),
)


# ---------------------------------------------------------------------------
# Abstract base model
# ---------------------------------------------------------------------------

class VersionedModel(Base):
    """Abstract base for all domain models."""
    __abstract__ = True

    @declared_attr
    def __tablename__(cls):
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', cls.__name__)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()


# ---------------------------------------------------------------------------
# Shared mixin
# ---------------------------------------------------------------------------

class NestedMixin:
    """Adds ``display_name``, ``get_ordered``, and ``descendant_ids`` to any
    self-referential model that has a ``parent_id`` and ``name``."""

    @property
    def display_name(self):
        if self.parent:
            return f'{self.parent.display_name} > {self.name}'
        return self.name

    @classmethod
    def get_ordered(cls, session):
        """Return all rows depth-first, children sorted by name within each level."""
        from sqlalchemy import select
        items = session.scalars(select(cls)).all()
        by_parent = {}
        for item in items:
            by_parent.setdefault(item.parent_id, []).append(item)
        for siblings in by_parent.values():
            siblings.sort(key=lambda x: x.name.lower())

        ordered = []

        def walk(parent_id):
            for child in by_parent.get(parent_id, []):
                ordered.append(child)
                walk(child.id)

        walk(None)
        return ordered

    @classmethod
    def descendant_ids(cls, session, root_id):
        """Return ``{root_id} ∪ every descendant id`` (inclusive, in-memory walk)."""
        from sqlalchemy import select
        rows = session.execute(select(cls.id, cls.parent_id)).all()
        children_of = {}
        for child_id, parent_id in rows:
            children_of.setdefault(parent_id, []).append(child_id)
        result = {root_id}
        stack = [root_id]
        while stack:
            current = stack.pop()
            for child_id in children_of.get(current, ()):
                if child_id not in result:
                    result.add(child_id)
                    stack.append(child_id)
        return result


# ---------------------------------------------------------------------------
# Side-normalization helpers (used by DataType.match_targets subclasses)
# ---------------------------------------------------------------------------

def _canonical_side(value):
    """Normalize a side string to ``'Left'``/``'Right'`` regardless of case.

    Returns ``None`` for falsy or unrecognized inputs.
    """
    if not value:
        return None
    lowered = str(value).strip().lower()
    if lowered in ('left', 'l'):
        return 'Left'
    if lowered in ('right', 'r'):
        return 'Right'
    return None


def _expand_sides(raw, count):
    """Normalize ``parsed['side']`` to a per-animal list of canonical sides.

    Accepts either a scalar (broadcast to every animal) or a list parallel
    to ``animal_id``. Returns ``None`` if the lengths don't line up.
    """
    if isinstance(raw, (list, tuple)):
        if len(raw) != count:
            return None
        return [_canonical_side(s) for s in raw]
    return [_canonical_side(raw)] * count
