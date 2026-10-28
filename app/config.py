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
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
