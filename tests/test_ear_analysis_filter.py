"""The histology list/grid Analysis filter.

The filter card offered five options while the query compared the chosen
value straight against ``ConfocalImage.status``, whose stored values are
``imaged`` / ``analyzed`` / ``need_review`` / ``region_missing`` /
``region_bad``. Only *Imaged* ever matched a row; *Pending*, *Needs
Review* and *Done* each returned no ears at all, silently — the page
rendered fine, just empty, which reads as "nothing to do here".
"""
import pytest

from colony_manager.enums import ConfocalImageStatus
from colony_manager_gui.services.histology_queries import (
    EAR_ANALYSIS_FILTERS, _analysis_filter_clause, get_filtered_ears,
    parse_ear_filters,
)

from .factories import (
    make_animal, make_confocal_image, make_confocal_image_type, make_ear,
)


def _ear_with_images(session, custom_id, *statuses, image_type=None):
    """An ear carrying one image per entry in *statuses*.

    ``None`` means "leave the status column NULL", which is how an image
    created from the UI starts out.
    """
    animal = make_animal(session, custom_id=custom_id)
    ear = make_ear(session, animal=animal, side='Left')
    for i, status in enumerate(statuses):
        image = make_confocal_image(
            session, ear=ear, image_type=image_type,
            frequency=1000.0 * (i + 1),
        )
        image.status = status
    session.commit()
    return ear


def _filtered_ids(session, value):
    filters = parse_ear_filters({'analysis_filter': value})
    return {e.id for e in get_filtered_ears(session, filters)}


# ---------------------------------------------------------------------------
# The guard against the two halves drifting apart again
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value', [v for v, _ in EAR_ANALYSIS_FILTERS])
def test_every_offered_option_is_answerable(value):
    """Nothing may appear in the filter card without a clause behind it.

    ``all`` is the one option that legitimately has no clause.
    """
    clause = _analysis_filter_clause(value)
    if value == 'all':
        assert clause is None
    else:
        assert clause is not None, f'{value!r} is offered but filters nothing'


def test_unknown_value_filters_nothing_rather_than_erroring(db_session):
    ear = _ear_with_images(db_session, 'AF-0', ConfocalImageStatus.IMAGED)
    assert ear.id in _filtered_ids(db_session, 'not-an-option')


# ---------------------------------------------------------------------------
# Each option
# ---------------------------------------------------------------------------

def test_imaged_matches_only_ears_with_an_imaged_image(db_session):
    imaged = _ear_with_images(db_session, 'AF-1', ConfocalImageStatus.IMAGED)
    analyzed = _ear_with_images(db_session, 'AF-2', ConfocalImageStatus.ANALYZED)

    matched = _filtered_ids(db_session, 'imaged')
    assert imaged.id in matched
    assert analyzed.id not in matched


def test_a_null_status_counts_as_imaged(db_session):
    """NULL is how ``conflict`` and the grid square already read it."""
    ear = _ear_with_images(db_session, 'AF-3', None)

    assert ear.id in _filtered_ids(db_session, 'imaged')
    assert ear.id in _filtered_ids(db_session, 'pending')
    assert ear.id not in _filtered_ids(db_session, 'done')


def test_needs_review_matches_only_that_status(db_session):
    review = _ear_with_images(db_session, 'AF-4', ConfocalImageStatus.NEED_REVIEW)
    imaged = _ear_with_images(db_session, 'AF-5', ConfocalImageStatus.IMAGED)

    matched = _filtered_ids(db_session, 'needs_review')
    assert review.id in matched
    assert imaged.id not in matched


@pytest.mark.parametrize('status, is_pending', [
    (ConfocalImageStatus.IMAGED, True),
    (ConfocalImageStatus.NEED_REVIEW, True),
    (ConfocalImageStatus.ANALYZED, False),
    # Terminal: the region isn't there, or isn't usable. Nothing left to do.
    (ConfocalImageStatus.REGION_MISSING, False),
    (ConfocalImageStatus.REGION_BAD, False),
])
def test_pending_is_outstanding_work_only(db_session, status, is_pending):
    ear = _ear_with_images(db_session, f'AF-P-{status}', status)
    assert (ear.id in _filtered_ids(db_session, 'pending')) is is_pending


def test_pending_matches_an_ear_with_any_image_outstanding(db_session):
    """One unfinished image is enough, however much else is done."""
    ear = _ear_with_images(
        db_session, 'AF-6',
        ConfocalImageStatus.ANALYZED,
        ConfocalImageStatus.ANALYZED,
        ConfocalImageStatus.IMAGED,
    )
    assert ear.id in _filtered_ids(db_session, 'pending')
    assert ear.id not in _filtered_ids(db_session, 'done')


def test_done_needs_every_image_resolved(db_session):
    done = _ear_with_images(
        db_session, 'AF-7',
        ConfocalImageStatus.ANALYZED,
        ConfocalImageStatus.REGION_MISSING,
    )
    partly = _ear_with_images(
        db_session, 'AF-8',
        ConfocalImageStatus.ANALYZED,
        ConfocalImageStatus.NEED_REVIEW,
    )

    matched = _filtered_ids(db_session, 'done')
    assert done.id in matched
    assert partly.id not in matched


def test_an_ear_with_no_images_is_neither_pending_nor_done(db_session):
    """Not started is not the same as finished.

    "Done" is an EXISTS over the ear's images precisely so an ear nobody
    has imaged yet doesn't report itself complete.
    """
    animal = make_animal(db_session, custom_id='AF-9')
    ear = make_ear(db_session, animal=animal, side='Left')

    assert ear.id not in _filtered_ids(db_session, 'done')
    assert ear.id not in _filtered_ids(db_session, 'pending')
    assert ear.id in _filtered_ids(db_session, 'all')


# ---------------------------------------------------------------------------
# Through the routes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value', ['pending', 'imaged', 'needs_review', 'done'])
def test_list_and_grid_surface_the_matching_ear(db_session, logged_in_client, value):
    """The regression, end to end: every option must find its ear.

    One ear carries an outstanding image and one a finished one, so each
    option has exactly one ear it should return. Before the fix, three of
    these four rendered an empty table.
    """
    # One shared image type: the grid renders a tab per type and falls back
    # to "no images recorded" when the selected one has no frequencies, so
    # three ears under three types would test the tab default, not the filter.
    image_type = make_confocal_image_type(db_session, name='AF-Type')
    outstanding = _ear_with_images(
        db_session, 'AF-R1', ConfocalImageStatus.IMAGED, image_type=image_type)
    review = _ear_with_images(
        db_session, 'AF-R2', ConfocalImageStatus.NEED_REVIEW, image_type=image_type)
    finished = _ear_with_images(
        db_session, 'AF-R3', ConfocalImageStatus.ANALYZED, image_type=image_type)
    expected = {
        'pending': ['AF-R1', 'AF-R2'],
        'imaged': ['AF-R1'],
        'needs_review': ['AF-R2'],
        'done': ['AF-R3'],
    }[value]
    all_ids = {'AF-R1': outstanding, 'AF-R2': review, 'AF-R3': finished}

    for path in ('/histology/', '/histology/grid'):
        resp = logged_in_client.get(f'{path}?analysis_filter={value}')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        for custom_id in all_ids:
            if custom_id in expected:
                assert custom_id in body, f'{path}?{value}: missing {custom_id}'
            else:
                assert custom_id not in body, f'{path}?{value}: unexpected {custom_id}'
