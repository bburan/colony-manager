"""Domain status enumerations.

``StrEnum`` (Python 3.11+) members compare equal to their string values, so
SQLAlchemy column defaults, ``==`` comparisons, JSON serialisation, and
template rendering all work without calling ``.value``.
"""
from enum import StrEnum


class SyncJobStatus(StrEnum):
    """Lifecycle states stored in ``SyncJob.status``."""
    PENDING = 'pending'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED  = 'failed'


class SyncJobKind(StrEnum):
    """Discriminator stored in ``SyncJob.kind``."""
    SYNC          = 'sync'
    REMATCH       = 'rematch'
    FORCE_REMATCH = 'force_rematch'
    RATING_SYNC   = 'rating_sync'


class DataStatus(StrEnum):
    """Review / lifecycle status stored in ``Data.status``."""
    UNREVIEWED = 'unreviewed'
    REVIEWED   = 'reviewed'
    EXCLUDE    = 'exclude'
    MISSING    = 'missing'


class ConfocalImageStatus(StrEnum):
    """Processing status stored in ``ConfocalImage.status``."""
    IMAGED         = 'imaged'
    ANALYZED       = 'analyzed'
    NEED_REVIEW    = 'need_review'
    REGION_MISSING = 'region_missing'
    REGION_BAD     = 'region_bad'
