from datetime import date, datetime, timedelta

from flask import Blueprint, Response, render_template, request

from app.i18n import t
from app.services import analytics, csv_io, forecast, inventory, pdf
from app.services.formatting import LOCAL_TZ, parse_timestamp
from app.store import parallel
from app.web.documents import pdf_response, requisites_loader
from app.web.session import get_store, permission_required

bp = Blueprint("reports", __name__, url_prefix="/reports")

PERIODS = (7, 30, 90, 365)


def _period():
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30
    return days if days in PERIODS else 30


@bp.route("/")
@permission_required("reports")
def index():
    store = get_store()
    days = _period()
    now = datetime.now(LOCAL_TZ)
    window = max(days, forecast.WINDOW_DAYS)
    products, movements, warehouses, stock = parallel(
        store.list_products,
        lambda: store.list_movements(since=now - timedelta(days=window)),
        store.list_warehouses, store.list_stock,
    )
    period_start = now - timedelta(days=days)
    in_period = [m for m in movements if parse_timestamp(m["created_at"]) >= period_start]
    totals = analytics.movement_totals(in_period)
    categories = analytics.category_breakdown(products)
    series, peak = analytics.chart_geometry(analytics.flow_buckets(in_period, now.date(), days))
    forecasts = forecast.forecast_all(products, movements, now)
    return render_template(
        "reports.html",
        days=days, periods=PERIODS,
        summary=inventory.summary(products),
        categories=categories,
        category_chart=analytics.category_donut(categories),
        totals=totals,
        series=series, peak=peak,
        abc=analytics.abc_analysis(products, in_period),
        forecast_rows=forecast.forecast_rows(products, forecasts, limit=12),
        warehouses=inventory.warehouse_summary(warehouses, products, stock),
        top_outflow=analytics.top_outflow(in_period, limit=8),
    )


def _csv_response(content, prefix):
    return Response(
        content, mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={prefix}_{date.today():%Y-%m-%d}.csv"},
    )


@bp.route("/products.csv")
@permission_required("reports")
def products_csv():
    return _csv_response(csv_io.products_csv(get_store().list_products(), t), "qoima_products")


@bp.route("/movements.csv")
@permission_required("reports")
def movements_csv():
    days = request.args.get("days")
    since = None
    if days and days.isdigit() and int(days) in PERIODS:
        since = datetime.now(LOCAL_TZ) - timedelta(days=int(days))
    return _csv_response(csv_io.movements_csv(get_store().list_movements(since=since), t), "qoima_movements")


# ---------------------------------------------------------------- PDF reports

@bp.route("/stock.pdf")
@permission_required("reports")
def stock_pdf():
    store = get_store()
    products, warehouses, org = parallel(store.list_products, store.list_warehouses, requisites_loader())
    warehouse = next((w for w in warehouses if str(w["id"]) == request.args.get("warehouse")), None)
    in_warehouse = None
    if warehouse:
        in_warehouse = {row["product_id"]: row["quantity"] for row in store.list_stock(warehouse_id=warehouse["id"])}
    content = pdf.stock_report(products, org, t, warehouse["name"] if warehouse else None, in_warehouse)
    return pdf_response(content, f"qoima_stock_{date.today():%Y-%m-%d}.pdf")


@bp.route("/movements.pdf")
@permission_required("reports")
def movements_pdf():
    store = get_store()
    days = _period()
    movements, org = parallel(
        lambda: store.list_movements(since=datetime.now(LOCAL_TZ) - timedelta(days=days)), requisites_loader(),
    )
    return pdf_response(pdf.movements_report(movements, org, t, days), f"qoima_movements_{days}d.pdf")


@bp.route("/reorder.pdf")
@permission_required("reports")
def reorder_pdf():
    store = get_store()
    now = datetime.now(LOCAL_TZ)
    products, movements, org = parallel(
        store.list_products, lambda: store.list_movements(since=now - timedelta(days=forecast.WINDOW_DAYS)),
        requisites_loader(),
    )
    rows = forecast.forecast_rows(products, forecast.forecast_all(products, movements, now))
    return pdf_response(pdf.reorder_report(rows, org, t), f"qoima_reorder_{date.today():%Y-%m-%d}.pdf")
