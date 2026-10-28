from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.i18n import error_text, t
from app.services import inventory
from app.services.validators import ValidationError
from app.store import StoreError, parallel
from app.web.session import get_store, login_required, permission_required

bp = Blueprint("warehouses", __name__, url_prefix="/warehouses")


def _render(form=None, error=None, status=200):
    store = get_store()
    warehouses, products, stock = parallel(store.list_warehouses, store.list_products, store.list_stock)
    summary = inventory.warehouse_summary(warehouses, products, stock)
    peak = max([1] + [w["value"] for w in summary])
    for row in summary:
        row["bar"] = round(row["value"] / peak * 100)
    return render_template("warehouses/index.html", warehouses=summary, form=form or {}, error=error), status


@bp.route("/")
@login_required
def index():
    return _render()


@bp.route("/", methods=["POST"])
@permission_required("manage")
def create():
    try:
        get_store().create_warehouse(inventory.clean_warehouse_form(request.form))
    except (ValidationError, StoreError) as error:
        return _render(request.form, error_text(error), 400)
    flash(t("msg.warehouse_saved"), "success")
    return redirect(url_for("warehouses.index"))


@bp.route("/<int:warehouse_id>/edit", methods=["GET", "POST"])
@permission_required("manage")
def edit(warehouse_id):
    store = get_store()
    warehouse = store.get_warehouse(warehouse_id)
    if warehouse is None:
        abort(404)
    if request.method == "GET":
        return render_template("warehouses/form.html", warehouse=warehouse, form=warehouse, error=None)
    try:
        store.update_warehouse(warehouse_id, inventory.clean_warehouse_form(request.form))
    except (ValidationError, StoreError) as error:
        return render_template("warehouses/form.html", warehouse=warehouse, form=request.form,
                               error=error_text(error)), 400
    flash(t("msg.warehouse_saved"), "success")
    return redirect(url_for("warehouses.index"))


@bp.route("/<int:warehouse_id>/delete", methods=["POST"])
@permission_required("manage")
def delete(warehouse_id):
    try:
        get_store().delete_warehouse(warehouse_id)
    except StoreError as error:
        flash(t("err.warehouse_in_use") if error.key == "err.in_use" else error_text(error), "error")
        return redirect(url_for("warehouses.edit", warehouse_id=warehouse_id))
    flash(t("msg.warehouse_deleted"), "success")
    return redirect(url_for("warehouses.index"))
