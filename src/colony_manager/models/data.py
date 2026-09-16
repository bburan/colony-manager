"""Data / DataType polymorphic models.

``match_targets()`` methods on DataType subclasses reference Animal, Ear,
ConfocalImage, etc. via lazy imports inside the method body to avoid
circular imports at module load time.
"""
from pathlib import Path
import os
from typing import NamedTuple

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, JSON,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    auto_create       = Column(Boolean, nullable=False, default=False, server_default='false')
    description_class = Column(String(200), nullable=True)

    locations   = relationship('DataLocation', backref='datatype', cascade='all, delete-orphan')
    data_files  = relationship('Data',         backref='datatype', cascade='all, delete-orphan')

    __mapper_args__ = {
        'polymorphic_on': target_type,
        'polymorphic_identity': 'datatype',
    }

    TARGET_LABEL = 'Generic'

    def get_description_class(self):
        if not self.description_class:
            return None
        from colony_manager.datatypes import load_description_class
        return load_description_class(self.description_class)

    def get_description_callbacks(self):
        try:
            cls = self.get_description_class()
            return cls.get_callbacks() if cls is not None else {}
        except Exception:
            return {}

    @property
    def uses_folders(self):
        """Whether ``sync`` should walk directories rather than files.

        Read straight off the description class, which is the only thing
        that knows whether its ``parse()`` expects a directory. A DataType
        with no resolvable class reports ``False``, which costs nothing:
        such a row cannot sync at all.
        """
        try:
            cls = self.get_description_class()
        except Exception:
            return False
        return bool(getattr(cls, 'is_folder', False))

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
        from .animal import Animal, AnimalEvent, AnimalProcedure

        animal_ids = parsed.get('animal_id') or []
        if isinstance(animal_ids, str):
            animal_ids = [animal_ids]
        target_date = parsed.get('date')
        if not animal_ids or not target_date or not self.default_procedure_id:
            return []
        # Match the configured procedure *or any of its subprocedures*: an
        # event recorded against a more specific child (e.g. a subtype of
        # "Noise Exposure") should still link to a DataType whose default is
        # the parent procedure.
        procedure_ids = AnimalProcedure.descendant_ids(
            session, self.default_procedure_id,
        )
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
                AnimalEvent.procedure_id.in_(procedure_ids),
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

