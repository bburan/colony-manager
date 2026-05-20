from datetime import date, datetime, timedelta
import re
from statistics import mean

from sqlalchemy import (
    func, orm, UniqueConstraint, Index, MetaData, Table, Column, Integer, String,
    ForeignKey, Text, Boolean, Date, DateTime, Time, Float, JSON, and_, or_
)
from sqlalchemy.orm import (declared_attr, declarative_base, relationship,
                            backref, joinedload)

# Sentinel for cache-miss checks on optional cached attributes — ``None``
# is a valid cached value (no baseline), so we can't use it to mean "unset".
_MISSING = object()


Base = declarative_base(
    metadata=MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s"
        },
    ),
)


# --- Association Tables ---
study_animals = Table('study_animals', Base.metadata,
    Column('study_id', Integer, ForeignKey('study.id'), primary_key=True),
    Column('animal_id', Integer, ForeignKey('animal.id'), primary_key=True)
)

user_roles = Table('user_roles', Base.metadata,
    Column('user_id', Integer, ForeignKey('user.id'), primary_key=True),
    Column('role_id', Integer, ForeignKey('user_role.id'), primary_key=True)
)

animal_tags = Table('animal_tags', Base.metadata,
    Column('animal_id', Integer, ForeignKey('animal.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('animal_tag.id'), primary_key=True)
)

animal_event_tags = Table('animal_event_tags', Base.metadata,
    Column('animal_event_id', Integer, ForeignKey('animal_event.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('animal_event_tag.id'), primary_key=True)
)

ear_tags = Table('ear_tags', Base.metadata,
    Column('ear_id', Integer, ForeignKey('ear.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('ear_tag.id'), primary_key=True)
)

data_candidate_animals = Table('data_candidate_animals', Base.metadata,
    Column('data_id', Integer, ForeignKey('data.id'), primary_key=True),
    Column('animal_id', Integer, ForeignKey('animal.id'), primary_key=True)
)

data_candidate_ears = Table('data_candidate_ears', Base.metadata,
    Column('data_id', Integer, ForeignKey('data.id'), primary_key=True),
    Column('ear_id', Integer, ForeignKey('ear.id'), primary_key=True)
)

animal_event_data_targets = Table('animal_event_data_targets', Base.metadata,
    Column('animal_event_data_id', Integer, ForeignKey('animal_event_data.id'), primary_key=True),
    Column('animal_event_id', Integer, ForeignKey('animal_event.id'), primary_key=True)
)

confocal_image_data_targets = Table('confocal_image_data_targets', Base.metadata,
    Column('confocal_image_data_id', Integer, ForeignKey('confocal_image_data.id'), primary_key=True),
    Column('confocal_image_id', Integer, ForeignKey('confocal_image.id'), primary_key=True)
)

animal_data_targets = Table('animal_data_targets', Base.metadata,
    Column('animal_data_id', Integer, ForeignKey('animal_data.id'), primary_key=True),
    Column('animal_id', Integer, ForeignKey('animal.id'), primary_key=True)
)

ear_data_targets = Table('ear_data_targets', Base.metadata,
    Column('ear_data_id', Integer, ForeignKey('ear_data.id'), primary_key=True),
    Column('ear_id', Integer, ForeignKey('ear.id'), primary_key=True)
)


class VersionedModel(Base):
    """Base model that automatically adds created and updated timestamps."""
    __abstract__ = True
    __versioned__ = {}

    @declared_attr
    def __tablename__(cls):
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', cls.__name__)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

class Species(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    animals = relationship('Animal', backref='species', lazy=True)
    cages = relationship('Cage', backref='species', lazy=True)

    # Dashboard aggregates that previously lived here as classmethods
    # have moved to ``colony_manager_gui.queries`` — they're presentation
    # helpers, not domain logic, and they took an implicit dependency on
    # a Flask-SQLAlchemy session being bound to the Base.

class Source(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    animals = relationship('Animal', backref='source', lazy=True)

class NestedMixin:

    @property
    def display_name(self):
        if self.parent:
            return f'{self.parent.display_name} > {self.name}'
        return self.name

    @classmethod
    def get_ordered(cls, session):
        """Return all rows depth-first, with each parent's children sorted by name.

        Takes an explicit ``session`` so this works from both Flask
        routes (passing ``db.session``) and standalone scripts/tests
        (passing a session built from ``colony_manager.db``).
        """
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
        """Return ``{root_id} | every descendant id under it`` (inclusive).

        Walks the whole table once and traverses in-memory rather than
        issuing N recursive queries.
        """
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

class AnimalProcedure(VersionedModel, NestedMixin):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    parent_id = Column(Integer, ForeignKey('animal_procedure.id'), nullable=True)

    __table_args__ = (
        UniqueConstraint('parent_id', 'name', name='uq_animal_procedure_parent_id_name'),
        Index(
            'uq_animal_procedure_name_root',
            'name',
            unique=True,
            postgresql_where=Column('parent_id').is_(None),
            sqlite_where=Column('parent_id').is_(None),
        ),
    )

    subcategories = relationship(
        'AnimalProcedure',
        backref=backref('parent', remote_side=[id]),
    )

    events = relationship('AnimalEvent', backref='procedure', lazy=True)


def _canonical_side(value):
    """Normalize a side string to ``'Left'``/``'Right'`` regardless of case.

    Returns ``None`` for falsy or unrecognized inputs so callers can use a
    simple equality comparison against the column.
    """
    if not value:
        return None
    lowered = str(value).strip().lower()
    if lowered in ('left', 'l'):
        return 'Left'
    if lowered in ('right', 'r'):
        return 'Right'
    return None


class DataType(VersionedModel):
    """Polymorphic base. Subclasses target specific model types."""
    __tablename__ = 'data_type'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    target_type = Column(String(50), nullable=False)
    is_folder = Column(Boolean, nullable=False, default=False, server_default='false')
    auto_create = Column(Boolean, nullable=False, default=False, server_default='false')
    description_class = Column(String(200), nullable=True)

    locations = relationship('DataLocation', backref='datatype', cascade="all, delete-orphan")
    data_files = relationship('Data', backref='datatype', cascade="all, delete-orphan")

    __mapper_args__ = {
        'polymorphic_on': target_type,
        'polymorphic_identity': 'datatype',
    }

    TARGET_LABEL = 'Generic'

    def get_description(self):
        """Get the associated DataTypeDescription class.

        Returns
        -------
        instance of DataTypeDescription
        """
        if not self.description_class:
            return {}
        from colony_manager.datatypes import load_description_class
        return load_description_class(self.description_class)

    def get_description_callbacks(self):
        """Introspect callbacks from the associated DataTypeDescription class.

        Returns
        -------
        dict
            ``{friendly_name: {'type': str, 'method_name': str}}``, or
            an empty dict if no description class is configured.
        """
        try:
            return self.get_description().get_callbacks()
        except Exception:
            return {}

    def match_targets(self, session, parsed):
        """Resolve a parsed metadata dict to a list of target model instances.

        Subclasses override. Return an empty list if nothing matched.
        Takes an explicit ``session`` so polymorphic dispatch works
        from both Flask routes (passing ``db.session``) and standalone
        scripts/tests.
        """
        return []


class AnimalEventDataType(DataType):
    __tablename__ = 'animal_event_data_type'

    id = Column(Integer, ForeignKey('data_type.id'), primary_key=True)
    default_procedure_id = Column(Integer, ForeignKey('animal_procedure.id'), nullable=True)
    default_procedure_target_id = Column(Integer, ForeignKey('animal_procedure_target.id'), nullable=True)

    default_procedure = relationship('AnimalProcedure', lazy=True)
    default_procedure_target = relationship('AnimalProcedureTarget', lazy=True)

    __mapper_args__ = {'polymorphic_identity': 'animal_event'}

    TARGET_LABEL = 'Animal Event'

    def match_targets(self, session, parsed):
        from sqlalchemy import select

        animal_ids = parsed.get('animal_id') or []
        if isinstance(animal_ids, str):
            animal_ids = [animal_ids]
        target_date = parsed.get('date')
        if not animal_ids or not target_date or not self.default_procedure_id:
            return []
        side = _canonical_side(parsed.get('side'))
        events = []
        for aid in animal_ids:
            animal = session.scalars(
                select(Animal).where(Animal.custom_id == aid)
            ).first()
            if not animal:
                continue
            stmt = select(AnimalEvent).where(
                AnimalEvent.animal_id == animal.id,
                AnimalEvent.procedure_id == self.default_procedure_id,
                or_(
                    AnimalEvent.scheduled_date == target_date,
                    AnimalEvent.completion_date == target_date,
                ),
            )
            if side is not None:
                stmt = stmt.where(AnimalEvent.side == side)
            event = session.scalars(stmt).first()
            if event:
                events.append(event)
        return events


class ConfocalImageDataType(DataType):
    __tablename__ = 'confocal_image_data_type'

    id = Column(Integer, ForeignKey('data_type.id'), primary_key=True)

    __mapper_args__ = {'polymorphic_identity': 'confocal_image'}

    TARGET_LABEL = 'Confocal Image'

    def match_targets(self, session, parsed):
        from sqlalchemy import select

        animal_ids = parsed.get('animal_id') or []
        if isinstance(animal_ids, str):
            animal_ids = [animal_ids]
        ear = _canonical_side(parsed.get('ear'))
        frequency = parsed.get('frequency')
        image_type_name = parsed.get('image_type')
        if not (animal_ids and ear and frequency is not None and image_type_name):
            return []
        image_type = session.scalars(
            select(ConfocalImageType).where(ConfocalImageType.name == image_type_name)
        ).first()
        if not image_type:
            return []
        images = []
        for aid in animal_ids:
            animal = session.scalars(
                select(Animal).where(Animal.custom_id == aid)
            ).first()
            if not animal:
                continue
            image = session.scalars(
                select(ConfocalImage).join(Ear).where(
                    Ear.animal_id == animal.id,
                    Ear.side == ear,
                    func.abs(ConfocalImage.frequency - float(frequency)) < 1e-6,
                    ConfocalImage.image_type_id == image_type.id,
                )
            ).first()
            if image:
                images.append(image)
        return images


class AnimalDataType(DataType):
    __tablename__ = 'animal_data_type'

    id = Column(Integer, ForeignKey('data_type.id'), primary_key=True)

    __mapper_args__ = {'polymorphic_identity': 'animal'}

    TARGET_LABEL = 'Animal'

    def match_targets(self, session, parsed):
        from sqlalchemy import select

        animal_ids = parsed.get('animal_id') or []
        if isinstance(animal_ids, str):
            animal_ids = [animal_ids]
        animals = []
        for aid in animal_ids:
            animal = session.scalars(
                select(Animal).where(Animal.custom_id == aid)
            ).first()
            if animal:
                animals.append(animal)
        return animals


class EarDataType(DataType):
    __tablename__ = 'ear_data_type'

    id = Column(Integer, ForeignKey('data_type.id'), primary_key=True)

    __mapper_args__ = {'polymorphic_identity': 'ear'}

    TARGET_LABEL = 'Ear'

    def match_targets(self, session, parsed):
        from sqlalchemy import select

        animal_ids = parsed.get('animal_id') or []
        if isinstance(animal_ids, str):
            animal_ids = [animal_ids]
        sides = _expand_sides(parsed.get('side'), len(animal_ids))
        if sides is None:
            return []
        ears = []
        for aid, side in zip(animal_ids, sides):
            if side not in ('Left', 'Right'):
                continue
            animal = session.scalars(
                select(Animal).where(Animal.custom_id == aid)
            ).first()
            if not animal:
                continue
            ear = session.scalars(
                select(Ear).where(Ear.animal_id == animal.id, Ear.side == side)
            ).first()
            if ear:
                ears.append(ear)
        return ears


def _expand_sides(raw, count):
    """Normalize ``parsed['side']`` to a per-animal list of canonical sides.

    Accepts either a scalar (broadcast to every animal) or a list parallel
    to ``animal_id``. Returns ``None`` if the lengths don't line up so
    callers can short-circuit.
    """
    if isinstance(raw, (list, tuple)):
        if len(raw) != count:
            return None
        return [_canonical_side(s) for s in raw]
    return [_canonical_side(raw)] * count


DATATYPE_SUBCLASSES = {
    'animal_event': AnimalEventDataType,
    'confocal_image': ConfocalImageDataType,
    'animal': AnimalDataType,
    'ear': EarDataType,
}




class DataLocation(VersionedModel):
    id = Column(Integer, primary_key=True)
    datatype_id = Column(Integer, ForeignKey('data_type.id'), nullable=False)
    base_path = Column(String(1024), nullable=False)
    data_files = relationship('Data', backref='location', cascade="all, delete-orphan")


class Data(VersionedModel):
    """Polymorphic base for files discovered by the sync script."""
    __tablename__ = 'data'

    id = Column(Integer, primary_key=True)
    datatype_id = Column(Integer, ForeignKey('data_type.id'), nullable=False)
    location_id = Column(Integer, ForeignKey('data_location.id'), nullable=False)
    target_type = Column(String(50), nullable=False)
    relative_path = Column(String(1024), nullable=False)
    file_hash = Column(String(64), nullable=True)
    name = Column(String(255), nullable=False)
    date = Column(Date, nullable=True)
    status = Column(String(50), nullable=False, default='unreviewed')
    notes = Column(Text, nullable=True)
    mtime = Column(DateTime, nullable=True)
    ctime = Column(DateTime, nullable=True)
    discovered_at = Column(DateTime, nullable=True)

    # Cached output of the description class's ``parse()`` call. Populated
    # by sync / rematch jobs so list views don't have to re-run the parser
    # to surface frequency / image_type / side metadata. Dates are stored
    # as ISO strings (see ``_to_json_safe`` in services/data_linking).
    parsed_metadata = Column(JSON, nullable=True)

    candidate_animals = relationship(
        'Animal',
        secondary=data_candidate_animals,
        backref='candidate_data_files',
    )

    candidate_ears = relationship(
        'Ear',
        secondary=data_candidate_ears,
        backref='candidate_data_files',
    )

    __table_args__ = (
        UniqueConstraint('location_id', 'relative_path'),
    )

    __mapper_args__ = {
        'polymorphic_on': target_type,
        'polymorphic_identity': 'data',
    }

    @property
    def targets(self):
        """List of resolved target instances. Overridden by subclasses."""
        return []

    @property
    def is_unmatched(self):
        return len(self.targets) == 0


class AnimalEventData(Data):
    __tablename__ = 'animal_event_data'

    id = Column(Integer, ForeignKey('data.id'), primary_key=True)
    events = relationship(
        'AnimalEvent',
        secondary=animal_event_data_targets,
        backref='data_files',
    )

    __mapper_args__ = {'polymorphic_identity': 'animal_event'}

    @property
    def targets(self):
        return list(self.events)


class ConfocalImageData(Data):
    __tablename__ = 'confocal_image_data'

    id = Column(Integer, ForeignKey('data.id'), primary_key=True)
    confocal_images = relationship(
        'ConfocalImage',
        secondary=confocal_image_data_targets,
        backref='data_files',
    )

    __mapper_args__ = {'polymorphic_identity': 'confocal_image'}

    @property
    def targets(self):
        return list(self.confocal_images)


class AnimalData(Data):
    __tablename__ = 'animal_data'

    id = Column(Integer, ForeignKey('data.id'), primary_key=True)
    animals = relationship(
        'Animal',
        secondary=animal_data_targets,
        backref='data_files',
    )

    __mapper_args__ = {'polymorphic_identity': 'animal'}

    @property
    def targets(self):
        return list(self.animals)


class EarData(Data):
    __tablename__ = 'ear_data'

    id = Column(Integer, ForeignKey('data.id'), primary_key=True)
    ears = relationship(
        'Ear',
        secondary=ear_data_targets,
        backref='data_files',
    )

    __mapper_args__ = {'polymorphic_identity': 'ear'}

    @property
    def targets(self):
        return list(self.ears)


DATA_SUBCLASSES = {
    'animal_event': AnimalEventData,
    'confocal_image': ConfocalImageData,
    'animal': AnimalData,
    'ear': EarData,
}


class AnimalProcedureTarget(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    requires_side = Column(Boolean, nullable=False, default=False, server_default='false')
    events = relationship('AnimalEvent', backref='procedure_target', lazy=True)

class TerminationReason(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    animals = relationship('Animal', backref='termination_reason', lazy=True)

class Cage(VersionedModel):
    id = Column(Integer, primary_key=True)
    custom_id = Column(String(50), unique=True, nullable=False)
    notes = Column(Text, nullable=True)
    species_id = Column(Integer, ForeignKey('species.id', use_alter=True), nullable=False)
    animals = relationship('Animal', backref='cage', cascade="all, delete-orphan")

    # ``animals`` defaults to ``lazy='select'``: first access materializes
    # the full collection in one query. List views should use
    # ``selectinload(Cage.animals)`` (optionally chained to ``Animal.source``)
    # at query time to avoid the per-row fan-out.

    @property
    def animals_count(self):
        return len(self.animals)

    @property
    def active_animals_count(self):
        return sum(1 for a in self.animals if a.termination_date is None)

    @property
    def is_active(self):
        return self.active_animals_count > 0

    @property
    def sex(self):
        return sorted({a.sex for a in self.animals})

    @property
    def sex_symbol(self):
        result = sorted({a.sex_symbol for a in self.animals})
        if len(result) == 2:
            return '⚥'
        elif len(result) == 1:
            return result[0]
        return ''

    def age_display(self, unit='day'):
        ages = sorted({getattr(a, f'age_in_{unit}s') for a in self.animals})
        if len(ages) == 0:
            return 'N/A'
        elif len(ages) == 1:
            return f'{ages[0]:.1f} {unit}s'
        return f'{ages[0]:.1f} to {ages[-1]:.1f} {unit}s'

    @property
    def source_display(self):
        sources = {a.source_display for a in self.animals}
        if len(sources) == 0:
            return 'N/A'
        return ', '.join(sorted(sources))

class AnimalTag(VersionedModel, NestedMixin):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    parent_id = Column(Integer, ForeignKey('animal_tag.id'), nullable=True)
    subtags = relationship(
        'AnimalTag',
        backref=backref('parent', remote_side=[id]),
    )

class Animal(VersionedModel):
    id = Column(Integer, primary_key=True)
    custom_id = Column(String(100), unique=True, nullable=True)
    cage_id = Column(Integer, ForeignKey('cage.id', use_alter=True), nullable=False)
    species_id = Column(Integer, ForeignKey('species.id', use_alter=True), nullable=False)
    sex = Column(String(10), nullable=False)
    dob = Column(Date, nullable=False)
    source_id = Column(Integer, ForeignKey('source.id', use_alter=True), nullable=True)
    breeding_pair_id = Column(Integer, ForeignKey('breeding_pair.id'), nullable=True)
    notes = Column(Text, nullable=True)
    termination_date = Column(Date, nullable=True)
    termination_reason_id = Column(Integer, ForeignKey('termination_reason.id', use_alter=True), nullable=True)
    events = relationship('AnimalEvent', backref='animal', cascade="all, delete-orphan")
    ears = relationship('Ear', backref='animal', cascade="all, delete-orphan")
    breeding_pair = relationship('BreedingPair', back_populates='offspring', foreign_keys=[breeding_pair_id])
    weights = relationship('WeightLog', backref='animal', cascade="all, delete-orphan")
    feedings = relationship('FeedLog', backref='animal', cascade="all, delete-orphan")
    # ``order_by`` here keeps tag rendering stable across pages — the
    # template can iterate ``animal.tags`` directly without sorting on
    # the Jinja side. Same pattern on AnimalEvent.tags and Ear.tags.
    tags = relationship('AnimalTag', secondary=animal_tags, backref='animals',
                        order_by='AnimalTag.name')

    @property
    def events_by_date(self):
        groups = {}
        for e in self.events:
            groups.setdefault(e.date, []).append(e)
        return dict((d, sorted(groups[d], key=lambda x: x.procedure.name)) for d in sorted(groups.keys()))

    # These properties read directly from the now-lazy='select' events
    # relationship. List views that render N animals should chain
    # ``selectinload(Animal.events)`` on the outer query to keep this
    # from fanning out into N queries.

    @property
    def has_events(self):
        return bool(self.events)

    @property
    def events_count(self):
        return len(self.events)

    @property
    def studies_count(self):
        return len(self.studies)

    @property
    def event_due(self):
        return any(e.scheduled_date == date.today() and e.completion_date is None for e in self.events)

    @property
    def event_overdue(self):
        return any(e.scheduled_date < date.today() and e.completion_date is None for e in self.events)

    @property
    def last_event_date(self):
        completion_dates = [
            e.completion_date for e in self.events
            if e.status == 'completed' and e.completion_date is not None
        ]
        return max(completion_dates) if completion_dates else date.min

    @property
    def age_in_days(self):
        return (date.today() - self.dob).days

    @property
    def age_in_weeks(self):
        return self.age_in_days / 7

    @property
    def age_in_months(self):
        return self.age_in_days / 30

    @property
    def is_active(self):
        return self.termination_date is None

    @property
    def sex_symbol(self):
        if self.sex == 'female':
            return '♀'
        elif self.sex == 'male':
            return '♂'
        else:
            return '?'

    @property
    def source_display(self):
        # First check if it was bred in-house
        if self.breeding_pair:
            return self.breeding_pair.custom_id
        # Fall back to an external source, or N/A
        return 'N/A' if self.source is None else self.source.name

    @property
    def scheduled_events(self):
        scheduled = [e for e in self.events if e.completion_date is None]
        return sorted(scheduled, key=lambda x: x.scheduled_date)

    @property
    def completed_events(self):
        completed = [e for e in self.events if e.completion_date is not None]
        return sorted(completed, key=lambda x: x.completion_date)

    def terminate(self, termination_date, termination_reason=None,
                  ears_extracted=None):
        """Mark this animal as terminated and optionally extract ears for histology.

        Parameters
        ----------
        termination_date : date
            The date the animal was terminated.
        termination_reason : TerminationReason or None, optional
            The reason for termination.
        ears_extracted : str or None, optional
            Which ears to extract for histology. Accepted values are
            ``'Left'``, ``'Right'``, ``'Both'``, or ``None`` (no extraction).

        Returns
        -------
        list of Ear
            The newly created :class:`Ear` instances (may be empty).

        Raises
        ------
        ValueError
            If the animal is already terminated or *ears_extracted* is not a
            recognised value.
        """
        if self.termination_date is not None:
            raise ValueError(
                f'{self.display_id} is already terminated '
                f'(on {self.termination_date}).'
            )

        valid_ear_choices = (None, 'Left', 'Right', 'Both')
        if ears_extracted not in valid_ear_choices:
            raise ValueError(
                f'ears_extracted must be one of {valid_ear_choices}, '
                f'got {ears_extracted!r}.'
            )

        self.termination_date = termination_date
        self.termination_reason = termination_reason

        new_ears = []
        if ears_extracted in ('Left', 'Both'):
            new_ears.append(Ear(animal_id=self.id, side='Left'))
        if ears_extracted in ('Right', 'Both'):
            new_ears.append(Ear(animal_id=self.id, side='Right'))
        return new_ears

    def age_display(self, unit='day'):
        age = getattr(self, f'age_in_{unit}s')
        return f'{age:.1f} {unit}s'

    @property
    def display_id(self):
        if self.custom_id:
            return self.custom_id
        else:
            return f'Animal from {self.cage.custom_id}'

    @staticmethod
    def _baseline_from_weights(weights_desc):
        """Compute baseline from an already-ordered (date desc) WeightLog list.

        Shared by the per-instance property and the bulk path used by
        :meth:`get_daily_logs` so the same algorithm runs in both places.
        """
        baselines = []
        for w in weights_desc:
            if w.weight is None:
                continue
            if w.baseline:
                baselines.append(w)
            elif baselines:
                break
        if baselines:
            return mean(w.weight for w in baselines)
        return None

    @property
    def baseline_weight(self):
        '''
        Get the most recent baseline weight as the average of all weights consecutively marked as baseline.

        Honors a request-scoped cache populated by :meth:`get_daily_logs`
        so the dashboard's weight table doesn't issue one extra query per
        ``animal.baseline_weight`` access (and the template reads it twice
        per cell).
        '''
        cached = getattr(self, '_baseline_weight_cached', _MISSING)
        if cached is not _MISSING:
            return cached
        weights = sorted(
            (w for w in self.weights if w.weight is not None),
            key=lambda w: w.date,
            reverse=True,
        )
        return self._baseline_from_weights(weights)

    def weight_feed_history(self):
        # When current_baseline is None, we are in accumulation mode. When we get to the first non-baseline weight, then we calculate the mean baseline weight and set that to current_baselinmean baseline weight and set that to current_baseline
        baselines = []
        current_baseline = None
        history = {}
        for w in sorted(self.weights, key=lambda w: w.date):
            if w.weight is not None:
                if w.baseline:
                    current_baseline = None
                    baselines.append(w)
                    baseline_pct = None
                else:
                    if current_baseline is None and len(baselines) > 0:
                        current_baseline = mean(w.weight for w in baselines)
                        baselines = []
                    if current_baseline is not None:
                        baseline_pct = int(round((w.weight / current_baseline) * 100))
                    else:
                        baseline_pct = None
            else:
                baseline_pct = None
            history[w.date] = {
                'weight': w.weight,
                'baseline_pct': baseline_pct,
                'notes': w.notes,
                'feed': {},
                'total_feed': 0,
                'baseline': w.baseline
            }

        # ``self.feedings`` is now lazy='select'; the joinedload that
        # used to live on the per-call ``.options(...)`` chain is no
        # longer applicable. Each ``f.feed_type`` access lazy-loads,
        # but the typical view (the per-animal weight/feed accordion)
        # has at most a few dozen entries — fine.
        for f in self.feedings:
            day = history.setdefault(f.date, {'weight': None, 'note': '', 'feed': {}, 'total_feed': 0, 'baseline_pct': None})
            day['feed'][f.feed_id] = f.quantity
            day['total_feed'] += (f.quantity * f.feed_type.weight)

        return dict(sorted(history.items(), key=lambda item: item[0], reverse=True))

    @classmethod
    def _get_recent_feeds(cls, days=7):
        today = date.today()


    @classmethod
    def get_daily_logs(cls, session, reference_date=None, before=0, after=0, species=None):
        """Return animals paired with their weight and feed logs over a date window.

        Takes an explicit ``session`` so this works from both Flask
        routes (passing ``db.session``) and standalone scripts/tests
        (passing a session built from ``colony_manager.db``).
        """
        from sqlalchemy import select

        if reference_date is None:
            reference_date = date.today()

        start_date = reference_date - timedelta(days=before)
        end_date = reference_date + timedelta(days=after)
        total_days = (end_date - start_date).days + 1

        weight_stmt = select(cls, WeightLog).join(WeightLog).where(
            WeightLog.date >= start_date,
            WeightLog.date <= end_date,
        )
        # ``feed_log.feed_type.weight`` is read once per log when computing
        # ``total_feed`` below — joinedload it here so we don't fan out into
        # one SELECT per feed log.
        feed_stmt = (
            select(cls, FeedLog)
            .join(FeedLog)
            .options(joinedload(FeedLog.feed_type))
            .where(FeedLog.date >= start_date, FeedLog.date <= end_date)
        )

        if species is not None:
            weight_stmt = weight_stmt.where(Animal.species == species)
            feed_stmt = feed_stmt.where(Animal.species == species)

        weight_rows = session.execute(weight_stmt).all()
        feed_rows = session.execute(feed_stmt).all()

        if weight_rows:
            w_animals, weights = zip(*weight_rows)
        else:
            w_animals, weights = [], []

        if feed_rows:
            f_animals, feeds = zip(*feed_rows)
        else:
            f_animals, feeds = [], []

        animals = sorted(set(w_animals) | set(f_animals), key=lambda x: x.display_id)

        # Bulk-load every WeightLog for these animals (ordered date desc)
        # and stash the computed baseline on each instance. The dashboard
        # weight template reads ``animal.baseline_weight`` twice per cell;
        # without this each access would re-iterate ``self.weights`` and
        # recompute the same answer.
        if animals:
            animal_ids = [a.id for a in animals]
            by_animal = {a.id: [] for a in animals}
            baseline_rows = session.scalars(
                select(WeightLog)
                .where(
                    WeightLog.animal_id.in_(animal_ids),
                    WeightLog.weight.is_not(None),
                )
                .order_by(WeightLog.animal_id, WeightLog.date.desc())
            ).all()
            for w in baseline_rows:
                by_animal[w.animal_id].append(w)
            for a in animals:
                a._baseline_weight_cached = cls._baseline_from_weights(
                    by_animal.get(a.id, [])
                )

        results = {a: [{'date': start_date + timedelta(days=i), 'weight': None, 'feeds': [], 'total_feed': 0} \
                       for i in range(total_days)] for a in animals}

        for weight in weights:
            ix = (weight.date - start_date).days
            if 0 <= ix < total_days:
                results[weight.animal][ix]['weight'] = weight

        for feed_log in feeds:
            ix = (feed_log.date - start_date).days
            if 0 <= ix < total_days:
                results[feed_log.animal][ix]['total_feed'] += (feed_log.feed_type.weight * feed_log.quantity)
                results[feed_log.animal][ix]['feeds'].append(feed_log)
                results[feed_log.animal][ix][feed_log.feed_type.name] = feed_log.quantity

        return results

class BreedingPair(VersionedModel):
    id = Column(Integer, primary_key=True)
    custom_id = Column(String(50), unique=True, nullable=False)
    start_date = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)
    male_animal_id = Column(Integer, ForeignKey('animal.id', use_alter=True), nullable=False)
    # ``backref='breeding_pair_male'`` exposes ``animal.breeding_pair_male`` as
    # the BreedingPair where this animal sits in the male slot (None if not
    # used as a sire). Same for ``breeding_pair_female`` on the other side.
    # ``routes/animals.delete_animal`` reads these to refuse deletion of
    # animals that are part of a breeding pair.
    male = relationship('Animal', foreign_keys=[male_animal_id],
                        backref='breeding_pair_male')
    female_animal_id = Column(Integer, ForeignKey('animal.id', use_alter=True), nullable=False)
    female = relationship('Animal', foreign_keys=[female_animal_id],
                          backref='breeding_pair_female')
    is_active = Column(Boolean, default=True, nullable=False)
    litters = relationship('Litter', backref='breeding_pair', cascade="all, delete-orphan")
    offspring = relationship('Animal', back_populates='breeding_pair', foreign_keys='Animal.breeding_pair_id')

class Litter(VersionedModel):
    id = Column(Integer, primary_key=True)
    breeding_pair_id = Column(Integer, ForeignKey('breeding_pair.id', use_alter=True), nullable=False)
    dob = Column(Date, nullable=False)
    pup_count = Column(Integer, nullable=False)
    wean_date = Column(Date, nullable=True)

    @property
    def age_in_days(self):
        return (date.today() - self.dob).days

class Feed(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    weight = Column(Float, nullable=False)

class WeightLog(VersionedModel):
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animal.id'), nullable=False)
    date = Column(Date)
    weight = Column(Float, nullable=True)
    notes = Column(Text)
    baseline = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint('animal_id', 'date'),
    )

class FeedLog(VersionedModel):
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animal.id'), nullable=False)
    feed_id = Column(Integer, ForeignKey('feed.id'), nullable=False)
    date = Column(Date)
    quantity = Column(Integer, nullable=False)  # Number of pellets
    feed_type = relationship('Feed')

    @property
    def total_grams(self):
        return self.amount * self.feed_type.weight

    __table_args__ = (
        UniqueConstraint('animal_id', 'feed_id', 'date'),
    )

class AnimalEventTag(VersionedModel, NestedMixin):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    parent_id = Column(Integer, ForeignKey('animal_event_tag.id'), nullable=True)
    subtags = relationship(
        'AnimalEventTag',
        backref=backref('parent', remote_side=[id]),
    )

class AnimalEvent(VersionedModel):
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animal.id', use_alter=True), nullable=False)
    procedure_id = Column(Integer, ForeignKey('animal_procedure.id', use_alter=True), nullable=False)
    procedure_target_id = Column(Integer, ForeignKey('animal_procedure_target.id', use_alter=True), nullable=False)
    side = Column(String(10), nullable=True)
    scheduled_date = Column(Date, nullable=False)
    completion_date = Column(Date, nullable=True)
    # Optional time-of-day for completion. Set automatically when a dose
    # is logged via the dosage calculator so anesthesia records carry the
    # injection clock time; older event paths leave this NULL.
    completion_time = Column(Time, nullable=True)
    notes = Column(Text, nullable=True)
    tags = relationship('AnimalEventTag', secondary=animal_event_tags,
                        backref='animal_procedure',
                        order_by='AnimalEventTag.name')

    @property
    def status(self):
        if self.completion_date is not None: return 'complete'
        if self.scheduled_date < date.today(): return 'overdue'
        if self.scheduled_date == date.today(): return 'due'
        return ''

    @property
    def date(self):
        return self.scheduled_date if self.completion_date is None else self.completion_date

    @property
    def sorted_data_files(self):
        return sorted(self.data_files, key=lambda f: f.name)

class DosageProtocol(VersionedModel):
    """A reusable drug dosage protocol attached to a procedure.

    The set of drugs lives in :class:`DosageProtocolDrug`; each drug carries
    its target dose (mg/kg) and stock concentration (mg/mL) so the animal
    page calculator can derive an injection volume from the animal's weight.
    """
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    procedure_id = Column(Integer, ForeignKey('animal_procedure.id', use_alter=True), nullable=False)
    procedure_target_id = Column(Integer, ForeignKey('animal_procedure_target.id', use_alter=True), nullable=False)
    notes = Column(Text, nullable=True)

    procedure = relationship('AnimalProcedure', lazy=True)
    procedure_target = relationship('AnimalProcedureTarget', lazy=True)
    drugs = relationship(
        'DosageProtocolDrug',
        backref='protocol',
        cascade='all, delete-orphan',
        order_by='DosageProtocolDrug.position',
    )


class DosageProtocolDrug(VersionedModel):
    id = Column(Integer, primary_key=True)
    protocol_id = Column(Integer, ForeignKey('dosage_protocol.id'), nullable=False)
    name = Column(String(100), nullable=False)
    dose_mg_per_kg = Column(Float, nullable=False)
    concentration_mg_per_ml = Column(Float, nullable=False)
    position = Column(Integer, nullable=False, default=0)


class ImmunolabelingPanel(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    
    ears = relationship('Ear', backref='panel', lazy=True)

class Ear(VersionedModel):
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animal.id', use_alter=True), nullable=False)
    side = Column(String(5), nullable=False)
    cryoprotection_date = Column(Date, nullable=True)
    dissection_date = Column(Date, nullable=True)
    immunolabel_date = Column(Date, nullable=True)
    panel_id = Column(Integer, ForeignKey('immunolabeling_panel.id', use_alter=True), nullable=True)
    notes = Column(Text, nullable=True)
    confocal_images = relationship('ConfocalImage', backref='ear', lazy=True)
    tags = relationship('EarTag', secondary=ear_tags, backref='ears',
                        order_by='EarTag.name')

    @property
    def full_display(self):
        return f'{self.animal.custom_id} {self.side}'

    @property
    def events(self):
        """AnimalEvents tagged with this ear's side."""
        return [e for e in self.animal.events if e.side == self.side]

    @property
    def events_by_date(self):
        groups = {}
        for e in self.events:
            groups.setdefault(e.date, []).append(e)
        return dict(
            (d, sorted(groups[d], key=lambda x: x.procedure.name))
            for d in sorted(groups.keys())
        )

    def __eq__(self, other):
        if not isinstance(other, Ear): return NotImplemented
        return self.id == other.id

    def __lt__(self, other):
        if not isinstance(other, Ear): return NotImplemented
        return (self.animal.custom_id, self.side) < (other.animal.custom_id, other.side)

class EarTag(VersionedModel, NestedMixin):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    parent_id = Column(Integer, ForeignKey('ear_tag.id'), nullable=True)
    subtags = relationship(
        'EarTag',
        backref=backref('parent', remote_side=[id]),
    )

class ConfocalImageType(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    confocal_images = relationship('ConfocalImage', backref='image_type', lazy=True)

class ConfocalImage(VersionedModel):
    id = Column(Integer, primary_key=True)
    ear_id = Column(Integer, ForeignKey('ear.id', use_alter=True), nullable=False)
    frequency = Column(Float, nullable=False)
    image_type_id = Column(Integer, ForeignKey('confocal_image_type.id', use_alter=True), nullable=False)
    notes = Column(Text, nullable=True)
    status = Column(String(150), nullable=True)

    @property
    def full_display(self):
        return f'{self.ear.full_display} {self.image_type.name} {self.frequency}'

class Study(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    animals = relationship('Animal', secondary=study_animals, backref='studies')


class UserRole(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)


class User(VersionedModel):
    id = Column(Integer, primary_key=True)
    first_name = Column(String(150), unique=False, nullable=False)
    last_name = Column(String(150), unique=False, nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(512))
    roles = relationship('UserRole', secondary='user_roles', backref='users')
    active = Column(Boolean, default=False, nullable=False)
    admin = Column(Boolean, default=False, nullable=False)

    def is_admin(self):
        return self.admin

    @property
    def is_active(self):
        # Used by Flask-Login to decide whether an account may log in.
        return self.active

    # ``is_authenticated`` and ``is_anonymous`` use Flask-Login's defaults
    # (True / False respectively). Deactivation is enforced at login time
    # and on every request by the GUI's ``check_login`` hook, so we don't
    # conflate "logged in" with "still active" here.
    is_authenticated = True
    is_anonymous = False

    def set_password(self, password):
        """Creates a hashed version of the password."""
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Checks the provided password against the stored hash."""
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

    @property
    def display_name(self):
        return f'{self.first_name} {self.last_name}'

    # Python 3 implicitly set __hash__ to None if we override __eq__ We set it
    # back to its default implementation
    __hash__ = object.__hash__

    def get_id(self):
        return str(self.id)

    def __eq__(self, other):
        if isinstance(other, User):
            return self.get_id() == other.get_id()
        return NotImplemented

    def __ne__(self, other):
        equal = self.__eq__(other)
        if equal is NotImplemented:
            return NotImplemented
        return not equal


class SyncJob(Base):
    """Background-job record for sync / rematch runs.

    Created at request time, updated by the RQ worker. Not versioned
    (this is operational state, not domain data).
    """
    __tablename__ = 'sync_job'

    id = Column(Integer, primary_key=True)
    datatype_id = Column(
        Integer, ForeignKey('data_type.id', ondelete='SET NULL'), nullable=True,
    )
    # 'sync' | 'rematch' | 'force_rematch'
    kind = Column(String(32), nullable=False)
    # 'pending' | 'running' | 'success' | 'failed'
    status = Column(String(32), nullable=False, default='pending')
    enqueued_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    # Counts dict from sync_locations / rematch_datatype, JSON-encoded.
    summary = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    # RQ's internal job id. Lets the worker-boot stale-job sweep tell
    # "still queued in Redis" apart from "worker died". Nullable because
    # tests / sync-execution paths don't always go through RQ, and
    # historical rows predate this column.
    rq_job_id = Column(String(64), nullable=True)

    datatype = relationship('DataType')


orm.configure_mappers()
