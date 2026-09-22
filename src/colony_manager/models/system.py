"""System / operational models: User, UserRole, SyncJob."""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, String, Text, ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from colony_manager.enums import SyncJobStatus

from .base import Base, VersionedModel, user_roles


class UserRole(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)


class User(VersionedModel):
    """An account, authenticated by local password, by SSO, or by both.

    The two credential paths are independent and additive: ``password_hash``
    backs the local login form, ``oidc_issuer``/``oidc_subject`` back the
    OIDC single-sign-on flow. An account may carry either, both, or — very
    briefly, between auto-provisioning and first password set — neither.
    """

    __table_args__ = (
        # ``sub`` is only promised to be unique *within* an issuer, so the
        # identity is the pair, not the subject alone. Two users can never
        # share one IdP identity; one user is never linked to two.
        UniqueConstraint('oidc_issuer', 'oidc_subject',
                         name='uq_user_oidc_identity'),
    )

    id = Column(Integer, primary_key=True)
    first_name = Column(String(150), unique=False, nullable=False)
    last_name  = Column(String(150), unique=False, nullable=False)
    email      = Column(String(150), unique=True,  nullable=False)
    password_hash = Column(String(512))
    # OIDC identity, populated the first time this account signs in through
    # SSO (see ``colony_manager_gui.services.sso``). NULL on a local-only
    # account; the issuer is stored alongside the subject so re-pointing the
    # deployment at a different IdP can't silently hand an account over.
    oidc_issuer  = Column(String(255), nullable=True)
    oidc_subject = Column(String(255), nullable=True)
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
        """Verify a local password. Always False for an SSO-only account.

        ``password_hash`` is NULL on an account that has only ever signed in
        through SSO, and ``check_password_hash(None, ...)`` raises rather
        than returning False — so guard before delegating.
        """
        from werkzeug.security import check_password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def has_password(self):
        """True when this account can sign in with the local login form."""
        return bool(self.password_hash)

    @property
    def is_sso_linked(self):
        """True when this account is bound to an OIDC identity."""
        return bool(self.oidc_subject)

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