class UnmatchedObject(NamedTuple):
    """One pill in the Unmatched-Data page's "Unlinked objects" column.

    *kind* is ``'animal'`` or ``'ear'``; *obj* is the ORM row the named
    thing resolves to, or ``None`` when no such row exists yet; *label*
    is the pill text for the whole name. *animal* and *side* carry the
    two halves of an ear name separately so the page can render a hybrid
    pill -- a linked animal beside the side that has no ``Ear`` row --
    when the animal exists but its ear doesn't. *animal* is the resolved
    ``Animal`` (or ``None`` for a name that matches nothing); *side* is
    ``None`` for animal-kind entries.
    """
    kind:   str
    obj:    object
    label:  str
    animal: object = None
    side:   str | None = None


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
    # For rating schemes with named raters (e.g. ABR waveform picks):
    # ``raters`` is the sorted list of who has rated, ``rater_count`` its
    # length. Both are set by the sync-rating job from a description
    # class's ``get_rating_status()['raters']`` and let the rating-review
    # page filter by coverage (single vs multi rater) and by identity.
    rater_count     = Column(Integer, nullable=True)
    raters          = Column(JSONB, nullable=True)
    # Unified analysis-attribution columns, populated by the sync-rating job
    # from a description class's ``get_rating_status()`` (``analyzed_by`` /
    # ``analyzed_at``). Distinct from ``raters``: ``analyzed_by`` is the
    # cross-datatype "who worked this analysis" list the scoreboard reads for
    # every ratable type (ABR mirrors ``raters`` into it; IHC/OHC and
    # synaptograms populate it from the analysis file's ``meta.history``),
    # while ``analyzed_at`` is when the analysis was last modified. Both stay
    # NULL for older files that carry no attribution metadata.
    analyzed_by     = Column(JSONB, nullable=True)
    analyzed_at     = Column(DateTime, nullable=True)
    mtime           = Column(DateTime, nullable=True)
    ctime           = Column(DateTime, nullable=True)
    discovered_at   = Column(DateTime, nullable=True)
    parsed_metadata = Column(JSON, nullable=True)
    # Queryable flag: at least one animal ID parsed from the filename had no
    # matching Animal at the last sync/rematch (even if other IDs matched).
    # Maintained by ``sync.py``; drives the data-review page filter. For live
    # display, prefer the ``unmatched_animal_ids`` property, which recomputes
    # from ``candidate_animals`` and lists the specific offending IDs.
    has_unmatched_animals = Column(
        Boolean, nullable=False, default=False, server_default='false',
    )

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
    def full_path(self):
        """Where this file actually lives: its location's base + relative path.

        The UI lists files by ``name`` alone, which is not enough to go
        find one on disk, so every listing hangs this off a hover title.
        Purely for display — code that opens the file joins the same two
        parts itself, since it needs the path before the row is loaded.
        """
        base = self.location.base_path if self.location is not None else ''
        return os.path.join(base, self.relative_path or '')

    def get_description(self):
        """Return a DataTypeDescription instance for this file, or None."""
        cls = self.datatype.get_description_class()
        if cls is None:
            return None
        return cls(self)

    @property
    def targets(self):
        return []

    @property
    def is_unmatched(self):
        return len(self.targets) == 0

    @property
    def parsed_animal_ids(self):
        """Animal custom_ids the parser extracted from the filename."""
        parsed = self.parsed_metadata or {}
        raw = parsed.get('animal_id')
        if not raw:
            return []
        return list(raw) if isinstance(raw, (list, tuple)) else [raw]

    @property
    def matched_animal_ids(self):
        """custom_ids of animals reachable from this file's linked targets.

        Overridden per subclass to walk that subclass's target collection
        down to the owning Animal. The base has no targets.
        """
        return set()

    @property
    def unmatched_animal_ids(self):
        """Parsed animal IDs that have no linked target on this file.

        A multi-animal filename is only fully matched once *every* animal
        it names has a linked target. This lists the ones that don't yet —
        covering both animals absent from the colony (a typo like
        ``B0828-4`` can never be linked) and animals that exist but whose
        event/ear/image isn't linked yet. Empty once all are matched.
        """
        parsed_ids = self.parsed_animal_ids
        if not parsed_ids:
            return []
        matched = self.matched_animal_ids
        return [aid for aid in parsed_ids if aid not in matched]

    @property
    def parsed_ear_sides(self):
        """``{animal_id: side}`` for the sides the parser named, if any.

        Description classes disagree on how they spell this, so all the
        shapes in the wild are accepted: confocal images write ``ear``
        (``'Left'``), ear-targeted files write ``side`` as a *list*
        (``['Left']``), and psi-derived event files carry both, lowercased.
        A scalar applies to every animal the filename names (the common
        single-animal case); a list is zipped positionally against
        ``parsed_animal_ids``, matching how ``animal_id`` is itself stored.

        Sides come back title-cased so they compare and render against
        ``Ear.side`` regardless of which parser produced them.
        """
        parsed = self.parsed_metadata or {}
        ids = self.parsed_animal_ids
        if not ids or not isinstance(parsed, dict):
            return {}
        for key in ('ear', 'side'):
            raw = parsed.get(key)
            if not raw:
                continue
            if isinstance(raw, (list, tuple)):
                pairs = zip(ids, raw)
            else:
                pairs = ((aid, raw) for aid in ids)
            sides = {aid: str(side).title() for aid, side in pairs if side}
            if sides:
                return sides
        return {}

    @property
    def unmatched_objects(self):
        """Objects named in the filename but not yet linked, for display.

        Returns a list of :class:`UnmatchedObject` records, which the
        Unmatched-Data page renders as pills: a thing that resolves to a
        real row links to its detail page, a name that resolves to
        nothing greys out, and an ear whose animal exists but whose
        ``Ear`` row does not renders as a hybrid of the two. The base
        walks animals; ear/confocal subclasses override to yield ``Ear``
        rows at side granularity via :meth:`_ear_unmatched_objects`.
        """
        return self._animal_unmatched_objects()

    def _animal_unmatched_objects(self):
        by_cid = {a.custom_id: a for a in self.candidate_animals}
        objects = []
        for aid in self.unmatched_animal_ids:
            animal = by_cid.get(aid)
            objects.append(UnmatchedObject(
                'animal', animal, animal.display_id if animal else aid,
                animal=animal))
        return objects

    def _ear_unmatched_objects(self, linked_ear_ids):
        """Shared body for ear-targeted subclasses: the still-unlinked ears,
        at side granularity.

        The target of these datatypes is an ear, so a name the file hasn't
        linked is reported as an *ear* whenever the filename says which
        side -- including when no such ear row exists. "B047-3 Right is
        missing" is the actionable fact; "B047-3 is missing" is misleading
        when the animal is right there and only its Right ear isn't.

        An ear that exists but was never made a candidate still resolves
        here, so it renders as a link rather than a dead name. When only
        the animal resolves, it still rides along on the entry so the page
        can link to it -- that page is where the missing ear gets created.
        Only when the filename names no side at all is there nothing more
        specific to offer than the animal.
        """
        objects = []
        covered_cids = set()
        for ear in sorted(self.candidate_ears):
            if ear.id in linked_ear_ids:
                continue
            objects.append(UnmatchedObject(
                'ear', ear, ear.full_display,
                animal=ear.animal, side=ear.side))
            covered_cids.add(ear.animal.custom_id)
        by_cid = {a.custom_id: a for a in self.candidate_animals}
        sides = self.parsed_ear_sides
        for aid in self.unmatched_animal_ids:
            if aid in covered_cids:
                continue
            animal = by_cid.get(aid)
            side = sides.get(aid)
            if side is None:
                objects.append(UnmatchedObject(
                    'animal', animal, animal.display_id if animal else aid,
                    animal=animal))
                continue
            ear = None
            if animal is not None:
                ear = next((e for e in animal.ears
                            if (e.side or '').casefold() == side.casefold()),
                           None)
            if ear is not None and ear.id in linked_ear_ids:
                continue
            # ``aid`` rather than ``display_id``: it is the custom_id that
            # matched, which is what ``Ear.full_display`` would render.
            objects.append(UnmatchedObject(
                'ear', ear, ear.full_display if ear else f'{aid} {side}',
                animal=animal, side=ear.side if ear else side))
        return objects

    def recompute_unmatched_flag(self):
        """Refresh the persisted ``has_unmatched_animals`` column.

        Call after any change to this row's targets (sync, rematch, manual
        (un)link, auto-create) so the data-review page's SQL filter stays
        accurate. Kept as a plain method — not an ORM event — so every
        mutation site opts in explicitly.
        """
        self.has_unmatched_animals = bool(self.unmatched_animal_ids)

    @property
    def path(self):
        return Path(self.location.base_path) / self.relative_path


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

    @property
    def matched_animal_ids(self):
        return {e.animal.custom_id for e in self.events}


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

    @property
    def matched_animal_ids(self):
        return {img.ear.animal.custom_id for img in self.confocal_images}

    @property
    def unmatched_objects(self):
        return self._ear_unmatched_objects({img.ear.id for img in self.confocal_images})


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

    @property
    def matched_animal_ids(self):
        return {a.custom_id for a in self.animals}


class EarData(Data):
    __tablename__ = 'ear_data'

    id   = Column(Integer, ForeignKey('data.id'), primary_key=True)
    ears = relationship('Ear', secondary=ear_data_targets, backref='data_files')

    __mapper_args__ = {'polymorphic_identity': 'ear'}

    @property
    def targets(self):
        return list(self.ears)

    @property
    def matched_animal_ids(self):
        return {e.animal.custom_id for e in self.ears}

    @property
    def unmatched_objects(self):
        return self._ear_unmatched_objects({e.id for e in self.ears})


DATA_SUBCLASSES = {
    'animal_event':   AnimalEventData,
    'confocal_image': ConfocalImageData,
    'animal':         AnimalData,
    'ear':            EarData,
}
