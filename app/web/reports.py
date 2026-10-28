from datetime import date, datetime, timedelta

from flask import Blueprint, Response, render_template, request

from app.i18n import t
from app.services import analytics, csv_io, inventory
from app.services.formatting import LOCAL_TZ
from app.web.session import get_store, login_required

bp = Blueprint("reports", __name__, url_prefix="/reports")

PERIODS = (7, 30, 90, 365)


def _period():
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30
    return days if days in PERIODS else 30


@bp.route("/")
@login_required
def index():
    store = get_store()
    days = _period()
    products = store.list_products()
    movements = store.list_movements(since=datetime.now(LOCAL_TZ) - timedelta(days=days))
    totals = analytics.movement_totals(movements)
    return render_template(
        "reports.html",
        days=days, periods=PERIODS,
        summary=inventory.summary(products),
        categories=analytics.category_breakdown(products),
        totals=totals,
        top_outflow=analytics.top_outflow(movements, limit=8),
    )


def _csv_response(content, prefix):
    return Response(
        content, mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={prefix}_{date.today():%Y-%m-%d}.csv"},
    )


@bp.route("/products.csv")
@login_required
def products_csv():
    return _csv_response(csv_io.products_csv(get_store().list_products(), t), "qoima_products")


@bp.route("/movements.csv")
@login_required
def movements_csv():
    days = request.args.get("days")
    since = None
    if days and days.isdigit() and int(days) in PERIODS:
        since = datetime.now(LOCAL_TZ) - timedelta(days=int(days))
    return _csv_response(csv_io.movements_csv(get_store().list_movements(since=since), t), "qoima_movements")
