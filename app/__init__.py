import gzip
import hashlib
import logging
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config
from app.i18n import LANGUAGES, error_text, resolve_preferences, t
from app.services import formatting
from app.services.forecast import format_rate
from app.store import PHOTO_BUCKET, StoreError, SupabaseStore
from app.supabase_client import Supabase
from app.web import (account, auth, documents, main, movements, notifications, organization, products, reports,
                     stocktake, suppliers, warehouses)
from app.web.session import can, check_csrf, csrf_token, current_org, end_session

logger = logging.getLogger(__name__)


def create_app(config=None, store_factory=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    # Hosting platforms terminate HTTPS at a proxy; trust its X-Forwarded-* headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs full request URLs at INFO; Telegram URLs contain the bot token
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not app.config["SUPABASE_URL"] or not app.config["SUPABASE_PUBLISHABLE_KEY"]:
        logger.warning("SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY are not set — see .env.example")

    client = Supabase(app.config["SUPABASE_URL"] or "http://localhost", app.config["SUPABASE_PUBLISHABLE_KEY"])
    app.extensions["supabase"] = client
    app.extensions["store_factory"] = store_factory or (lambda token, user_id: SupabaseStore(client, token, user_id))

    for module in (auth, main, products, movements, suppliers, stocktake, reports, account,
                   warehouses, organization, documents, notifications):
        app.register_blueprint(module.bp)

    _register_hooks(app)
    _register_template_helpers(app)
    _register_error_handlers(app)
    return app


def _register_hooks(app):
    @app.before_request
    def before_request():
        resolve_preferences()
        check_csrf()

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return _compress(response)


COMPRESSIBLE = ("text/html", "text/css", "text/csv", "application/javascript", "text/javascript",
                "application/json", "image/svg+xml")


def _compress(response):
    """gzip text responses (HTML pages shrink ~6×). Skipped for small bodies and streamed files."""
    if (
        response.direct_passthrough
        or response.status_code < 200 or response.status_code >= 300
        or "Content-Encoding" in response.headers
        or not (response.mimetype or "").startswith(COMPRESSIBLE)
        or "gzip" not in request.headers.get("Accept-Encoding", "")
    ):
        return response
    data = response.get_data()
    if len(data) < 1024:
        return response
    response.set_data(gzip.compress(data, compresslevel=6))
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(response.get_data()))
    response.vary.add("Accept-Encoding")
    return response


def _register_template_helpers(app):
    static_dir = Path(app.static_folder)
    versions = {}

    def static_url(filename):
        """URL with a content hash so the year-long cache is safe after every deploy."""
        if filename not in versions or app.debug:
            try:
                versions[filename] = hashlib.md5((static_dir / filename).read_bytes()).hexdigest()[:10]
            except OSError:
                versions[filename] = "0"
        return url_for("static", filename=filename, v=versions[filename])

    supabase_client = app.extensions["supabase"]

    def photo_url(path):
        return supabase_client.public_url(PHOTO_BUCKET, path) if path else ""

    app.jinja_env.globals.update(t=t, csrf_token=csrf_token, languages=LANGUAGES, can=can,
                                 static_url=static_url, photo_url=photo_url)
    app.jinja_env.filters.update(
        money=formatting.format_money,
        money_short=formatting.format_money_short,
        number=formatting.format_number,
        signed=formatting.format_signed,
        datetime=formatting.format_datetime,
        date=formatting.format_date,
        rate=format_rate,
        pairs=lambda items: [(item, item) for item in items],
        options=lambda rows: [(row["id"], row["name"]) for row in rows],
    )

    @app.context_processor
    def inject_user():
        auth = session.get("auth")
        profile = session.get("profile") or {}
        name = profile.get("full_name") or (auth or {}).get("email") or ""
        initials = "".join(part[0] for part in name.replace("@", " ").split()[:2]).upper() or "Q"
        org = current_org() if auth else None
        return {
            "user": {"email": auth["email"], "name": name, "initials": initials,
                     "company": (org or {}).get("name") or profile.get("company")}
            if auth else None,
            "org": org,
            "orgs": session.get("orgs") or [],
            "lang": g.get("lang", "kk"),
            "theme": g.get("theme", "dark"),
        }


def _register_error_handlers(app):
    @app.errorhandler(StoreError)
    def store_error(error):
        if error.key == "err.forbidden":
            return render_template("error.html", code=403, message=t("err.forbidden")), 403
        if error.key == "err.session_expired":
            end_session()
            flash(t("err.session_expired"), "error")
            return redirect(url_for("auth.login", next=request.path))
        return render_template("error.html", code=503, message=error_text(error)), 503

    @app.errorhandler(400)
    def bad_request(_error):
        return render_template("error.html", code=400, message=t("err.bad_request")), 400

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", code=403, message=t("err.forbidden")), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message=t("err.page_not_found")), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("error.html", code=413, message=t("err.file_too_large")), 413

    @app.errorhandler(500)
    def server_error(_error):
        return render_template("error.html", code=500, message=t("err.server")), 500
