from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, Regexp

# Shared password policy – change here to update everywhere
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class RegisterForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(min=3, max=64),
            Regexp(r'^[A-Za-z0-9_-]+$',
                   message="Letters, numbers, underscores, and hyphens only."),
        ]
    )
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=150)])
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=MIN_PASSWORD_LENGTH, max=MAX_PASSWORD_LENGTH,
                   message=f"Password must be at least {MIN_PASSWORD_LENGTH} characters."),
        ]
    )
    confirm = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")]
    )
    submit = SubmitField("Create Account")


class LoginForm(FlaskForm):
    username = StringField("Username or Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me")
    submit = SubmitField("Sign In")


class ChangePasswordForm(FlaskForm):
    """Reuse the same password validation for profile changes."""
    current_password = PasswordField("Current Password", validators=[DataRequired()])
    new_password = PasswordField(
        "New Password",
        validators=[
            DataRequired(),
            Length(min=MIN_PASSWORD_LENGTH, max=MAX_PASSWORD_LENGTH,
                   message=f"Password must be at least {MIN_PASSWORD_LENGTH} characters."),
        ]
    )
    confirm_new = PasswordField(
        "Confirm New Password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match")]
    )
    submit = SubmitField("Update Password")