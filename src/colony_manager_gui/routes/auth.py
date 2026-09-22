from urllib.parse import urlparse, urljoin

import sqlalchemy
from sqlalchemy import select, text
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    current_app, Response,
)
import flask
import flask_login

from colony_manager_gui import db
from colony_manager_gui.auth_decorators import public
from colony_manager_gui.oidc import end_session_url, get_oidc_client, oidc_config
from colony_manager_gui.services.sso import SSOError, resolve_user
from colony_manager_gui.routes.util import flash_form_errors, get_or_404, render_modal
from colony_manager_gui.forms.auth import (
    UserLoginForm, UserCreateForm, UserEditForm, ChangePasswordForm,
)
from colony_manager.models import User

auth_bp = Blueprint('auth', __name__)

# Endpoints inside the auth blueprint that should remain accessible without
# admin privileges. Everything else (user list/view/edit) requires admin.
_AUTH_PUBLIC_ENDPOINTS = {
    'auth.login_user', 'auth.add_user', 'auth.logout_user',
    'auth.sso_login', 'auth.sso_callback',
}

# Endpoints any *authenticated* user may reach to manage their own account
# (login required, but admin is not).
_AUTH_SELF_SERVICE_ENDPOINTS = {'auth.change_password'}


@auth_bp.before_request
def _restrict_auth_to_admin():
    from flask import request, Response
    if request.endpoint in _AUTH_PUBLIC_ENDPOINTS:
        return
    if request.endpoint in _AUTH_SELF_SERVICE_ENDPOINTS:
        # The global check_login hook already guarantees authentication;
        # just make sure we don't hand an anonymous user through here.
        if flask_login.current_user.is_anonymous:
            abort(403)
        return
    if flask_login.current_user.is_anonymous or not flask_login.current_user.is_admin():
        abort(403)


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and \
           ref_url.netloc == test_url.netloc

# Where to land after login, parked in the session across the redirect to
# the IdP and back. The ``next`` query arg can't survive that round trip:
# the provider only echoes back the state it was given.
_SSO_NEXT_KEY = '_sso_next'
# The raw ID token, kept only when RP-initiated logout is switched on �
# providers want it back as ``id_token_hint`` to end the session cleanly.
_SSO_ID_TOKEN_KEY = '_sso_id_token'


@auth_bp.route('/logout')
def logout_user() -> Response | str:
    """Drop the local session, and optionally the one at the IdP too.

    With ``OIDC_RP_LOGOUT`` off (the default) this is a purely local
    logout: the next SSO sign-in will silently re-authenticate from the
    provider's still-live session, which is usually what people expect
    from a shared institutional login. Turn it on to sign out everywhere.
    """
    id_token = flask.session.pop(_SSO_ID_TOKEN_KEY, None)
    was_sso = (
        not flask_login.current_user.is_anonymous
        and getattr(flask_login.current_user, 'is_sso_linked', False)
    )
    flask_login.logout_user()
    if was_sso:
        provider_logout = end_session_url(
            post_logout_redirect_uri=url_for('auth.login_user', _external=True),
            id_token=id_token,
        )
        if provider_logout:
            return redirect(provider_logout)
    return redirect(request.referrer or url_for('auth.login_user'))


