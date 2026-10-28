"""Telegram linking, notification settings and the daily low-stock cron endpoint."""

import hmac
import logging
import secrets

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, request, session, url_for

from app.i18n import t
from app.services import inventory, notify
from app.supabase_client import SupabaseError
from app.web.session import current_org, get_store, login_required, supabase

logger = logging.getLogger(__name__)
bp = Blueprint("notifications", __name__)


def _token():
    return current_app.config.get("TELEGRAM_BOT_TOKEN") or ""


def _back():
    return redirect(url_for("account.index") + "#notifications")


def _save_profile(changes):
    get_store().update_profile(changes)
    session["profile"] = {**(session.get("profile") or {}), **changes}


@bp.route("/account/telegram/start", methods=["POST"])
@login_required
def telegram_start():
    if not _token():
        flash(t("err.telegram_off"), "error")
        return _back()
    try:
        username = notify.bot_username(_token())
    except notify.NotifyError as error:
        logger.warning("Telegram getMe failed: %s", error)
        flash(t("err.telegram"), "error")
        return _back()
    code = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12]
    session["telegram_link"] = {"code": code, "url": f"https://t.me/{username}?start={code}", "bot": username}
    return _back()


@bp.route("/account/telegram/check", methods=["POST"])
@login_required
def telegram_check():
    """Called by the page every few seconds (and by the 'Check' button without JS)."""
    link = session.get("telegram_link")
    wants_json = request.accept_mimetypes.best == "application/json"
    if not link or not _token():
        return jsonify(linked=False) if wants_json else _back()
    try:
        chat_id = notify.find_start_chat(_token(), link["code"])
    except notify.NotifyError as error:
        logger.warning("Telegram getUpdates failed: %s", error)
        chat_id = None
    if chat_id is None:
        if wants_json:
            return jsonify(linked=False)
        flash(t("err.telegram_not_found"), "error")
        return _back()

    _save_profile({"telegram_chat_id": chat_id, "notify_telegram": True})
    session.pop("telegram_link", None)
    try:
        notify.send_telegram(_token(), chat_id, t("notify.linked", org=(current_org() or {}).get("name", "")))
    except notify.NotifyError:
        pass
    flash(t("msg.telegram_linked"), "success")
    return jsonify(linked=True, redirect=url_for("account.index") + "#notifications") if wants_json else _back()


@bp.route("/account/telegram/unlink", methods=["POST"])
@login_required
def telegram_unlink():
    _save_profile({"telegram_chat_id": None})
    session.pop("telegram_link", None)
    flash(t("msg.telegram_unlinked"), "success")
    return _back()


@bp.route("/account/notifications", methods=["POST"])
@login_required
def settings():
    _save_profile({
        "notify_telegram": bool(request.form.get("notify_telegram")),
        "notify_email": bool(request.form.get("notify_email")) and notify.email_enabled(current_app.config),
    })
    flash(t("msg.preferences_saved"), "success")
    return _back()


@bp.route("/account/notifications/test", methods=["POST"])
@login_required
def test():
    """Send the current low-stock list right now to this user's channels."""
    profile = session.get("profile") or {}
    products = get_store().list_products()
    items = [{**p, "out_30": 0} for p in inventory.low_stock(products)]
    if not items:
        flash(t("msg.digest_nothing"), "success")
        return _back()
    org_name = (current_org() or {}).get("name", "")
    config = current_app.config
    sent = 0
    try:
        if profile.get("telegram_chat_id") and _token():
            notify.send_telegram(_token(), profile["telegram_chat_id"],
                                 notify.digest_text(profile.get("language") or "kk", org_name, items, config["SITE_URL"]))
            sent += 1
        if profile.get("notify_email") and notify.email_enabled(config):
            notify.send_email(config, session["auth"]["email"], t("notify.subject", count=len(items)),
                              notify.digest_plain(profile.get("language") or "kk", org_name, items, config["SITE_URL"]))
            sent += 1
    except notify.NotifyError as error:
        logger.warning("Test digest failed: %s", error)
        flash(t("err.telegram"), "error")
        return _back()
    flash(t("msg.digest_sent") if sent else t("err.no_channel"), "success" if sent else "error")
    return _back()


@bp.route("/cron/low-stock", methods=["GET", "POST"])
def cron_low_stock():
    """Daily digest. Call with header 'X-Cron-Secret: <CRON_SECRET>' (or ?key=...)."""
    expected = current_app.config.get("CRON_SECRET") or ""
    sent_key = request.headers.get("X-Cron-Secret") or request.args.get("key") or ""
    if not expected or not hmac.compare_digest(sent_key, expected):
        abort(403)
    try:
        entries = supabase().rpc("qoima_low_stock_digest", None, {"p_secret": expected}) or []
    except SupabaseError as error:
        logger.error("Digest query failed: %s", error)
        return jsonify(error="digest query failed"), 502
    result = notify.send_digests(entries, current_app.config)
    logger.info("Low-stock digest: %s", result)
    return jsonify(recipients=len(entries), **result)
