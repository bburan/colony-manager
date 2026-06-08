"""Models package.

Submodule layout
----------------
base.py       — Base, VersionedModel, NestedMixin, association tables,
                side-normalization helpers
system.py     — UserRole, User, SyncJob
animal.py     — Species, Source, TerminationReason, AnimalProcedure/Target/Tag,
                AnimalEvent/Tag, DosageProtocol/Drug, Cage, Animal,
                BreedingPair, Litter, Feed, WeightLog, FeedLog, Study
histology.py  — ImmunolabelingPanel, EarTag, ConfocalImageType, Ear, ConfocalImage
data.py       — DataType (+ subclasses), DataLocation, Data (+ subclasses)

All public names are re-exported here so that existing
``from colony_manager.models import X`` call sites continue to work.

Import order is intentional: each module only depends on ``base``, so
there are no import-time circular dependencies.  String-based SA
relationship references and lazy imports inside ``match_targets()`` /
``Animal.terminate()`` handle the runtime cross-references.
"""
from sqlalchemy import orm

# --- infrastructure ---------------------------------------------------------
from .base import (
    Base,
    VersionedModel,
    NestedMixin,
    _MISSING,
    _canonical_side,
    _expand_sides,
    # association tables (Alembic needs them in metadata; routes use
    # data_candidate_animals directly)
    study_animals,
    user_roles,
    animal_tags,
    animal_event_tags,
    ear_tags,
    data_candidate_animals,
    data_candidate_ears,
    animal_event_data_targets,
    confocal_image_data_targets,
    animal_data_targets,
    ear_data_targets,
)

# --- system models ----------------------------------------------------------
from .system import UserRole, User, SyncJob

# --- animal-domain models ---------------------------------------------------
from .animal import (
    Species,
    Source,
    TerminationReason,
    AnimalProcedure,
    AnimalProcedureTarget,
    AnimalTag,
    AnimalEventTag,
    Cage,
    Animal,
    BreedingPair,
    Litter,
    Feed,
    WeightLog,
    FeedLog,
    AnimalEvent,
    DosageProtocol,
    DosageProtocolDrug,
    Study,
)

# --- histology models -------------------------------------------------------
from .histology import (
    ImmunolabelingPanel,
    EarTag,
    ConfocalImageType,
    Ear,
    ConfocalImage,
)

# --- data / sync models -----------------------------------------------------
from .data import (
    DataType,
    AnimalEventDataType,
    ConfocalImageDataType,
    AnimalDataType,
    EarDataType,
    DATATYPE_SUBCLASSES,
    DataLocation,
    Data,
    AnimalEventData,
    ConfocalImageData,
    AnimalData,
    EarData,
    DATA_SUBCLASSES,
)

# Resolve all string-based relationship references now that every mapper
# is registered.  Mirrors the original models.py behaviour.
orm.configure_mappers()