@auth_bp.route('/sso/login')
@public
def sso_login() -> Response | str:
    """Kick off the authorization-code flow at the identity provider."""
    # Validate the attacker-reachable input before anything else, so a
    # hostile ``next`` is rejected on its merits rather than incidentally
    # by whatever the provider config happens to be.
    next_page = request.args.get('next')
    if next_page and not is_safe_url(next_page):
        return abort(400)

    client = get_oidc_client()
    if client is None:
        flash('Single sign-on is not configured for this site.', 'danger')
        return redirect(url_for('auth.login_user'))

    flask.session[_SSO_NEXT_KEY] = next_page or ''

    # ``_external=True`` must produce exactly the URI registered with the
    # provider � behind a TLS-terminating proxy that needs ProxyFix (wired
    # in the app factory) so the scheme comes out https, not http.
    redirect_uri = url_for('auth.sso_callback', _external=True)
    try:
        return client.authorize_redirect(redirect_uri)
    except Exception as exc:  # noqa: BLE001 - Authlib raises a wide family
        # Building the redirect means fetching the provider's discovery
        # document, so everything from a DNS failure to a 503 at the IdP
        # surfaces here rather than at the callback. Unhandled it's a 500,
        # which tells a user nothing and sends them to whoever runs the
        # site. The local password form is entirely unaffected by an IdP
        # outage, so say so — during one, that's the only thing the person
        # reading this can actually act on.
        current_app.logger.warning('OIDC authorization redirect failed: %s', exc)
        flash(
            'Single sign-on is temporarily unavailable. You can still sign '
            'in with your Colony Manager password below.',
            'warning',
        )
        return redirect(url_for('auth.login_user'))


@auth_bp.route('/sso/callback')
@public
def sso_callback() -> Response | str:
    """Complete the flow: exchange the code, map claims onto an account.

    Authlib validates the ``state``, the ID token signature against the
    provider's JWKS, and the issuer/audience/nonce before returning, so
    the claims reaching :func:`resolve_user` are already trustworthy.
    """
    client = get_oidc_client()
    if client is None:
        flash('Single sign-on is not configured for this site.', 'danger')
        return redirect(url_for('auth.login_user'))

    next_page = flask.session.pop(_SSO_NEXT_KEY, '') or None

    try:
        token = client.authorize_access_token()
    except Exception as exc:  # noqa: BLE001 - Authlib raises a wide family
        current_app.logger.warning('OIDC token exchange failed: %s', exc)
        flash('Single sign-on failed. Please try again.', 'danger')
        return redirect(url_for('auth.login_user'))

    # Authlib parses the ID token into ``userinfo`` whenever the scope
    # includes ``openid``; fall back to the userinfo endpoint for the rare
    # provider that returns a thin ID token.
    claims = dict(token.get('userinfo') or {})
    if not claims.get('email'):
        try:
            claims.update(client.userinfo(token=token) or {})
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning('OIDC userinfo lookup failed: %s', exc)

    try:
        user = resolve_user(db.session, claims, oidc_config())
    except SSOError as exc:
        db.session.rollback()
        flash(exc.message, exc.category)
        return redirect(url_for('auth.login_user'))

    if not user.is_active:
        flash(
            'Your account is not yet active. Please contact an administrator.',
            'danger',
        )
        return redirect(url_for('auth.login_user'))

    flask_login.login_user(user)
    if oidc_config().get('rp_logout') and token.get('id_token'):
        flask.session[_SSO_ID_TOKEN_KEY] = token['id_token']
    flash('Logged in successfully.', 'success')
    if next_page and not is_safe_url(next_page):
        return abort(400)
    return redirect(next_page or url_for('main.view_dashboard'))

@auth_bp.route('/login', methods=['GET', 'POST'])
@public
def login_user() -> Response | str:
    # Here we use a class of some kind to represent and validate our
    # client-side form data. For example, WTForms is a library that will
    # handle this for us, and we use a custom LoginForm to validate.
    login_form = UserLoginForm()
    if login_form.validate_on_submit():
        # Login and validate the user.
        # user should be an instance of your `User` class
        user = db.session.scalars(
            select(User).where(User.email == login_form.email.data)
        ).first()
        if user and user.is_active:
            if user.check_password(login_form.password.data):
                flask_login.login_user(user)
                flash('Logged in successfully.', 'success')
                next_page = request.args.get('next')
                if next_page and not is_safe_url(next_page):
                    return abort(400)
                return redirect(next_page or url_for('main.view_dashboard'))
            else:
                flash('Invalid email or password', 'danger')
        else:
            flash('Not authorized to login. Please contact admin.', 'danger')
    return render_template('login.html', login_form=login_form,
                           create_form=UserCreateForm(), active_tab='login',
                           next_page=request.args.get('next'))

