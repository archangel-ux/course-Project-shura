import httpx
from flask import Blueprint, current_app, flash, make_response, redirect, render_template, request, session, url_for

from app.i18n import LANGUAGES, THEMES, error_text, t
from app.services import notify
from app.services.validators import ValidationError, optional_text, parse_email, parse_password
from app.store import StoreError
from app.supabase_client import SupabaseError
from app.web.auth import auth_error_key, callback_url
from app.web.session import current_auth, get_store, login_required, supabase

bp = Blueprint("account", __name__, url_prefix="/account")

YEAR_SECONDS = 60 * 60 * 24 * 365


def _render(errors=None, status=200):
    return render_template(
        "account.html", profile=session.get("profile") or {}, email=current_auth()["email"],
        languages=LANGUAGES, themes=THEMES, errors=errors or {},
        telegram_enabled=bool(current_app.config.get("TELEGRAM_BOT_TOKEN")),
        email_enabled=notify.email_enabled(current_app.config),
        telegram_link=session.get("telegram_link"),
    ), status


@bp.route("/")
@login_required
def index():
    return _render()


@bp.route("/profile", methods=["POST"])
@login_required
def profile():
    try:
        data = {
            "full_name": optional_text(request.form.get("full_name"), "field.full_name", max_length=120),
            "company": optional_text(request.form.get("company"), "field.company", max_length=120),
            "phone": optional_text(request.form.get("phone"), "field.phone", max_length=40),
        }
        get_store().update_profile(data)
    except (ValidationError, StoreError) as error:
        return _render({"profile": error_text(error)}, 400)
    session["profile"] = {**(session.get("profile") or {}), **data}
    flash(t("msg.profile_saved"), "success")
    return redirect(url_for("account.index"))


@bp.route("/preferences", methods=["POST"])
@login_required
def preferences():
    language = request.form.get("language")
    theme = request.form.get("theme")
    if language not in LANGUAGES or theme not in THEMES:
        return _render({"preferences": t("err.invalid_choice")}, 400)
    try:
        get_store().update_profile({"language": language, "theme": theme})
    except StoreError as error:
        return _render({"preferences": error_text(error)}, 400)
    session["profile"] = {**(session.get("profile") or {}), "language": language, "theme": theme}
    flash(t("msg.preferences_saved"), "success")
    response = make_response(redirect(url_for("account.index")))
    response.set_cookie("lang", language, max_age=YEAR_SECONDS, samesite="Lax")
    response.set_cookie("theme", theme, max_age=YEAR_SECONDS, samesite="Lax")
    return response


def _update_user(attributes, section, redirect_to=None):
    try:
        supabase().update_user(current_auth()["access_token"], attributes, redirect_to)
    except SupabaseError as error:
        return _render({section: t(auth_error_key(error))}, 400)
    except httpx.HTTPError:
        return _render({section: t("err.network")}, 400)
    return None


@bp.route("/email", methods=["POST"])
@login_required
def email():
    try:
        new_email = parse_email(request.form.get("email"))
    except ValidationError as error:
        return _render({"email": error_text(error)}, 400)
    if new_email == current_auth()["email"]:
        return _render({"email": t("err.same_email")}, 400)
    failed = _update_user({"email": new_email}, "email", callback_url())
    if failed:
        return failed
    flash(t("msg.email_change_sent", email=new_email), "success")
    return redirect(url_for("account.index"))


@bp.route("/password", methods=["POST"])
@login_required
def password():
    try:
        new_password = parse_password(request.form.get("password"), request.form.get("password_confirm"))
    except ValidationError as error:
        return _render({"password": error_text(error)}, 400)
    failed = _update_user({"password": new_password}, "password")
    if failed:
        return failed
    flash(t("msg.password_changed"), "success")
    return redirect(url_for("account.index"))


@bp.route("/reset-password", methods=["GET", "POST"])
@login_required
def reset_password():
    """Reached from the password-recovery email link."""
    error = None
    if request.method == "POST":
        try:
            new_password = parse_password(request.form.get("password"), request.form.get("password_confirm"))
            supabase().update_user(current_auth()["access_token"], {"password": new_password})
        except ValidationError as exc:
            error = error_text(exc)
        except SupabaseError as exc:
            error = t(auth_error_key(exc))
        except httpx.HTTPError:
            error = t("err.network")
        else:
            flash(t("msg.password_changed"), "success")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/reset_password.html", error=error)
