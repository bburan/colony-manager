"""Coverage for ``ConfocalImage.conflict``, the histology grid's conflict rule.

The property backs both the grid squares' border colors
(``partials/grid_status_square.html``) and the grid's "show conflicts only"
filter, so these cases pin the precedence the two share.
"""
import pytest

from colony_manager.enums import ConfocalImageStatus
from colony_manager.models.histology import (
    CONFLICT_FILE_MISMATCH, CONFLICT_MULTIPLE_FILES, CONFLICT_UNANALYZED,
)

from .factories import (
    make_animal, make_confocal_image, make_confocal_image_data,
    make_confocal_image_type, make_ear,
)


@pytest.fixture
def image(db_session):
    animal = make_animal(db_session, custom_id='C-1')
    ear = make_ear(db_session, animal=animal, side='Left')
    return make_confocal_image(
        db_session, ear=ear, image_type=make_confocal_image_type(db_session),
    )


def _attach(db_session, image, *, is_rated=None):
    row = make_confocal_image_data(db_session, confocal_image=image)
    row.is_rated = is_rated
    db_session.commit()
    return row


@pytest.mark.parametrize('status', [
    ConfocalImageStatus.IMAGED,
    ConfocalImageStatus.ANALYZED,
    ConfocalImageStatus.NEED_REVIEW,
    ConfocalImageStatus.REGION_BAD,
])
def test_status_expecting_a_file_with_none_linked_is_a_mismatch(
    db_session, image, status,
):
    image.status = status
    db_session.commit()
    assert image.conflict == CONFLICT_FILE_MISMATCH


def test_region_missing_with_no_file_is_not_a_conflict(db_session, image):
    """The region was never imaged, so having no file is correct."""
    image.status = ConfocalImageStatus.REGION_MISSING
    db_session.commit()
    assert image.conflict is None


def test_region_missing_with_a_file_is_a_mismatch(db_session, image):
    """The other direction: a file exists for a region marked missing."""
    image.status = ConfocalImageStatus.REGION_MISSING
    _attach(db_session, image, is_rated=True)
    db_session.commit()
    assert image.conflict == CONFLICT_FILE_MISMATCH


def test_two_files_linked_is_a_multiple_files_conflict(db_session, image):
    image.status = ConfocalImageStatus.ANALYZED
    _attach(db_session, image, is_rated=True)
    _attach(db_session, image, is_rated=True)
    db_session.commit()
    assert image.conflict == CONFLICT_MULTIPLE_FILES


def test_analyzed_with_an_unrated_file_is_an_unanalyzed_conflict(
    db_session, image,
):
    image.status = ConfocalImageStatus.ANALYZED
    _attach(db_session, image, is_rated=False)
    db_session.commit()
    assert image.conflict == CONFLICT_UNANALYZED


def test_analyzed_with_a_rated_file_is_clean(db_session, image):
    image.status = ConfocalImageStatus.ANALYZED
    _attach(db_session, image, is_rated=True)
    db_session.commit()
    assert image.conflict is None


def test_null_is_rated_is_not_treated_as_missing_analysis(db_session, image):
    """NULL means the rating job has nothing to say, not "unanalyzed".

    Flagging it would paint every cell of a datatype whose description
    class doesn't support rating.
    """
    image.status = ConfocalImageStatus.ANALYZED
    _attach(db_session, image, is_rated=None)
    db_session.commit()
    assert image.conflict is None


def test_unrated_file_on_a_non_analyzed_status_is_clean(db_session, image):
    """Only a status of *analyzed* claims the analysis is done."""
    image.status = ConfocalImageStatus.IMAGED
    _attach(db_session, image, is_rated=False)
    db_session.commit()
    assert image.conflict is None


def test_mismatch_outranks_multiple_files(db_session, image):
    """Region-missing-with-files wins over the two-files rule."""
    image.status = ConfocalImageStatus.REGION_MISSING
    _attach(db_session, image, is_rated=True)
    _attach(db_session, image, is_rated=True)
    db_session.commit()
    assert image.conflict == CONFLICT_FILE_MISMATCH


def test_multiple_files_outranks_unanalyzed(db_session, image):
    image.status = ConfocalImageStatus.ANALYZED
    _attach(db_session, image, is_rated=False)
    _attach(db_session, image, is_rated=False)
    db_session.commit()
    assert image.conflict == CONFLICT_MULTIPLE_FILES
