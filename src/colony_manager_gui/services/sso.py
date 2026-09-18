"""Turn a verified set of OIDC claims into a local :class:`User` row.

The route layer owns the OAuth dance (redirect, state, token exchange,
signature/nonce validation); by the time anything here runs the claims
are already trustworthy. What's left is the policy question this module
answers: *which local account, if any, does this identity correspond to,
and may it sign in?*

Matching runs in two tiers, and the order matters:

1. **By OIDC identity** — ``(issuer, subject)``. ``sub`` is the only
   claim an IdP promises is stable and never reassigned, so once an
   account is linked this is the only lookup that runs. A user who
   changes their name or email address at the institution keeps their
   account.
2. **By email**, once, to *establish* the link. This is the bootstrap
   for accounts that predate SSO (or were created by an admin), and it
   is the risky tier: an email address can be reassigned by the
   institution, so it is gated on ``email_verified`` and on the allowed
   domain list before it is trusted.

After tier 2 succeeds the subject is written to the row and tier 2 never
runs for that account again. An account already linked to a *different*
subject is never re-linked by email — that combination means either the
IdP reissued subjects or someone else now holds the address, and neither
is something to resolve silently.
"""
from sqlalchemy import func, select

from colony_manager.models import User


class SSOError(Exception):
    """A sign-in that must be refused, with a user-facing message.

    ``category`` maps onto the flash categories the templates already
    style ('danger' for a refusal, 'warning' for "created, now wait").
    """

    def __init__(self, message, category='danger'):
        super().__init__(message)
        self.message = message
        self.category = category


def _claim(claims, *names):
    """First non-empty claim among ``names``."""
    for name in names:
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_identity(claims, config):
    """Pull the fields we care about out of the raw claim set.

    Returns ``(subject, issuer, email, first_name, last_name)``. Name
    claims are optional — an IdP that sends only ``email`` still yields a
    usable account, with the local part standing in for a display name.
    """
    subject = _claim(claims, 'sub')
    if not subject:
        raise SSOError('The identity provider returned no subject claim.')

    # ``iss`` is present in every ID token; fall back to the configured
    # issuer for the (unusual) case of claims sourced from userinfo only.
    issuer = _claim(claims, 'iss') or config.get('issuer') or config.get('discovery_url')

    email = _claim(claims, 'email', 'preferred_username', 'upn')
    if not email or '@' not in email:
        raise SSOError(
            'The identity provider did not return an email address. '
            'Ask your administrator to enable the "email" scope for this '
            'application.'
        )
    email = email.lower()

    first_name = _claim(claims, 'given_name', 'first_name')
    last_name = _claim(claims, 'family_name', 'last_name')
    if not (first_name and last_name):
        full = _claim(claims, 'name')
        if full and ' ' in full:
            head, _, tail = full.partition(' ')
            first_name = first_name or head
            last_name = last_name or tail
        else:
            # Nothing but an email to go on. The local part is a better
            # placeholder than a made-up surname; ``last_name`` is NOT NULL
            # but perfectly happy empty, and an admin can fix it later.
            first_name = first_name or full or email.split('@')[0]
            last_name = last_name or ''

    return subject, issuer, email, first_name, last_name


def check_email_policy(claims, email, config):
    """Reject an email the deployment's policy says not to trust.

    Only relevant to the email-matching tier — an account already linked
    by subject has passed this check once and doesn't re-run it, so a
    later domain-list change can't lock existing users out.
    """
    if config.get('require_verified_email'):
        # Absent means "the IdP doesn't emit this claim", which is common
        # and not itself suspicious; only an explicit false is a refusal.
        if claims.get('email_verified') is False:
            raise SSOError(
                f'{email} is not a verified address at the identity provider.'
            )

    domains = config.get('allowed_domains') or []
    if domains and email.rsplit('@', 1)[-1] not in domains:
        raise SSOError(
            f'{email} is not in a domain permitted to sign in here.'
        )


def find_by_identity(session, issuer, subject):
    return session.scalars(
        select(User).where(
            User.oidc_issuer == issuer, User.oidc_subject == subject,
        )
    ).first()


def find_by_email(session, email):
    return session.scalars(
        select(User).where(func.lower(User.email) == email.lower())
    ).first()


def resolve_user(session, claims, config):
    """Return the local :class:`User` for a verified claim set.

    Commits any linking or provisioning it performs. Raises
    :class:`SSOError` when the sign-in must be refused; the caller turns
    that into a flash on the login page.
    """
    subject, issuer, email, first_name, last_name = extract_identity(claims, config)

    # --- Tier 1: an account already linked to this IdP identity. ---
    user = find_by_identity(session, issuer, subject)
    if user is not None:
        # Keep the local record in step with the institution's directory.
        # Email is the one field a user can't fix themselves here, and a
        # stale one breaks nothing but confuses every list that shows it.
        if user.email.lower() != email and find_by_email(session, email) is None:
            user.email = email
            session.commit()
        return user

    # --- Tier 2: first sign-in. Match an existing account by email. ---
    check_email_policy(claims, email, config)
    user = find_by_email(session, email)
    if user is not None:
        # Tier 1 already missed, so any link this account carries is to a
        # *different* identity — a different subject at this issuer, or the
        # same subject string at some other issuer, which is not the same
        # person. Either way, refuse rather than silently re-point it.
        if user.oidc_subject and (user.oidc_issuer, user.oidc_subject) != (issuer, subject):
            raise SSOError(
                f'The account for {email} is already linked to a different '
                'single sign-on identity. Contact an administrator.'
            )
        user.oidc_issuer = issuer
        user.oidc_subject = subject
        session.commit()
        return user

    # --- No local account. Provision one, if the deployment allows it. ---
    if not config.get('auto_provision'):
        raise SSOError(
            f'No Colony Manager account exists for {email}. Create one with '
            'the "Create account" tab, or ask an administrator to add you.'
        )

    user = User(
        first_name=first_name,
        last_name=last_name,
        email=email,
        oidc_issuer=issuer,
        oidc_subject=subject,
        active=bool(config.get('auto_activate')),
        admin=False,
    )
    # No password is set: the account is SSO-only until its owner sets one
    # through the change-password flow. ``User.check_password`` returns
    # False for a NULL hash, so the local form can't be used meanwhile.
    session.add(user)
    session.commit()
    if not user.is_active:
        raise SSOError(
            f'An account was created for {email} and is awaiting '
            'administrator approval.',
            category='warning',
        )
    return user
