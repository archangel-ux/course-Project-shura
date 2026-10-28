"""Signed-in state kept in the Flask session cookie, plus CSRF protection."""

import hmac
import logging
import secrets
import time
from functools import wraps

import httpx
from flask import abort, current_app, g, redirect, request, session, url_for

from app.supabase_client import SupabaseError

logger = logging.getLogger(__name__)

REFRESH_MARGIN_SECONDS = 60


def supabase():
    return current_app.extensions["supabase"]


def start_session(token_payload):
    user = token_payload.get("user") or {}
    expires_at = token_payload.get("expires_at") or time.time() + int(token_payload.get("expires_in", 3600))
    session.permanent = True
    session["auth"] = {
        "access_token": token_payload["access_token"],
        "refresh_token": token_payload["refresh_token"],
        "expires_at": int(expires_at),
        "user_id": user.get("id"),
        "email": user.get("email"),
    }


def end_session():
    keep = {key: session[key] for key in ("csrf",) if key in session}
    session.clear()
    session.update(keep)


def current_auth():
    """Valid auth data or None. Refreshes the access token shortly before it expires."""
    auth = session.get("auth")
    if not auth:
        return None
    if auth["expires_at"] - REFRESH_MARGIN_SECONDS > time.time():
        return auth
    try:
        payload = supabase().refresh(auth["refresh_token"])
    except (SupabaseError, httpx.HTTPError) as error:
        logger.info("Session refresh failed: %s", error)
        end_session()
        return None
    start_session(payload)
    return session["auth"]


def get_store():
    if "store" not in g:
        auth = current_auth()
        g.store = current_app.extensions["store_factory"](auth["access_token"], auth["user_id"])
    return g.store


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_auth() is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def safe_next(target, fallback="main.dashboard"):
    """Only allow same-site relative redirects."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for(fallback)


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("csrf") or ""
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400)
