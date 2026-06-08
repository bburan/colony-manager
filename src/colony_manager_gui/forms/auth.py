import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError


def validate_password_complexity(form, field):
    password = field.data
    if (len(password) < 8
            or not re.search(r'[A-Z]', password)
            or not re.search(r'[a-z]', password)
            or not re.search(r'\d', password)
            or not re.search(r'[!@#$%^&*(),.?":{}|<>]', password)):
        raise ValidationError(
            'Password must be at least 8 characters long and include '
            'uppercase, lowercase, numbers, and special characters.'
        )


class UserLoginForm(FlaskForm):
    email = StringField('Email')
    password = PasswordField('Password')


class UserCreateForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8),
        validate_password_complexity,
    ])
    confirm_password = PasswordField(
        'Password (repeat)',
        validators=[EqualTo('password', message='Passwords must match')],
    )


class UserEditForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    active = BooleanField('Active')
