"""CSV export and product import.

Exports use UTF-8 with BOM and ';' so Excel opens them correctly with Cyrillic text.
Import accepts ';' or ',' and Kazakh, Russian or English column headers.
"""

import csv
import io

from app.services.formatting import format_datetime, money_for_csv
from app.services.inventory import clean_product_form
from app.services.validators import ValidationError, parse_quantity

MAX_IMPORT_ROWS = 1000

# Accepted header spellings → form field
IMPORT_HEADERS = {
    "name": ("name", "атауы", "название", "наименование", "товар"),
    "sku": ("sku", "артикул"),
    "category": ("category", "санаты", "санат", "категория"),
    "unit": ("unit", "өлшем бірлігі", "бірлік", "единица", "ед. изм.", "ед"),
    "quantity": ("quantity", "қалдық", "саны", "количество", "остаток", "qty"),
    "min_quantity": ("min_quantity", "ең аз қалдық", "ең аз", "минимум", "мин. остаток", "min"),
    "purchase_price": ("purchase_price", "сатып алу бағасы", "закупочная цена", "закупка", "cost"),
    "sale_price": ("sale_price", "сату бағасы", "цена продажи", "продажа", "price"),
    "description": ("description", "сипаттама", "описание"),
}


def _write(rows, header):
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def products_csv(products, t):
    header = [t("field.sku"), t("field.name"), t("field.category"), t("field.unit"), t("field.quantity_left"),
              t("field.min_quantity"), t("field.purchase_price"), t("field.sale_price"), t("field.status"),
              t("field.description")]
    rows = [
        [p["sku"], p["name"], p["category"], p["unit"], p["quantity"], p["min_quantity"],
         money_for_csv(p["purchase_price"]), money_for_csv(p["sale_price"]),
         t("status.active") if p["is_active"] else t("status.inactive"), p["description"]]
        for p in products
    ]
    return _write(rows, header)


def movements_csv(movements, t):
    header = ["№", t("field.date"), t("field.type"), t("field.sku"), t("field.name"), t("field.quantity"),
              t("field.unit"), t("field.balance_after"), t("field.supplier"), t("field.note")]
    rows = []
    for m in movements:
        product = m.get("product") or {}
        supplier = m.get("supplier") or {}
        rows.append([
            m["id"], format_datetime(m["created_at"]), t(f"movement.{m['movement_type']}"),
            product.get("sku", ""), product.get("name", ""), m["quantity"], product.get("unit", ""),
            m["balance_after"], supplier.get("name", ""), m["note"],
        ])
    return _write(rows, header)


def template_csv(t):
    header = [t("field.name"), t("field.sku"), t("field.category"), t("field.unit"), t("field.quantity_left"),
              t("field.min_quantity"), t("field.purchase_price"), t("field.sale_price"), t("field.description")]
    return _write([["Шариктік қалам", "PEN-001", "Кеңсе", "дана", "100", "20", "45", "90", ""]], header)


def _header_map(header_row):
    mapping = {}
    for index, title in enumerate(header_row):
        normalized = title.strip().lower().lstrip("﻿")
        for field, aliases in IMPORT_HEADERS.items():
            if normalized in aliases and field not in mapping:
                mapping[field] = index
    return mapping


def parse_import(text):
    """Return (rows, errors). rows: [(line, data, initial_quantity)], errors: [(line, ValidationError)]."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise ValidationError("err.import_empty")
    first_line = text.splitlines()[0]
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    mapping = _header_map(next(reader, []))
    if "name" not in mapping or "sku" not in mapping:
        raise ValidationError("err.import_headers")

    rows, errors, seen_skus = [], [], set()
    for line_number, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            continue
        if len(rows) + len(errors) >= MAX_IMPORT_ROWS:
            raise ValidationError("err.import_too_many", max=MAX_IMPORT_ROWS)
        form = {field: cells[index] if index < len(cells) else "" for field, index in mapping.items()}
        try:
            data = clean_product_form(form)
            quantity = parse_quantity(form.get("quantity"), "field.quantity_left")
            if data["sku"].lower() in seen_skus:
                raise ValidationError("err.sku_taken")
        except ValidationError as error:
            errors.append((line_number, error))
            continue
        seen_skus.add(data["sku"].lower())
        rows.append((line_number, data, quantity))
    return rows, errors
