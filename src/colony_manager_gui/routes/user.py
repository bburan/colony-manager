import sqlalchemy
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user
from app import db
from app.routes.util import flash_form_errors
from app.forms import UserLoginForm, UserCreateForm
from app.models import User

auth_bp = Blueprint('auth', __name__)

def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and \
           ref_url.netloc == test_url.netloc

@auth_bp.route('/login', methods=['GET', 'POST'])
def logout():

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Here we use a class of some kind to represent and validate our
    # client-side form data. For example, WTForms is a library that will
    # handle this for us, and we use a custom LoginForm to validate.
    form = UserLoginForm()
    if form.validate_on_submit():
        # Login and validate the user.
        # user should be an instance of your `User` class
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.can_login():
            if user.check_password(form.password.data):
                login_user(user)
                flash('Logged in successfully.', 'success')
                next_page = request.args.get('next')
                if next_page and not is_safe_url(next_page):
                    return abort(400)
                return redirect(next_page or url_for('main.view_dashboard'))
            else:
                flash('Invalid email or password', 'danger')
        else:
            flash('Not authorized to login. Please contact admin.', 'danger')
    return render_template('login.html', form=form)

@auth_bp.route('/create', methods=['GET', 'POST'])
def create():
    form = UserCreateForm()
    if form.validate_on_submit():
        try:
            user = User(email=form.email.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash('Account created successfully. Contact admin to approve.', 'success')
        except sqlalchemy.exc.IntegrityError:
            flash('Error creating account', 'danger')
    else:
        flash_form_errors(form, 'Error creating account')
    return render_template('login.html', form=form)

@auth_bp.route('/')
def list_users():
    users = User.query.all()
    return render_template('list_users.html', users=users)

@auth_bp.route('/<int:auth_id>')
def view_user(auth_id):
    user = User.query.get_or_404(auth_id)
    return render_template('view_user.html', user=user)
