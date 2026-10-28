from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.i18n import error_text, t
from app.services import inventory
from app.services.validators import ValidationError, optional_text
from app.store import StoreError, parallel
from app.web.session import get_store, permission_required

bp = Blueprint("stocktake", __name__, url_prefix="/stocktake")


def _warehouse_id(warehouses, raw):
    ids = [w["id"] for w in warehouses]
    try:
        chosen = int(raw or 0)
    except ValueError:
        chosen = 0
    return chosen if chosen in ids else (ids[0] if ids else None)


def _render(form=None, error=None, status=200):
    store = get_store()
    products, warehouses, history = parallel(
        store.list_products, store.list_warehouses,
        lambda: store.list_movements(movement_type="ADJUST", limit=30),
    )
    warehouse_id = _warehouse_id(warehouses, (form or {}).get("warehouse_id") or request.args.get("warehouse"))
    stock = store.list_stock(warehouse_id=warehouse_id) if warehouse_id else []
    category = request.args.get("category", "")
    return render_template(
        "stocktake.html",
        products=inventory.filter_products(products, category=category),
        categories=inventory.categories(products), category=category,
        warehouses=warehouses, warehouse_id=warehouse_id,
        in_warehouse={row["product_id"]: row["quantity"] for row in stock},
        history=history, form=form or {}, error=error,
    ), status


@bp.route("/")
@permission_required("operate")
def index():
    return _render()


@bp.route("/", methods=["POST"])
@permission_required("operate")
def submit():
    store = get_store()
    try:
        products, warehouses = parallel(store.list_products, store.list_warehouses)
        warehouse_id = _warehouse_id(warehouses, request.form.get("warehouse_id"))
        if warehouse_id is None:
            raise ValidationError("err.choose_warehouse")
        in_warehouse = {row["product_id"]: row["quantity"] for row in store.list_stock(warehouse_id=warehouse_id)}
        items = inventory.clean_stocktake_form(request.form, [p for p in products if p["is_active"]], in_warehouse)
        note = optional_text(request.form.get("note"), "field.note", max_length=200) or t("note.stocktake")
        changed = store.stocktake(warehouse_id, [{"product_id": i["product_id"], "counted": i["counted"]} for i in items], note)
    except (ValidationError, StoreError) as error:
        return _render(form=request.form, error=error_text(error), status=400)
    flash(t("msg.stocktake_done", checked=len(items), changed=changed), "success")
    return redirect(url_for("stocktake.index", warehouse=warehouse_id))
