"""Forms package.

Each submodule owns one domain:

    common    — query factories, shared widgets, cross-blueprint forms
    auth      — login / user-management forms
    animals   — animal, event, dosage, and daily-log forms
    breeding  — breeding pair, litter, and weaning forms
    cages     — cage form
    studies   — study and add-to-study forms
    histology — histology and confocal-image forms
    settings  — DataType, DataLocation, and settings-registry forms

All public names are re-exported here so that existing
``from ..forms import X`` call sites continue to work.
"""
from .common import (
    order_by,
    species_factory,
    source_factory,
    study_factory,
    cage_factory,
    animal_procedure_factory,
    animal_procedure_target_factory,
    panel_factory,
    termination_reason_factory,
    confocal_image_type_factory,
    male_animal_factory,
    female_animal_factory,
    active_animal_factory,
    ButtonGroupWidget,
    NoteForm,
    CSRFOnlyForm,
    UploadFilesForm,
    QuickAddToStudyForm,
    TerminationForm,
    create_nested_form,
    mark_disabled,
    mark_readonly,
)
from .auth import (
    validate_password_complexity,
    UserLoginForm,
    UserCreateForm,
    UserEditForm,
)
from .animals import (
    AnimalCustomIDForm,
    AnimalForm,
    AnimalEventForm,
    AnimalEventEditForm,
    DosageCalculateForm,
    FeedEntryForm,
    DailyLogForm,
)
from .breeding import (
    BreedingPairForm,
    LitterForm,
    LitterDeleteForm,
    WeanedCageForm,
    WeaningForm,
)
from .cages import CageForm
from .studies import StudyForm, AddToStudyForm
from .histology import HistologyForm, ConfocalImageForm
from .settings import (
    SimpleAddForm,
    SimpleAddWithDescriptionForm,
    ProcedureTargetForm,
    FeedForm,
    DataTypeForm,
    AnimalEventDataTypeForm,
    ConfocalImageDataTypeForm,
    AnimalDataTypeForm,
    EarDataTypeForm,
    DATATYPE_FORMS,
    DATATYPE_TARGET_LABELS,
    datatype_form_for,
    DataLocationForm,
    DosageProtocolForm,
)
