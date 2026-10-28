from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from app.i18n import error_text, t
from app.services import csv_io, inventory
from app.services.formatting import money_to_input
from app.services.validators import ValidationError, parse_quantity
from app.store import StoreError
from app.web.session import get_store, login_required

bp = Blueprint("products", __name__, url_prefix="/products")

STATUSES = ("active", "low", "inactive", "all")


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
    products = get_store().list_products()
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
        counts=counts, query=query, category=category, status=status,
    )


def _render_form(product=None, form=None, error=None):
    products = get_store().list_products()
    return render_template(
        "products/form.html", product=product, form=form or {}, error=error,
        categories=inventory.categories(products), units=inventory.UNITS,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "GET":
        return _render_form(form={"unit": inventory.UNITS[0]})
    try:
        data = inventory.clean_product_form(request.form)
        initial = parse_quantity(request.form.get("quantity"), "field.initial_quantity")
        product_id = get_store().create_product(data, initial, t("note.initial"))
    except (ValidationError, StoreError) as error:
        return _render_form(form=request.form, error=error_text(error)), 400
    flash(t("msg.product_created"), "success")
    return redirect(url_for("products.detail", product_id=product_id))


@bp.route("/<int:product_id>")
@login_required
def detail(product_id):
    product = _product_or_404(product_id)
    movements = get_store().list_movements(product_id=product_id, limit=100)
    return render_template(
        "products/detail.html", product=product, movements=movements,
        suppliers=get_store().list_suppliers(), low=inventory.is_low_stock(product),
    )


@bp.route("/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
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
@login_required
def toggle(product_id):
    product = _product_or_404(product_id)
    get_store().set_product_active(product_id, not product["is_active"])
    flash(t("msg.product_archived") if product["is_active"] else t("msg.product_restored"), "success")
    return redirect(url_for("products.detail", product_id=product_id))


@bp.route("/import", methods=["GET", "POST"])
@login_required
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
@login_required
def import_template():
    return Response(
        csv_io.template_csv(t), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=qoima_import_template.csv"},
    )
