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
MOVEMENT_TYPES = ("IN", "OUT", "TRANSFER")
ROLES = ("owner", "storekeeper", "accountant")


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


# ---------------------------------------------------------------- documents (receipt / issue / transfer)

MAX_DOCUMENT_LINES = 100


def _to_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def clean_document_form(form, product_ids, warehouse_ids, supplier_ids):
    """Several lines of product + quantity. Lines with the same product are merged."""
    movement_type = form.get("movement_type")
    if movement_type not in MOVEMENT_TYPES:
        raise ValidationError("err.invalid_type")

    warehouse_id = _to_int(form.get("warehouse_id"))
    if warehouse_id not in warehouse_ids:
        raise ValidationError("err.choose_warehouse")
    to_warehouse_id = None
    if movement_type == "TRANSFER":
        to_warehouse_id = _to_int(form.get("to_warehouse_id"))
        if to_warehouse_id not in warehouse_ids or to_warehouse_id == warehouse_id:
            raise ValidationError("err.invalid_transfer")

    supplier_id = None
    if movement_type == "IN" and form.get("supplier_id"):
        supplier_id = _to_int(form.get("supplier_id"))
        if supplier_id not in supplier_ids:
            raise ValidationError("err.not_found")

    quantities = {}
    raw_products = form.getlist("product_id") if hasattr(form, "getlist") else [form.get("product_id")]
    raw_quantities = form.getlist("quantity") if hasattr(form, "getlist") else [form.get("quantity")]
    for raw_product, raw_quantity in zip(raw_products, raw_quantities):
        if not raw_product and not str(raw_quantity or "").strip():
            continue
        product_id = _to_int(raw_product)
        if product_id not in product_ids:
            raise ValidationError("err.choose_product")
        quantity = parse_quantity(raw_quantity, "field.quantity", allow_zero=False)
        quantities[product_id] = quantities.get(product_id, 0) + quantity
    if not quantities:
        raise ValidationError("err.choose_product")
    if len(quantities) > MAX_DOCUMENT_LINES:
        raise ValidationError("err.too_many_lines", max=MAX_DOCUMENT_LINES)

    return {
        "movement_type": movement_type,
        "warehouse_id": warehouse_id,
        "to_warehouse_id": to_warehouse_id,
        "supplier_id": supplier_id,
        "counterparty": optional_text(form.get("counterparty"), "field.counterparty", max_length=150)
        if movement_type == "OUT" else "",
        "note": optional_text(form.get("note"), "field.note", max_length=200),
        "items": [{"product_id": pid, "quantity": qty} for pid, qty in quantities.items()],
    }


def stock_map(stock_rows):
    """{product_id: {warehouse_id: quantity}}"""
    result = {}
    for row in stock_rows:
        result.setdefault(row["product_id"], {})[row["warehouse_id"]] = row["quantity"]
    return result


def warehouse_summary(warehouses, products, stock_rows):
    """Positions, units and purchase value per warehouse (active products only)."""
    active = {p["id"]: p for p in products if p["is_active"]}
    rows = {w["id"]: {**w, "positions": 0, "units": 0, "value": 0} for w in warehouses}
    for row in stock_rows:
        product = active.get(row["product_id"])
        target = rows.get(row["warehouse_id"])
        if not product or not target or row["quantity"] <= 0:
            continue
        target["positions"] += 1
        target["units"] += row["quantity"]
        target["value"] += row["quantity"] * product["purchase_price"]
    total = sum(r["value"] for r in rows.values()) or 1
    result = list(rows.values())
    for row in result:
        row["share"] = round(row["value"] / total * 100)
    return result


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
                (movement.get("warehouse") or {}).get("name") or "",
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


# ---------------------------------------------------------------- warehouses & organization

def clean_warehouse_form(form):
    return {
        "name": require_text(form.get("name"), "field.warehouse_name", max_length=100),
        "address": optional_text(form.get("address"), "field.address", max_length=250),
    }


def clean_organization_form(form):
    return {
        "name": require_text(form.get("name"), "field.org_name"),
        "bin": optional_text(form.get("bin"), "field.bin", max_length=20),
        "address": optional_text(form.get("address"), "field.address", max_length=250),
        "phone": optional_text(form.get("phone"), "field.phone", max_length=40),
        "director": optional_text(form.get("director"), "field.director", max_length=120),
        "bank": optional_text(form.get("bank"), "field.bank"),
        "iban": optional_text(form.get("iban"), "field.iban", max_length=40).replace(" ", "").upper(),
        "bik": optional_text(form.get("bik"), "field.bik", max_length=20).upper(),
    }


# ---------------------------------------------------------------- stocktake

def clean_stocktake_form(form, products, in_warehouse):
    """Read 'counted_<id>' fields. Empty fields are skipped (product not counted).
    in_warehouse: {product_id: quantity} for the warehouse being counted."""
    items = []
    for product in products:
        raw = (form.get(f"counted_{product['id']}") or "").strip()
        if raw == "":
            continue
        counted = parse_quantity(raw, "field.counted")
        current = in_warehouse.get(product["id"], 0)
        items.append({"product_id": product["id"], "counted": counted, "difference": counted - current})
    if not items:
        raise ValidationError("err.stocktake_empty")
    return items
