"""Regression guard for enum string values.

Ensures the DB-stored string values never silently change.  If a value
here differs from what's in the database, migrations would be needed —
so any accidental rename must cause a test failure.
"""
from colony_manager.enums import (
    ConfocalImageStatus, DataStatus, SyncJobKind, SyncJobStatus,
)


def test_sync_job_status_values():
    assert SyncJobStatus.PENDING == 'pending'
    assert SyncJobStatus.RUNNING == 'running'
    assert SyncJobStatus.SUCCESS == 'success'
    assert SyncJobStatus.FAILED  == 'failed'


def test_sync_job_kind_values():
    assert SyncJobKind.SYNC          == 'sync'
    assert SyncJobKind.REMATCH       == 'rematch'
    assert SyncJobKind.FORCE_REMATCH == 'force_rematch'


def test_data_status_values():
    assert DataStatus.UNREVIEWED == 'unreviewed'
    assert DataStatus.REVIEWED   == 'reviewed'
    assert DataStatus.EXCLUDE    == 'exclude'
    assert DataStatus.MISSING    == 'missing'


def test_confocal_image_status_values():
    assert ConfocalImageStatus.IMAGED         == 'imaged'
    assert ConfocalImageStatus.ANALYZED       == 'analyzed'
    assert ConfocalImageStatus.NEED_REVIEW    == 'need_review'
    assert ConfocalImageStatus.REGION_MISSING == 'region_missing'
    assert ConfocalImageStatus.REGION_BAD     == 'region_bad'


def test_str_enum_members_are_strings():
    """StrEnum members must be proper str instances so SQLAlchemy can
    store them and template comparisons work without .value."""
    for member in SyncJobStatus:
        assert isinstance(member, str)
    for member in SyncJobKind:
        assert isinstance(member, str)
    for member in DataStatus:
        assert isinstance(member, str)
    for member in ConfocalImageStatus:
        assert isinstance(member, str)