@auth_bp.route('/add', methods=['GET', 'POST'])
@public
def add_user() -> Response | str:
    # Self-registration is always open. The first user to register is
    # auto-activated and elevated to admin to bootstrap the system;
    # subsequent accounts are inactive until an admin approves them.
    create_form = UserCreateForm()
    if create_form.validate_on_submit():
        try:
            # Serialize concurrent first-user creates so two simultaneous
            # registrations can't both observe an empty table and both
            # become admin. The advisory lock is released at COMMIT/ROLLBACK.
            db.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('colony_manager.first_user'))")
            )
            is_bootstrap = db.session.scalar(
                select(sqlalchemy.func.count()).select_from(User)
            ) == 0
            user = User(
                first_name=create_form.first_name.data,
                last_name=create_form.last_name.data,
                email=create_form.email.data,
                active=is_bootstrap,
                admin=is_bootstrap,
            )
            user.set_password(create_form.password.data)
            db.session.add(user)
            db.session.commit()
            flash('Account created successfully. Contact admin to approve.', 'success')
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()
            flash('Error creating account', 'danger')
    else:
        flash_form_errors(create_form, 'Error creating account')
    return render_template('login.html', login_form=UserLoginForm(),
                           create_form=create_form, active_tab='create')

@auth_bp.route('/')
def list_users() -> Response | str:
    users = db.session.scalars(select(User)).all()
    return render_template('list_users.html', users=users)

@auth_bp.route('/<int:user_id>/update', methods=['POST'])
def update_user_admin(user_id) -> Response | str:
    if not flask_login.current_user.is_admin():
        flash('Must be admin to update user.', 'danger')
        return redirect(request.referrer or url_for('auth.list_users'))
    user = get_or_404(User, user_id)
    form = UserEditForm()
    if form.validate_on_submit():
        form.populate_obj(user)
        db.session.commit()
        flash(f'Successfully updated user {user.display_name}', 'success')
    else:
        flash_form_errors(form, f'Unable to update user {user.display_name}', 'error')
    return redirect(request.referrer or url_for('auth.list_users'))

@auth_bp.route('/change-password', methods=['GET', 'POST'])
def change_password() -> Response | str:
    """Let the logged-in user change their own password.

    GET renders the modal; POST verifies the current password, enforces
    the complexity rules, and updates the hash. Follows the same full-POST
    modal pattern as ``update_user_admin`` (flash + redirect rather than an
    HTMX swap).
    """
    user = flask_login.current_user
    form = ChangePasswordForm()
    if request.method == 'GET':
        return render_modal(
            form, label='Change Password',
            submit_url=url_for('auth.change_password'),
            submit_label='Update Password',
        )
    if form.validate_on_submit():
        if not user.check_password(form.current_password.data):
            flash('Current password is incorrect.', 'danger')
        elif user.check_password(form.new_password.data):
            flash('New password must be different from the current one.', 'danger')
        else:
            user.set_password(form.new_password.data)
            db.session.commit()
            flash('Password updated successfully.', 'success')
            return redirect(url_for('main.view_dashboard'))
    else:
        flash_form_errors(form, 'Unable to change password')
    return redirect(request.referrer or url_for('main.view_dashboard'))


@auth_bp.route('/<int:user_id>/edit_modal')
def edit_user_modal(user_id) -> Response | str:
    if not flask_login.current_user.is_admin():
        flash('Must be admin to update user.', 'danger')
        return redirect(request.referrer or url_for('auth.list_users'))
    user = get_or_404(User, user_id)
    return render_modal(UserEditForm(obj=user), item=user, label='Edit user',
                        submit_url=url_for('auth.update_user_admin', user_id=user.id))
