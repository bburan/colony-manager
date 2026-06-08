"""System / operational models: User, UserRole, SyncJob."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship

from colony_manager.enums import SyncJobStatus

from .base import Base, VersionedModel, user_roles


class UserRole(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)


class User(VersionedModel):
    id = Column(Integer, primary_key=True)
    first_name = Column(String(150), unique=False, nullable=False)
    last_name  = Column(String(150), unique=False, nullable=False)
    email      = Column(String(150), unique=True,  nullable=False)
    password_hash = Column(String(512))
    roles  = relationship('UserRole', secondary=user_roles, backref='users')
    active = Column(Boolean, default=False, nullable=False)
    admin  = Column(Boolean, default=False, nullable=False)

    def is_admin(self):
        return self.admin

    @property
    def is_active(self):
        return self.active

    # Flask-Login attrs — deactivation is enforced at login time and by
    # the GUI's check_login hook, so we don't conflate "logged in" with
    # "still active" here.
    is_authenticated = True
    is_anonymous = False

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

    @property
    def display_name(self):
        return f'{self.first_name} {self.last_name}'

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

    Created at request time, updated by the RQ worker.  Not versioned
    (this is operational state, not domain data).
    """
    __tablename__ = 'sync_job'

    id          = Column(Integer, primary_key=True)
    datatype_id = Column(
        Integer, ForeignKey('data_type.id', ondelete='SET NULL'), nullable=True,
    )
    kind       = Column(String(32), nullable=False)
    status     = Column(String(32), nullable=False, default=SyncJobStatus.PENDING)
    enqueued_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at  = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    summary     = Column(Text, nullable=True)
    error       = Column(Text, nullable=True)
    rq_job_id   = Column(String(64), nullable=True)

    datatype = relationship('DataType')
