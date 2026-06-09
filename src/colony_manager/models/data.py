"""Data / DataType polymorphic models.

``match_targets()`` methods on DataType subclasses reference Animal, Ear,
ConfocalImage, etc. via lazy imports inside the method body to avoid
circular imports at module load time.
"""
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, JSON,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import relationship

from colony_manager.enums import DataStatus

from .base import (
    VersionedModel,
    _canonical_side, _expand_sides,
    data_candidate_animals, data_candidate_ears,
    animal_event_data_targets, confocal_image_data_targets,
    animal_data_targets, ear_data_targets,
)


# ---------------------------------------------------------------------------
# DataType polymorphic hierarchy
# ---------------------------------------------------------------------------

class DataType(VersionedModel):
    """Polymorphic base. Subclasses target specific model types."""
    __tablename__ = 'data_type'

    id                = Column(Integer, primary_key=True)
    name              = Column(String(100), unique=True, nullable=False)
    description       = Column(Text, nullable=True)
    target_type       = Column(String(50), nullable=False)
    is_folder         = Column(Boolean, nullable=False, default=False, server_default='false')
    auto_create       = Column(Boolean, nullable=False, default=False, server_default='false')
    description_class = Column(String(200), nullable=True)

    locations   = relationship('DataLocation', backref='datatype', cascade='all, delete-orphan')
    data_files  = relationship('Data',         backref='datatype', cascade='all, delete-orphan')

    __mapper_args__ = {
        'polymorphic_on': target_type,
        'polymorphic_identity': 'datatype',
    }

    TARGET_LABEL = 'Generic'

    def get_description(self):
        if not self.description_class:
            return {}
        from colony_manager.datatypes import load_description_class
        return load_description_class(self.description_class)

    def get_description_callbacks(self):
        try:
            return self.get_description().get_callbacks()
        except Exception:
            return {}

    def match_targets(self, session, parsed):
        return []


class AnimalEventDataType(DataType):
    __tablename__ = 'animal_event_data_type'

    id                          = Column(Integer, ForeignKey('data_type.id'), primary_key=True)
    default_procedure_id        = Column(Integer, ForeignKey('animal_procedure.id'),        nullable=True)
    default_procedure_target_id = Column(Integer, ForeignKey('animal_procedure_target.id'), nullable=True)

    default_procedure        = relationship('AnimalProcedure',       lazy=True)
    default_procedure_target = relationship('AnimalProcedureTarget', lazy=True)

    __mapper_args__ = {'polymorphic_identity': 'animal_event'}
    TARGET_LABEL = 'Animal Event'

    def match_targets(self, session, parsed):
        from sqlalchemy import select, or_
        from .animal import Animal, AnimalEvent

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
        from .animal import Animal
        from .histology import ConfocalImage, ConfocalImageType, Ear

        animal_ids     = parsed.get('animal_id') or []
        if isinstance(animal_ids, str):
            animal_ids = [animal_ids]
        ear            = _canonical_side(parsed.get('ear'))
        frequency      = parsed.get('frequency')
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
        from .animal import Animal

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
        from .animal import Animal
        from .histology import Ear

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


DATATYPE_SUBCLASSES = {
    'animal_event':   AnimalEventDataType,
    'confocal_image': ConfocalImageDataType,
    'animal':         AnimalDataType,
    'ear':            EarDataType,
}


# ---------------------------------------------------------------------------
# DataLocation
# ---------------------------------------------------------------------------

class DataLocation(VersionedModel):
    id          = Column(Integer, primary_key=True)
    datatype_id = Column(Integer, ForeignKey('data_type.id'), nullable=False)
    base_path   = Column(String(1024), nullable=False)
    data_files  = relationship('Data', backref='location', cascade='all, delete-orphan')


# ---------------------------------------------------------------------------
# Data polymorphic hierarchy
# ---------------------------------------------------------------------------

class Data(VersionedModel):
    """Polymorphic base for files discovered by the sync script."""
    __tablename__ = 'data'

    id              = Column(Integer, primary_key=True)
    datatype_id     = Column(Integer, ForeignKey('data_type.id'),     nullable=False)
    location_id     = Column(Integer, ForeignKey('data_location.id'), nullable=False)
    target_type     = Column(String(50), nullable=False)
    relative_path   = Column(String(1024), nullable=False)
    file_hash       = Column(String(64), nullable=True)
    name            = Column(String(255), nullable=False)
    date            = Column(Date, nullable=True)
    status          = Column(String(50), nullable=False, default=DataStatus.UNREVIEWED)
    notes           = Column(Text, nullable=True)
    is_rated        = Column(Boolean, nullable=True)
    rating_note     = Column(Text, nullable=True)
    mtime           = Column(DateTime, nullable=True)
    ctime           = Column(DateTime, nullable=True)
    discovered_at   = Column(DateTime, nullable=True)
    parsed_metadata = Column(JSON, nullable=True)

    candidate_animals = relationship(
        'Animal', secondary=data_candidate_animals, backref='candidate_data_files',
    )
    candidate_ears = relationship(
        'Ear', secondary=data_candidate_ears, backref='candidate_data_files',
    )

    __table_args__ = (UniqueConstraint('location_id', 'relative_path'),)

    __mapper_args__ = {
        'polymorphic_on': target_type,
        'polymorphic_identity': 'data',
    }

    @property
    def targets(self):
        return []

    @property
    def is_unmatched(self):
        return len(self.targets) == 0


class AnimalEventData(Data):
    __tablename__ = 'animal_event_data'

    id     = Column(Integer, ForeignKey('data.id'), primary_key=True)
    events = relationship(
        'AnimalEvent', secondary=animal_event_data_targets, backref='data_files',
    )

    __mapper_args__ = {'polymorphic_identity': 'animal_event'}

    @property
    def targets(self):
        return list(self.events)


class ConfocalImageData(Data):
    __tablename__ = 'confocal_image_data'

    id              = Column(Integer, ForeignKey('data.id'), primary_key=True)
    confocal_images = relationship(
        'ConfocalImage', secondary=confocal_image_data_targets, backref='data_files',
    )

    __mapper_args__ = {'polymorphic_identity': 'confocal_image'}

    @property
    def targets(self):
        return list(self.confocal_images)


class AnimalData(Data):
    __tablename__ = 'animal_data'

    id      = Column(Integer, ForeignKey('data.id'), primary_key=True)
    animals = relationship(
        'Animal', secondary=animal_data_targets, backref='data_files',
    )

    __mapper_args__ = {'polymorphic_identity': 'animal'}

    @property
    def targets(self):
        return list(self.animals)


class EarData(Data):
    __tablename__ = 'ear_data'

    id   = Column(Integer, ForeignKey('data.id'), primary_key=True)
    ears = relationship('Ear', secondary=ear_data_targets, backref='data_files')

    __mapper_args__ = {'polymorphic_identity': 'ear'}

    @property
    def targets(self):
        return list(self.ears)


DATA_SUBCLASSES = {
    'animal_event':   AnimalEventData,
    'confocal_image': ConfocalImageData,
    'animal':         AnimalData,
    'ear':            EarData,
}
