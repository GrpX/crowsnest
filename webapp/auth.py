import os
import secrets
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user

REPO_DIR = Path(__file__).parent.parent.resolve()
login_manager = LoginManager()


class _Admin(UserMixin):
    id = "admin"


_user = _Admin()


def get_password() -> str:
    pwd = os.environ.get("CROWSNEST_WEBAPP_PASSWORD", "")
    if pwd:
        return pwd
    pwd = secrets.token_urlsafe(16)
    env_path = REPO_DIR / ".env"
    with open(env_path, "a") as f:
        f.write(f"\nCROWSNEST_WEBAPP_PASSWORD={pwd}\n")
    os.environ["CROWSNEST_WEBAPP_PASSWORD"] = pwd
    print(f"[CROWSNEST webapp] Password generada y guardada en .env: {pwd}")
    return pwd


def _get_secret_key() -> str:
    key = os.environ.get("CROWSNEST_WEBAPP_SECRET_KEY", "")
    if key:
        return key
    key = secrets.token_hex(32)
    env_path = REPO_DIR / ".env"
    with open(env_path, "a") as f:
        f.write(f"\nCROWSNEST_WEBAPP_SECRET_KEY={key}\n")
    os.environ["CROWSNEST_WEBAPP_SECRET_KEY"] = key
    return key


SECRET_KEY = _get_secret_key()


def init_auth(app):
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(uid):
        return _user if uid == "admin" else None


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password", "") == get_password():
            login_user(_user, remember=True)
            return redirect(url_for("dashboard"))
        flash("Contraseña incorrecta")
    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
