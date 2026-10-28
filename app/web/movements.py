import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.i18n import error_text, t
from app.services import inventory
from app.services.validators import ValidationError
from app.store import StoreError, parallel
from app.web.session import get_store, login_required, permission_required, safe_next

bp = Blueprint("movements", __name__, url_prefix="/movements")

HISTORY_LIMIT = 500
FILTERS = ("", "IN", "OUT", "TRANSFER", "ADJUST")


def _render(form=None, error=None, status=200):
    store = get_store()
    movement_type = request.args.get("type", "")
    if movement_type not in FILTERS:
        movement_type = ""
    query = request.args.get("q", "")
    movements, products, suppliers, warehouses, stock = parallel(
        lambda: store.list_movements(limit=HISTORY_LIMIT),
        store.list_products, store.list_suppliers, store.list_warehouses, store.list_stock,
    )
    products = [p for p in products if p["is_active"]]
    stock_by_product = inventory.stock_map(stock)
    op = request.args.get("op")
    form = form or {
        "product_id": request.args.get("product", ""),
        "movement_type": op if op in inventory.MOVEMENT_TYPES else "IN",
        "warehouse_id": request.args.get("warehouse", ""),
    }
    lines = _form_lines(form)
    return render_template(
        "movements/index.html",
        movements=inventory.filter_movements(movements, movement_type, query),
        products=products, suppliers=suppliers, warehouses=warehouses,
        stock_json={p["id"]: json.dumps(stock_by_product.get(p["id"], {})) for p in products},
        form=form, lines=lines, error=error, movement_type=movement_type, query=query,
    ), status


def _form_lines(form):
    """Lines to pre-fill after a failed submit (or one line from ?product=)."""
    if hasattr(form, "getlist"):
        pairs = list(zip(form.getlist("product_id"), form.getlist("quantity")))
    else:
        pairs = [(form.get("product_id", ""), form.get("quantity", ""))]
    return [{"product_id": str(p or ""), "quantity": q or ""} for p, q in pairs] or [{"product_id": "", "quantity": ""}]


@bp.route("/")
@login_required
def index():
    return _render()


@bp.route("/", methods=["POST"])
@permission_required("operate")
def create():
    store = get_store()
    back = request.form.get("next")
    try:
        products, suppliers, warehouses = parallel(store.list_products, store.list_suppliers, store.list_warehouses)
        active = {p["id"]: p for p in products if p["is_active"]}
        data = inventory.clean_document_form(
            request.form, set(active), {w["id"] for w in warehouses}, {s["id"] for s in suppliers},
        )
        document_id = store.register_document(**data)
    except (ValidationError, StoreError) as error:
        if back:
            flash(error_text(error), "error")
            return redirect(safe_next(back))
        return _render(form=request.form, error=error_text(error), status=400)

    if len(data["items"]) == 1:
        product = active[data["items"][0]["product_id"]]
        message = t(f"msg.document_one_{data['movement_type']}", name=product["name"],
                    qty=data["items"][0]["quantity"], unit=product["unit"])
    else:
        message = t(f"msg.document_many_{data['movement_type']}", count=len(data["items"]))
    flash(message, "success")
    _flash_pdf(document_id)
    if back:
        return redirect(safe_next(back))
    return redirect(url_for("movements.index", op=data["movement_type"], warehouse=data["warehouse_id"]))


def _flash_pdf(document_id):
    """A second toast with a link to print the new document."""
    flash(f"pdf:{url_for('documents.invoice', document_id=document_id)}", "document")
