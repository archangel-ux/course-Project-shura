from datetime import datetime, timedelta

from flask import Blueprint, g, make_response, redirect, render_template, request, session

from app.i18n import LANGUAGES, THEMES
from app.services import analytics, forecast, inventory
from app.services.formatting import LOCAL_TZ
from app.store import StoreError, parallel
from app.web.session import get_store, login_required, safe_next

bp = Blueprint("main", __name__)

YEAR_SECONDS = 60 * 60 * 24 * 365


@bp.route("/")
@login_required
def dashboard():
    store = get_store()
    now = datetime.now(LOCAL_TZ)
    # independent requests run side by side: the page waits for the slowest, not the sum
    products, month_movements, recent, warehouses, stock = parallel(
        store.list_products,
        lambda: store.list_movements(since=now - timedelta(days=30)),
        lambda: store.list_movements(limit=8),
        store.list_warehouses,
        store.list_stock,
    )

    series, peak = analytics.chart_geometry(analytics.daily_flow(month_movements, now.date(), days=14))
    month_totals = analytics.movement_totals(month_movements)
    forecasts = forecast.forecast_all(products, month_movements, now)
    low = inventory.low_stock(products)[:6]
    return render_template(
        "dashboard.html",
        summary=inventory.summary(products),
        low_stock=[{**p, "forecast": forecasts.get(p["id"])} for p in low],
        recent=recent,
        series=series,
        peak=peak,
        month_in=month_totals["IN"][1],
        month_out=month_totals["OUT"][1],
        top_outflow=analytics.top_outflow(month_movements),
        status=analytics.stock_status(products),
        running_out=[row for row in forecast.forecast_rows(products, forecasts, limit=5) if row["days_left"] is not None],
        warehouses=inventory.warehouse_summary(warehouses, products, stock) if len(warehouses) > 1 else [],
        has_products=bool(products),
    )


@bp.route("/preferences", methods=["POST"])
def preferences():
    """Switch language or theme. Saved to a cookie, and to the profile when signed in."""
    changes = {}
    if request.form.get("language") in LANGUAGES:
        changes["language"] = request.form["language"]
    if request.form.get("theme") in THEMES:
        changes["theme"] = request.form["theme"]

    if changes and session.get("auth"):
        profile = dict(session.get("profile") or {})
        profile.update(changes)
        session["profile"] = profile
        try:
            get_store().update_profile(changes)
        except StoreError:
            pass  # the cookie still keeps the choice for this browser

    response = make_response(redirect(safe_next(request.form.get("next"))))
    if "language" in changes:
        response.set_cookie("lang", changes["language"], max_age=YEAR_SECONDS, samesite="Lax")
    if "theme" in changes:
        response.set_cookie("theme", changes["theme"], max_age=YEAR_SECONDS, samesite="Lax")
    return response


@bp.route("/healthz")
def healthz():
    return {"status": "ok"}
