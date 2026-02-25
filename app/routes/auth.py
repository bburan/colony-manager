import sqlalchemy
from flask import Blueprint, render_template, request, redirect, url_for, flash
import flask_login
from app import db
from app.routes.util import flash_form_errors
from app.forms import UserLoginForm, UserCreateForm, UserEditForm
from app.models import User

auth_bp = Blueprint('auth', __name__)

def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and \
           ref_url.netloc == test_url.netloc

@auth_bp.route('/logout')
def logout_user():
    flask_login.logout_user()
    return redirect(request.referrer or url_for('auth.login_user'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login_user():
    # Here we use a class of some kind to represent and validate our
    # client-side form data. For example, WTForms is a library that will
    # handle this for us, and we use a custom LoginForm to validate.
    login_form = UserLoginForm()
    if login_form.validate_on_submit():
        # Login and validate the user.
        # user should be an instance of your `User` class
        user = User.query.filter_by(email=login_form.email.data).first()
        if user and user.is_active():
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
                           create_form=UserCreateForm())

@auth_bp.route('/add', methods=['GET', 'POST'])
def add_user():
    create_form = UserCreateForm()
    if create_form.validate_on_submit():
        try:
            # Set first user to active by default. All other users must be
            # approved by the active user.
            first_user = User.query.count() == 0
            user = User(
                first_name=create_form.first_name.data,
                last_name=create_form.last_name.data,
                email=create_form.email.data,
                active=first_user,
                admin=first_user,
            )
            user.set_password(create_form.password.data)
            db.session.add(user)
            db.session.commit()
            flash('Account created successfully. Contact admin to approve.', 'success')
        except sqlalchemy.exc.IntegrityError:
            flash('Error creating account', 'danger')
    else:
        flash_form_errors(create_form, 'Error creating account')
    return render_template('login.html', login_form=UserLoginForm(),
                           create_form=create_form)

@auth_bp.route('/')
def list_users():
    users = User.query.all()
    return render_template('list_users.html', users=users)

@auth_bp.route('/<int:user_id>')
def view_user(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('view_user.html', user=user)

@auth_bp.route('/<int:user_id>/update', methods=['POST'])
def update_user_admin(user_id):
    if not flask_login.current_user.is_admin():
        flash('Must be admin to update user.', 'danger')
        return redirect(request.referrer or url_for('auth.list_users'))
    user = User.query.get_or_404(user_id)
    form = UserEditForm()
    if form.validate_on_submit():
        form.populate_obj(user)
        db.session.commit()
        flash(f'Successfully updated user {user.display_name}', 'success')
    else:
        flash_form_errors(form, f'Unable to update user {user.display_name}', 'error')
    return redirect(request.referrer or url_for('auth.list_users'))

@auth_bp.route('/<int:user_id>/edit_modal')
def edit_user_modal(user_id):
    if not flask_login.current_user.is_admin():
        flash('Must be admin to update user.', 'danger')
        return redirect(request.referrer or url_for('auth.list_users'))
    user = User.query.get_or_404(user_id)
    form = UserEditForm(obj=user)
    return render_template('partials/form_modal.html', form=form, item=user, label=f'Edit user', submit_url=url_for('auth.update_user_admin', user_id=user.id))
