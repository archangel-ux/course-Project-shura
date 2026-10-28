import logging

import httpx
from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for

from app.i18n import error_text, t
from app.services.validators import ValidationError, optional_text, parse_email, parse_password
from app.store import StoreError
from app.supabase_client import SupabaseError
from app.web.session import current_auth, end_session, get_store, load_organization, safe_next, start_session, supabase

logger = logging.getLogger(__name__)
bp = Blueprint("auth", __name__)

AUTH_ERRORS = {
    "invalid_credentials": "err.invalid_login",
    "email_not_confirmed": "err.email_not_confirmed",
    "user_already_exists": "err.user_exists",
    "email_exists": "err.user_exists",
    "weak_password": "err.weak_password",
    "over_email_send_rate_limit": "err.rate_limit",
    "over_request_rate_limit": "err.rate_limit",
    "same_password": "err.same_password",
    "email_address_invalid": "err.email_invalid",
    "signup_disabled": "err.signup_disabled",
    "session_not_found": "err.session_expired",
    "bad_jwt": "err.session_expired",
}


def auth_error_key(error):
    if error.code in AUTH_ERRORS:
        return AUTH_ERRORS[error.code]
    message = error.message.lower()
    if "not confirmed" in message:
        return "err.email_not_confirmed"
    if "invalid login" in message or error.code == "invalid_grant":
        return "err.invalid_login"
    if error.status == 429:
        return "err.rate_limit"
    logger.warning("Unhandled auth error: %s", error)
    return "err.auth"


def callback_url():
    return current_app.config["SITE_URL"] + url_for("auth.callback")


def load_profile():
    """Copy the profile into the session so every page knows the user's language and theme."""
    try:
        profile = get_store().get_profile()
    except StoreError as error:
        logger.warning("Could not load profile: %s", error.key)
        profile = {}
    session["profile"] = {
        "full_name": profile.get("full_name") or "",
        "company": profile.get("company") or "",
        "phone": profile.get("phone") or "",
        "language": profile.get("language") or g.lang,
        "theme": profile.get("theme") or g.theme,
        "telegram_chat_id": profile.get("telegram_chat_id"),
        "notify_telegram": profile.get("notify_telegram", True),
        "notify_email": profile.get("notify_email", False),
    }
    load_organization()


def _auth_call(action):
    """Run a Supabase auth call; return (result, error message)."""
    try:
        return action(), None
    except ValidationError as error:
        return None, error_text(error)
    except SupabaseError as error:
        return None, t(auth_error_key(error))
    except httpx.HTTPError:
        return None, t("err.network")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_auth():
        return redirect(url_for("main.dashboard"))
    email, error = "", None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        payload, error = _auth_call(lambda: supabase().sign_in(parse_email(email), password))
        if payload:
            start_session(payload)
            load_profile()
            return redirect(safe_next(request.args.get("next")))
    return render_template("auth/login.html", email=email, error=error)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_auth():
        return redirect(url_for("main.dashboard"))
    form, error = {}, None
    if request.method == "POST":
        form = request.form

        def sign_up():
            full_name = optional_text(form.get("full_name"), "field.full_name", max_length=120)
            company = optional_text(form.get("company"), "field.company", max_length=120)
            email = parse_email(form.get("email"))
            password = parse_password(form.get("password"), form.get("password_confirm"))
            metadata = {"full_name": full_name, "company": company, "language": g.lang}
            payload = supabase().sign_up(email, password, metadata, callback_url())
            if payload.get("access_token"):
                return payload
            # Accounts are confirmed instantly (see schema.sql), so sign in right away.
            return supabase().sign_in(email, password)

        payload, error = _auth_call(sign_up)
        if payload is not None:
            start_session(payload)
            load_profile()
            flash(t("msg.welcome"), "success")
            return redirect(safe_next(request.args.get("next")))
    return render_template("auth/register.html", form=form, error=error)


@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    email, error = "", None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        result, error = _auth_call(lambda: supabase().recover(parse_email(email), callback_url()) or True)
        if result:
            return render_template("auth/check_email.html", email=email, reason="recovery")
    return render_template("auth/forgot.html", email=email, error=error)


@bp.route("/auth/callback")
def callback():
    """Supabase email links land here with tokens in the URL fragment; JS posts them to /auth/session."""
    return render_template("auth/callback.html")


@bp.route("/auth/session", methods=["POST"])
def accept_session():
    data = request.get_json(silent=True) or {}
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if not access_token or not refresh_token:
        return jsonify(error=t("err.link_invalid")), 400
    try:
        user = supabase().get_user(access_token)
    except (SupabaseError, httpx.HTTPError):
        return jsonify(error=t("err.link_invalid")), 400

    start_session({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": int(data.get("expires_in") or 3600),
        "user": user,
    })
    load_profile()
    if data.get("type") == "recovery":
        return jsonify(redirect=url_for("account.reset_password"))
    flash(t("msg.email_confirmed"), "success")
    return jsonify(redirect=url_for("main.dashboard"))


@bp.route("/logout", methods=["POST"])
def logout():
    auth = session.get("auth")
    if auth:
        try:
            supabase().sign_out(auth["access_token"])
        except (SupabaseError, httpx.HTTPError):
            pass
    end_session()
    return redirect(url_for("auth.login"))
