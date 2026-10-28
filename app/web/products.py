from datetime import datetime, timedelta

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from app.i18n import error_text, t
from app.services import analytics, csv_io, forecast, inventory
from app.services.formatting import LOCAL_TZ, money_to_input
from app.services.validators import ValidationError, parse_quantity
from app.store import StoreError, parallel
from app.web.session import current_org, get_store, login_required, permission_required

bp = Blueprint("products", __name__, url_prefix="/products")

STATUSES = ("active", "low", "inactive", "all")

# Recognised by their first bytes, not by the file name or the browser's claim.
IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)

MAX_PHOTO_BYTES = 5 * 1024 * 1024


def _image_type(content):
    for signature, mime, extension in IMAGE_SIGNATURES:
        if content.startswith(signature):
            return mime, extension
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def _product_or_404(product_id):
    product = get_store().get_product(product_id)
    if product is None:
        abort(404)
    return product


def _form_values(product):
    return {
        "name": product["name"], "sku": product["sku"], "category": product["category"],
        "unit": product["unit"], "min_quantity": product["min_quantity"],
        "purchase_price": money_to_input(product["purchase_price"]),
        "sale_price": money_to_input(product["sale_price"]), "description": product["description"],
    }


@bp.route("/")
@login_required
def index():
    store = get_store()
    now = datetime.now(LOCAL_TZ)
    products, movements = parallel(
        store.list_products, lambda: store.list_movements(since=now - timedelta(days=forecast.WINDOW_DAYS)),
    )
    forecasts = forecast.forecast_all(products, movements, now)
    query = request.args.get("q", "")
    category = request.args.get("category", "")
    status = request.args.get("status", "active")
    if status not in STATUSES:
        status = "active"
    counts = {name: len(inventory.filter_products(products, status=name)) for name in STATUSES}
    return render_template(
        "products/index.html",
        products=inventory.filter_products(products, query, category, status),
        categories=inventory.categories(products),
        counts=counts, query=query, category=category, status=status, forecasts=forecasts,
    )


def _render_form(product=None, form=None, error=None):
    store = get_store()
    products, warehouses = parallel(store.list_products, store.list_warehouses)
    return render_template(
        "products/form.html", product=product, form=form or {}, error=error,
        categories=inventory.categories(products), units=inventory.UNITS, warehouses=warehouses,
    )


@bp.route("/new", methods=["GET", "POST"])
@permission_required("manage")
def create():
    if request.method == "GET":
        return _render_form(form={"unit": inventory.UNITS[0]})
    try:
        data = inventory.clean_product_form(request.form)
        initial = parse_quantity(request.form.get("quantity"), "field.initial_quantity")
        warehouse_id = int(request.form.get("warehouse_id") or 0) or None
        product_id = get_store().create_product(data, initial, t("note.initial"), warehouse_id)
    except (ValidationError, StoreError) as error:
        return _render_form(form=request.form, error=error_text(error)), 400
    flash(t("msg.product_created"), "success")
    return redirect(url_for("products.detail", product_id=product_id))


@bp.route("/<int:product_id>")
@login_required
def detail(product_id):
    store = get_store()
    now = datetime.now(LOCAL_TZ)
    product, movements, suppliers, warehouses, stock = parallel(
        lambda: store.get_product(product_id),
        lambda: store.list_movements(product_id=product_id, limit=300),
        store.list_suppliers, store.list_warehouses,
        lambda: store.list_stock(product_id=product_id),
    )
    if product is None:
        abort(404)
    in_warehouse = {row["warehouse_id"]: row["quantity"] for row in stock}
    since = now - timedelta(days=forecast.WINDOW_DAYS)
    issued = forecast.consumption(movements, since).get(product_id, 0)
    return render_template(
        "products/detail.html", product=product, movements=movements[:100],
        suppliers=suppliers, warehouses=warehouses, in_warehouse=in_warehouse,
        low=inventory.is_low_stock(product), forecast=forecast.forecast(product, issued, now),
        balance=analytics.balance_series(movements, product["quantity"], now),
    )


@bp.route("/<int:product_id>/edit", methods=["GET", "POST"])
@permission_required("manage")
def edit(product_id):
    product = _product_or_404(product_id)
    if request.method == "GET":
        return _render_form(product, _form_values(product))
    try:
        get_store().update_product(product_id, inventory.clean_product_form(request.form))
    except (ValidationError, StoreError) as error:
        return _render_form(product, request.form, error_text(error)), 400
    flash(t("msg.product_saved"), "success")
    return redirect(url_for("products.detail", product_id=product_id))


@bp.route("/<int:product_id>/toggle", methods=["POST"])
@permission_required("manage")
def toggle(product_id):
    product = _product_or_404(product_id)
    get_store().set_product_active(product_id, not product["is_active"])
    flash(t("msg.product_archived") if product["is_active"] else t("msg.product_restored"), "success")
    return redirect(url_for("products.detail", product_id=product_id))


@bp.route("/<int:product_id>/photo", methods=["POST"])
@permission_required("manage")
def photo(product_id):
    product = _product_or_404(product_id)
    back = redirect(url_for("products.detail", product_id=product_id))
    store = get_store()
    if request.form.get("remove"):
        store.remove_photo(product)
        flash(t("msg.photo_removed"), "success")
        return back
    upload = request.files.get("photo")
    content = upload.read(MAX_PHOTO_BYTES + 1) if upload and upload.filename else b""
    if not content:
        flash(t("err.photo_missing"), "error")
        return back
    if len(content) > MAX_PHOTO_BYTES:
        flash(t("err.photo_too_large"), "error")
        return back
    kind = _image_type(content)
    if kind is None:
        flash(t("err.photo_type"), "error")
        return back
    try:
        store.upload_photo(current_org()["id"], product, content, *kind)
    except StoreError as error:
        flash(error_text(error), "error")
        return back
    flash(t("msg.photo_saved"), "success")
    return back


@bp.route("/import", methods=["GET", "POST"])
@permission_required("manage")
def import_products():
    if request.method == "GET":
        return render_template("products/import.html", result=None, error=None)

    upload = request.files.get("file")
    text = request.form.get("text", "")
    if upload and upload.filename:
        raw = upload.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1251", errors="replace")
    try:
        rows, errors = csv_io.parse_import(text)
    except ValidationError as error:
        return render_template("products/import.html", result=None, error=error_text(error)), 400

    store = get_store()
    created = 0
    failures = [(line, error_text(error)) for line, error in errors]
    for line, data, quantity in rows:
        try:
            store.create_product(data, quantity, t("note.imported"))
            created += 1
        except StoreError as error:
            failures.append((line, f"{data['sku']}: {error_text(error)}"))
    failures.sort()
    return render_template("products/import.html", result={"created": created, "failures": failures}, error=None)


@bp.route("/import/template.csv")
@permission_required("manage")
def import_template():
    return Response(
        csv_io.template_csv(t), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=qoima_import_template.csv"},
    )
