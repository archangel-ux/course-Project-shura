from collections import defaultdict

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.i18n import error_text, t
from app.services import inventory
from app.services.validators import ValidationError
from app.store import StoreError, parallel
from app.web.session import get_store, login_required, permission_required

bp = Blueprint("suppliers", __name__, url_prefix="/suppliers")


def _supplier_or_404(supplier_id):
    supplier = get_store().get_supplier(supplier_id)
    if supplier is None:
        abort(404)
    return supplier


@bp.route("/")
@login_required
def index():
    store = get_store()
    stats = defaultdict(lambda: {"deliveries": 0, "units": 0, "value": 0, "last": None})
    receipts, suppliers = parallel(lambda: store.list_movements(movement_type="IN"), store.list_suppliers)
    for movement in receipts:
        if movement["supplier_id"]:
            entry = stats[movement["supplier_id"]]
            entry["deliveries"] += 1
            entry["units"] += movement["quantity"]
            entry["value"] += movement["quantity"] * (movement.get("price") or 0)
            entry["last"] = entry["last"] or movement["created_at"]
    peak = max([1] + [entry["value"] for entry in stats.values()])
    return render_template("suppliers/index.html", suppliers=suppliers, stats=stats, peak=peak)


@bp.route("/new", methods=["GET", "POST"])
@permission_required("manage")
def create():
    if request.method == "GET":
        return render_template("suppliers/form.html", supplier=None, form={}, error=None)
    try:
        get_store().create_supplier(inventory.clean_supplier_form(request.form))
    except (ValidationError, StoreError) as error:
        return render_template("suppliers/form.html", supplier=None, form=request.form, error=error_text(error)), 400
    flash(t("msg.supplier_saved"), "success")
    return redirect(url_for("suppliers.index"))


@bp.route("/<int:supplier_id>/edit", methods=["GET", "POST"])
@permission_required("manage")
def edit(supplier_id):
    supplier = _supplier_or_404(supplier_id)
    if request.method == "GET":
        return render_template("suppliers/form.html", supplier=supplier, form=supplier, error=None)
    try:
        get_store().update_supplier(supplier_id, inventory.clean_supplier_form(request.form))
    except (ValidationError, StoreError) as error:
        return render_template("suppliers/form.html", supplier=supplier, form=request.form,
                               error=error_text(error)), 400
    flash(t("msg.supplier_saved"), "success")
    return redirect(url_for("suppliers.index"))


@bp.route("/<int:supplier_id>/delete", methods=["POST"])
@permission_required("manage")
def delete(supplier_id):
    _supplier_or_404(supplier_id)
    try:
        get_store().delete_supplier(supplier_id)
    except StoreError as error:
        flash(t("err.supplier_in_use") if error.key == "err.in_use" else error_text(error), "error")
        return redirect(url_for("suppliers.edit", supplier_id=supplier_id))
    flash(t("msg.supplier_deleted"), "success")
    return redirect(url_for("suppliers.index"))
