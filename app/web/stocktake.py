from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.i18n import error_text, t
from app.services import inventory
from app.services.validators import ValidationError, optional_text
from app.store import StoreError
from app.web.session import get_store, login_required

bp = Blueprint("stocktake", __name__, url_prefix="/stocktake")


def _render(form=None, error=None, status=200):
    store = get_store()
    products = store.list_products()
    category = request.args.get("category", "")
    return render_template(
        "stocktake.html",
        products=inventory.filter_products(products, category=category),
        categories=inventory.categories(products), category=category,
        history=store.list_movements(movement_type="ADJUST", limit=30),
        form=form or {}, error=error,
    ), status


@bp.route("/")
@login_required
def index():
    return _render()


@bp.route("/", methods=["POST"])
@login_required
def submit():
    store = get_store()
    try:
        products = [p for p in store.list_products() if p["is_active"]]
        items = inventory.clean_stocktake_form(request.form, products)
        note = optional_text(request.form.get("note"), "field.note", max_length=200) or t("note.stocktake")
        changed = store.stocktake([{"product_id": i["product_id"], "counted": i["counted"]} for i in items], note)
    except (ValidationError, StoreError) as error:
        return _render(form=request.form, error=error_text(error), status=400)
    flash(t("msg.stocktake_done", checked=len(items), changed=changed), "success")
    return redirect(url_for("stocktake.index"))
