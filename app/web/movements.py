from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.i18n import error_text, t
from app.services import inventory
from app.services.formatting import format_number
from app.services.validators import ValidationError
from app.store import StoreError
from app.web.session import get_store, login_required, safe_next

bp = Blueprint("movements", __name__, url_prefix="/movements")

HISTORY_LIMIT = 500
FILTERS = ("", "IN", "OUT", "ADJUST")


def _render(form=None, error=None, status=200):
    store = get_store()
    movement_type = request.args.get("type", "")
    if movement_type not in FILTERS:
        movement_type = ""
    query = request.args.get("q", "")
    movements = store.list_movements(limit=HISTORY_LIMIT)
    products = [p for p in store.list_products() if p["is_active"]]
    form = form or {
        "product_id": request.args.get("product", ""),
        "movement_type": request.args.get("op", "IN") if request.args.get("op") in ("IN", "OUT") else "IN",
    }
    return render_template(
        "movements/index.html",
        movements=inventory.filter_movements(movements, movement_type, query),
        products=products, suppliers=store.list_suppliers(),
        form=form, error=error, movement_type=movement_type, query=query,
    ), status


@bp.route("/")
@login_required
def index():
    return _render()


@bp.route("/", methods=["POST"])
@login_required
def create():
    store = get_store()
    back = request.form.get("next")
    try:
        products = {p["id"]: p for p in store.list_products() if p["is_active"]}
        suppliers = {s["id"] for s in store.list_suppliers()}
        data = inventory.clean_movement_form(request.form, set(products), suppliers)
        row = store.register_movement(**data)
    except (ValidationError, StoreError) as error:
        if back:
            flash(error_text(error), "error")
            return redirect(safe_next(back))
        return _render(form=request.form, error=error_text(error), status=400)

    product = products[data["product_id"]]
    message = "msg.stock_in_done" if data["movement_type"] == "IN" else "msg.stock_out_done"
    flash(t(message, name=product["name"], balance=format_number(row["balance_after"]), unit=product["unit"]), "success")
    if back:
        return redirect(safe_next(back))
    return redirect(url_for("movements.index", product=data["product_id"], op=data["movement_type"]))
