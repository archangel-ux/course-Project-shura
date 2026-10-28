import logging

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config
from app.i18n import LANGUAGES, error_text, resolve_preferences, t
from app.services import formatting
from app.store import StoreError, SupabaseStore
from app.supabase_client import Supabase
from app.web import account, auth, main, movements, products, reports, stocktake, suppliers
from app.web.session import check_csrf, csrf_token, end_session

logger = logging.getLogger(__name__)


def create_app(config=None, store_factory=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    # Hosting platforms terminate HTTPS at a proxy; trust its X-Forwarded-* headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not app.config["SUPABASE_URL"] or not app.config["SUPABASE_PUBLISHABLE_KEY"]:
        logger.warning("SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY are not set — see .env.example")

    client = Supabase(app.config["SUPABASE_URL"] or "http://localhost", app.config["SUPABASE_PUBLISHABLE_KEY"])
    app.extensions["supabase"] = client
    app.extensions["store_factory"] = store_factory or (lambda token, user_id: SupabaseStore(client, token, user_id))

    for module in (auth, main, products, movements, suppliers, stocktake, reports, account):
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
        return response


def _register_template_helpers(app):
    app.jinja_env.globals.update(t=t, csrf_token=csrf_token, languages=LANGUAGES)
    app.jinja_env.filters.update(
        money=formatting.format_money,
        money_short=formatting.format_money_short,
        number=formatting.format_number,
        signed=formatting.format_signed,
        datetime=formatting.format_datetime,
        date=formatting.format_date,
    )

    @app.context_processor
    def inject_user():
        auth = session.get("auth")
        profile = session.get("profile") or {}
        name = profile.get("full_name") or (auth or {}).get("email") or ""
        initials = "".join(part[0] for part in name.replace("@", " ").split()[:2]).upper() or "Q"
        return {
            "user": {"email": auth["email"], "name": name, "initials": initials, "company": profile.get("company")}
            if auth else None,
            "lang": g.get("lang", "kk"),
            "theme": g.get("theme", "dark"),
        }


def _register_error_handlers(app):
    @app.errorhandler(StoreError)
    def store_error(error):
        if error.key == "err.session_expired":
            end_session()
            flash(t("err.session_expired"), "error")
            return redirect(url_for("auth.login", next=request.path))
        return render_template("error.html", code=503, message=error_text(error)), 503

    @app.errorhandler(400)
    def bad_request(_error):
        return render_template("error.html", code=400, message=t("err.bad_request")), 400

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message=t("err.page_not_found")), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("error.html", code=413, message=t("err.file_too_large")), 413

    @app.errorhandler(500)
    def server_error(_error):
        return render_template("error.html", code=500, message=t("err.server")), 500
