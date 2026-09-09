from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import or_
from urllib.parse import urlparse
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, limiter
from models import User
from app.auth.forms import RegisterForm, LoginForm

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# Dummy hash for timing‑side‑channel defence (same cost as real bcrypt)
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing")


def _safe_next_url(next_url):
    """Return a safe redirect URL or fallback to dashboard."""
    if not next_url:
        return url_for("main.dashboard")
    # reject absolute URLs (including protocol‑relative)
    if urlparse(next_url).netloc != "":
        return url_for("main.dashboard")
    return next_url


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("6 per minute")  # tighter limit for bot mitigation
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegisterForm()
    if form.validate_on_submit():
        existing = User.query.filter(
            or_(User.username == form.username.data, User.email == form.email.data)
        ).first()
        if existing:
            flash("Username or email already taken.", "danger")
        else:
            user = User(username=form.username.data.strip(), email=form.email.data.strip().lower())
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash("Account created! Please sign in.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("6 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        ident = form.username.data.strip()
        user = User.query.filter(or_(User.username == ident, User.email == ident.lower())).first()

        # Timing‑side‑channel defence: always run a hash check, even for nonexistent users
        ok = False
        if user:
            ok = user.check_password(form.password.data)
        else:
            # same cost as a real check, so timing doesn't reveal existence
            check_password_hash(_DUMMY_HASH, form.password.data)
            ok = False

        if ok:
            login_user(user, remember=form.remember.data)
            next_page = request.args.get("next")
            safe_next = _safe_next_url(next_page)
            flash(f"Welcome back, {user.username}!", "success")
            return redirect(safe_next)
        flash("Invalid credentials.", "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("main.index"))