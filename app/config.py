import os
import secrets

from dotenv import load_dotenv

load_dotenv()


class Config:
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
    SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    # Public address of the site; used in confirmation / password-reset email links.
    SITE_URL = os.environ.get("SITE_URL", "http://localhost:5000").rstrip("/")

    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_NAME = "qoima_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = SITE_URL.startswith("https://")
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30
    # Send the cookie only when the session changes: pages load in parallel (prefetch), and a
    # late response re-sending an older cookie must not undo a newer change.
    SESSION_REFRESH_EACH_REQUEST = False
    # product photos up to 5 MB plus form overhead
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024
    # static URLs carry a content hash (see static_url), so browsers may cache them for a year
    SEND_FILE_MAX_AGE_DEFAULT = 60 * 60 * 24 * 365

    # Low-stock notifications. The bot token is a secret: keep it in .env / hosting settings only.
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    # Must equal qoima_private.settings 'cron_secret' in the database (see README).
    CRON_SECRET = os.environ.get("CRON_SECRET", "")
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = os.environ.get("SMTP_PORT", "587")
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "")
