"""Low-stock notifications: a Telegram bot and (optionally) email over SMTP.

Linking a Telegram chat needs no webhook: the user opens t.me/<bot>?start=<code>, and the
site finds that /start message with getUpdates. The daily digest is sent by the
/cron/low-stock endpoint (see README → "Уведомления").
"""

import html
import logging
import math
import smtplib
import time
from email.message import EmailMessage

import httpx

from app.i18n import translate
from app.services import forecast
from app.services.formatting import format_number

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
_bot_cache = {}
_http = httpx.Client(timeout=15.0)


class NotifyError(Exception):
    pass


# ---------------------------------------------------------------- telegram

def _telegram(token, method, payload=None):
    try:
        response = _http.post(f"{TELEGRAM_API}/bot{token}/{method}", json=payload or {})
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise NotifyError(str(error)) from error
    if not data.get("ok"):
        raise NotifyError(data.get("description") or "telegram error")
    return data["result"]


def bot_username(token):
    """Cached for an hour — the name only changes in BotFather."""
    cached = _bot_cache.get(token)
    if cached and cached[1] > time.time():
        return cached[0]
    username = _telegram(token, "getMe")["username"]
    _bot_cache[token] = (username, time.time() + 3600)
    return username


def find_start_chat(token, code):
    """Chat id of the user who sent "/start <code>" to the bot in the last 24 hours."""
    for update in reversed(_telegram(token, "getUpdates", {"allowed_updates": ["message"], "limit": 100})):
        message = update.get("message") or {}
        if (message.get("text") or "").strip() == f"/start {code}":
            return message["chat"]["id"]
    return None


def send_telegram(token, chat_id, text):
    _telegram(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    })


# ---------------------------------------------------------------- email

def email_enabled(config):
    return bool(config.get("SMTP_HOST") and config.get("SMTP_FROM"))


def send_email(config, to, subject, text):
    message = EmailMessage()
    message["From"] = config["SMTP_FROM"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    port = int(config.get("SMTP_PORT") or 587)
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(config["SMTP_HOST"], port, timeout=20)
        else:
            server = smtplib.SMTP(config["SMTP_HOST"], port, timeout=20)
            server.starttls()
        with server:
            if config.get("SMTP_USER"):
                server.login(config["SMTP_USER"], config.get("SMTP_PASSWORD") or "")
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        raise NotifyError(str(error)) from error


# ---------------------------------------------------------------- digest text

def _items_with_reorder(items):
    """Digest items come from SQL with 30-day issued units; add the suggested order."""
    result = []
    for item in items:
        rate = item.get("out_30", 0) / forecast.WINDOW_DAYS
        target = item["min_quantity"] + math.ceil(rate * forecast.COVER_DAYS) if rate else item["min_quantity"] * 2
        days_left = int(item["quantity"] / rate) if rate else None
        result.append({**item, "reorder": max(0, target - item["quantity"]), "days_left": days_left})
    return result


def digest_text(language, organization, items, site_url, limit=25):
    tr = lambda key, **params: translate(language, key, **params)  # noqa: E731
    items = _items_with_reorder(items)
    lines = [f"<b>{html.escape(tr('notify.title'))}</b>", html.escape(organization or ""), ""]
    for item in items[:limit]:
        mark = "🔴" if item["quantity"] == 0 else "🟠"
        line = (f"{mark} <b>{html.escape(item['name'])}</b> <code>{html.escape(item['sku'])}</code>\n"
                f"    {format_number(item['quantity'])} / {format_number(item['min_quantity'])} {html.escape(item['unit'])}")
        if item["days_left"] is not None:
            line += " · " + html.escape(tr("forecast.days", days=item["days_left"]))
        if item["reorder"]:
            line += " · " + html.escape(tr("notify.order", qty=format_number(item["reorder"]), unit=item["unit"]))
        lines.append(line)
    if len(items) > limit:
        lines.append(html.escape(tr("notify.more", count=len(items) - limit)))
    lines += ["", html.escape(tr("notify.footer", count=len(items))), f"{site_url}/products?status=low"]
    return "\n".join(lines)


def digest_plain(language, organization, items, site_url):
    tr = lambda key, **params: translate(language, key, **params)  # noqa: E731
    rows = [tr("notify.title"), organization or "", ""]
    for item in _items_with_reorder(items):
        row = f"• {item['name']} [{item['sku']}] — {item['quantity']} / {item['min_quantity']} {item['unit']}"
        if item["reorder"]:
            row += " · " + tr("notify.order", qty=format_number(item["reorder"]), unit=item["unit"])
        rows.append(row)
    rows += ["", tr("notify.footer", count=len(items)), f"{site_url}/products?status=low"]
    return "\n".join(rows)


def send_digests(entries, config):
    """entries: rows from qoima_low_stock_digest. Returns counters for the cron response."""
    token = config.get("TELEGRAM_BOT_TOKEN")
    site_url = config["SITE_URL"]
    sent = {"telegram": 0, "email": 0, "failed": 0}
    for entry in entries:
        language = entry.get("language") or "kk"
        if token and entry.get("chat_id") and entry.get("notify_telegram"):
            try:
                send_telegram(token, entry["chat_id"], digest_text(language, entry["organization"], entry["items"], site_url))
                sent["telegram"] += 1
            except NotifyError as error:
                logger.warning("Telegram digest failed: %s", error)
                sent["failed"] += 1
        if entry.get("email") and email_enabled(config):
            try:
                send_email(config, entry["email"], translate(language, "notify.subject", count=len(entry["items"])),
                           digest_plain(language, entry["organization"], entry["items"], site_url))
                sent["email"] += 1
            except NotifyError as error:
                logger.warning("Email digest failed: %s", error)
                sent["failed"] += 1
    return sent
