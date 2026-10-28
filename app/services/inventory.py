"""Business rules for products, movements, suppliers and stocktakes.

Functions here validate input and compute derived data; storage happens in app.store.
"""

from app.services.validators import (
    ValidationError,
    optional_text,
    parse_email,
    parse_money,
    parse_quantity,
    require_text,
)

UNITS = ("дана", "кг", "г", "л", "м", "қорап", "жәшік", "орам", "жұп")
MOVEMENT_TYPES = ("IN", "OUT")


# ---------------------------------------------------------------- products

def clean_product_form(form):
    return {
        "name": require_text(form.get("name"), "field.name"),
        "sku": require_text(form.get("sku"), "field.sku", max_length=50),
        "category": optional_text(form.get("category"), "field.category", max_length=80),
        "unit": require_text(form.get("unit") or UNITS[0], "field.unit", max_length=20),
        "min_quantity": parse_quantity(form.get("min_quantity"), "field.min_quantity"),
        "purchase_price": parse_money(form.get("purchase_price"), "field.purchase_price"),
        "sale_price": parse_money(form.get("sale_price"), "field.sale_price"),
        "description": optional_text(form.get("description"), "field.description", max_length=1000),
    }


def is_low_stock(product):
    return product["is_active"] and product["quantity"] <= product["min_quantity"]


def filter_products(products, text="", category="", status="active"):
    """status: 'active' | 'low' | 'inactive' | 'all'."""
    needle = text.strip().lower()
    result = []
    for product in products:
        if status == "active" and not product["is_active"]:
            continue
        if status == "inactive" and product["is_active"]:
            continue
        if status == "low" and not is_low_stock(product):
            continue
        if category and product["category"] != category:
            continue
        if needle and not any(needle in (product[key] or "").lower() for key in ("name", "sku", "category")):
            continue
        result.append(product)
    return result


def categories(products):
    return sorted({p["category"] for p in products if p["category"]}, key=str.lower)


def summary(products):
    active = [p for p in products if p["is_active"]]
    return {
        "product_count": len(active),
        "inactive_count": len(products) - len(active),
        "total_units": sum(p["quantity"] for p in active),
        "low_count": sum(1 for p in active if is_low_stock(p)),
        "out_of_stock": sum(1 for p in active if p["quantity"] == 0),
        "purchase_value": sum(p["quantity"] * p["purchase_price"] for p in active),
        "sale_value": sum(p["quantity"] * p["sale_price"] for p in active),
    }


def low_stock(products):
    rows = [p for p in products if is_low_stock(p)]
    return sorted(rows, key=lambda p: (p["quantity"] - p["min_quantity"], p["name"].lower()))


# ---------------------------------------------------------------- movements

def clean_movement_form(form, product_ids, supplier_ids):
    movement_type = form.get("movement_type")
    if movement_type not in MOVEMENT_TYPES:
        raise ValidationError("err.invalid_type")
    try:
        product_id = int(form.get("product_id") or 0)
    except ValueError:
        product_id = 0
    if product_id not in product_ids:
        raise ValidationError("err.choose_product")

    supplier_id = None
    raw_supplier = form.get("supplier_id") or ""
    if movement_type == "IN" and raw_supplier:
        try:
            supplier_id = int(raw_supplier)
        except ValueError:
            supplier_id = None
        if supplier_id not in supplier_ids:
            raise ValidationError("err.not_found")

    return {
        "product_id": product_id,
        "movement_type": movement_type,
        "quantity": parse_quantity(form.get("quantity"), "field.quantity", allow_zero=False),
        "note": optional_text(form.get("note"), "field.note", max_length=200),
        "supplier_id": supplier_id,
    }


def filter_movements(movements, movement_type="", text=""):
    needle = text.strip().lower()
    result = []
    for movement in movements:
        if movement_type and movement["movement_type"] != movement_type:
            continue
        if needle:
            product = movement.get("product") or {}
            supplier = movement.get("supplier") or {}
            haystack = " ".join([
                product.get("name") or "", product.get("sku") or "",
                supplier.get("name") or "", movement.get("note") or "",
            ]).lower()
            if needle not in haystack:
                continue
        result.append(movement)
    return result


# ---------------------------------------------------------------- suppliers

def clean_supplier_form(form):
    return {
        "name": require_text(form.get("name"), "field.supplier_name"),
        "contact_person": optional_text(form.get("contact_person"), "field.contact_person", max_length=120),
        "phone": optional_text(form.get("phone"), "field.phone", max_length=40),
        "email": parse_email(form.get("email"), required=False),
        "note": optional_text(form.get("note"), "field.note", max_length=500),
    }


# ---------------------------------------------------------------- stocktake

def clean_stocktake_form(form, products):
    """Read 'counted_<id>' fields. Empty fields are skipped (product not counted)."""
    items = []
    for product in products:
        raw = (form.get(f"counted_{product['id']}") or "").strip()
        if raw == "":
            continue
        counted = parse_quantity(raw, "field.counted")
        items.append({"product_id": product["id"], "counted": counted, "difference": counted - product["quantity"]})
    if not items:
        raise ValidationError("err.stocktake_empty")
    return items
