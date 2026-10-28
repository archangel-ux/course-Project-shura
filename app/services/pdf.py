"""PDF invoices and reports (fpdf2). DejaVu Sans covers Kazakh and Russian letters and the ₸ sign."""

import logging
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from app.services.formatting import LOCAL_TZ, format_date, format_datetime, format_money, format_number

logging.getLogger("fontTools").setLevel(logging.WARNING)  # subsetting logs every glyph at INFO

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
INK = (22, 22, 26)
MUTED = (110, 110, 120)
RULE = (210, 210, 218)
HEAD_FILL = (242, 242, 245)


class _Pdf(FPDF):
    def __init__(self, footer_text, orientation="P"):
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self.footer_text = footer_text
        self.add_font("DejaVu", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(True, margin=18)
        self.set_text_color(*INK)
        self.set_draw_color(*RULE)
        self.set_font("DejaVu", size=9)

    def footer(self):
        self.set_y(-12)
        self.set_font("DejaVu", size=7)
        self.set_text_color(*MUTED)
        self.cell(0, 5, self.footer_text, align="L")
        self.cell(0, 5, f"{self.page_no()} / {{nb}}", align="R")
        self.set_text_color(*INK)


def _requisites(pdf, org, t):
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 6, org.get("name") or "—", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", size=8)
    pdf.set_text_color(*MUTED)
    first = [f"{t('field.bin')}: {org['bin']}" if org.get("bin") else "", org.get("address") or "",
             f"{t('field.phone')}: {org['phone']}" if org.get("phone") else ""]
    second = [org.get("bank") or "", f"IBAN: {org['iban']}" if org.get("iban") else "",
              f"{t('field.bik')}: {org['bik']}" if org.get("bik") else ""]
    for line in (first, second):
        text = " · ".join(part for part in line if part)
        if text:
            pdf.multi_cell(0, 4.2, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.ln(2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)


def _title(pdf, title, subtitle=None):
    pdf.set_font("DejaVu", "B", 14)
    pdf.cell(0, 8, title, align="C", new_x="LMARGIN", new_y="NEXT")
    if subtitle:
        pdf.set_font("DejaVu", size=9)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5, subtitle, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*INK)
    pdf.ln(5)


def _info(pdf, pairs):
    for label, value in pairs:
        if not value:
            continue
        pdf.set_font("DejaVu", size=9)
        pdf.set_text_color(*MUTED)
        pdf.cell(42, 5.5, label)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 5.5, str(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)


def _table(pdf, headers, rows, widths, aligns, total_row=None):
    pdf.set_font("DejaVu", size=8.5)
    heading = FontFace(emphasis="BOLD", fill_color=HEAD_FILL)
    total_style = FontFace(emphasis="BOLD")
    with pdf.table(col_widths=widths, text_align=aligns, line_height=5.6, padding=(1.4, 1.6),
                   headings_style=heading, borders_layout="HORIZONTAL_LINES", width=pdf.epw) as table:
        row = table.row()
        for header in headers:
            row.cell(header)
        for values in rows:
            row = table.row()
            for value in values:
                row.cell(str(value))
        if total_row:
            row = table.row(style=total_style)
            for value in total_row:
                row.cell(str(value))


def _signatures(pdf, labels):
    pdf.ln(12)
    width = pdf.epw / len(labels)
    pdf.set_font("DejaVu", size=9)
    y = pdf.get_y()
    for index, label in enumerate(labels):
        x = pdf.l_margin + index * width
        pdf.set_xy(x, y)
        pdf.cell(width - 8, 5, label)
        pdf.line(x, y + 13, x + width - 10, y + 13)
        pdf.set_xy(x, y + 14)
        pdf.set_text_color(*MUTED)
        pdf.set_font("DejaVu", size=7)
        pdf.cell(width - 8, 4, f"({_signature_hint()})")
        pdf.set_text_color(*INK)
        pdf.set_font("DejaVu", size=9)
    pdf.set_y(y + 22)


def _signature_hint():
    return "______ / ____________"


def _output(pdf):
    return bytes(pdf.output())


def _footer_text(t):
    return f"Qoima · {t('pdf.generated')} {datetime.now(LOCAL_TZ):%d.%m.%Y %H:%M}"


# ---------------------------------------------------------------- invoices

def invoice(document, lines, org, t):
    """document: qoima_documents row with embedded warehouse/supplier; lines: its movements."""
    doc_type = document["doc_type"]
    pdf = _Pdf(_footer_text(t))
    pdf.add_page()
    _requisites(pdf, org, t)
    _title(pdf, t(f"pdf.invoice_{doc_type}", number=document["number"]),
           t("pdf.dated", date=format_date(document["created_at"])))

    warehouse = (document.get("warehouse") or {}).get("name")
    pairs = [(t("field.warehouse"), warehouse)]
    if doc_type == "IN":
        supplier = document.get("supplier") or {}
        pairs.append((t("field.supplier"), " · ".join(x for x in (supplier.get("name"), supplier.get("phone")) if x)))
    elif doc_type == "OUT":
        pairs.append((t("field.counterparty"), document.get("counterparty")))
    elif doc_type == "TRANSFER":
        pairs.append((t("field.to_warehouse"), (document.get("to_warehouse") or {}).get("name")))
    pairs.append((t("field.note"), document.get("note")))
    _info(pdf, pairs)

    rows, total_qty, total_sum = [], 0, 0
    for index, line in enumerate(lines, start=1):
        product = line.get("product") or {}
        quantity = abs(line["quantity"])
        amount = quantity * (line.get("price") or 0)
        total_qty += quantity
        total_sum += amount
        rows.append([index, product.get("sku", ""), product.get("name", ""), product.get("unit", ""),
                     format_number(line["quantity"]) if doc_type == "ADJUST" else format_number(quantity),
                     format_money(line.get("price") or 0), format_money(amount)])
    _table(
        pdf,
        ["№", t("field.sku"), t("field.name"), t("field.unit_short"), t("field.quantity"), t("field.price"), t("field.amount")],
        rows, widths=(8, 24, 64, 14, 18, 26, 26), aligns=("CENTER", "LEFT", "LEFT", "CENTER", "RIGHT", "RIGHT", "RIGHT"),
        total_row=["", "", t("pdf.total"), "", format_number(total_qty), "", format_money(total_sum)],
    )
    pdf.ln(4)
    pdf.set_font("DejaVu", size=9)
    pdf.cell(0, 5, t("pdf.lines_total", count=len(rows), amount=format_money(total_sum)), new_x="LMARGIN", new_y="NEXT")

    labels = {"IN": ("pdf.sign_delivered", "pdf.sign_received"), "OUT": ("pdf.sign_released", "pdf.sign_received"),
              "TRANSFER": ("pdf.sign_released", "pdf.sign_received"), "ADJUST": ("pdf.sign_commission", "pdf.sign_storekeeper")}
    signatures = [t(key) for key in labels[doc_type]]
    if org.get("director"):
        signatures.insert(0, f"{t('field.director')}: {org['director']}")
    _signatures(pdf, signatures)
    return _output(pdf)


# ---------------------------------------------------------------- reports

def stock_report(products, org, t, warehouse_name=None, in_warehouse=None):
    pdf = _Pdf(_footer_text(t))
    pdf.add_page()
    _requisites(pdf, org, t)
    subtitle = t("pdf.as_of", date=f"{datetime.now(LOCAL_TZ):%d.%m.%Y %H:%M}")
    if warehouse_name:
        subtitle += f" · {warehouse_name}"
    _title(pdf, t("pdf.stock_title"), subtitle)

    rows, total_units, total_value = [], 0, 0
    for index, product in enumerate(p for p in products if p["is_active"]):
        quantity = in_warehouse.get(product["id"], 0) if in_warehouse is not None else product["quantity"]
        if in_warehouse is not None and quantity == 0:
            continue
        value = quantity * product["purchase_price"]
        total_units += quantity
        total_value += value
        rows.append([len(rows) + 1, product["sku"], product["name"], product["unit"], format_number(quantity),
                     format_number(product["min_quantity"]), format_money(product["purchase_price"]), format_money(value)])
    _table(
        pdf,
        ["№", t("field.sku"), t("field.name"), t("field.unit_short"), t("field.quantity_left"), t("field.min_short"),
         t("field.purchase_price"), t("metric.stock_value")],
        rows, widths=(8, 22, 54, 12, 18, 14, 26, 26),
        aligns=("CENTER", "LEFT", "LEFT", "CENTER", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
        total_row=["", "", t("pdf.total"), "", format_number(total_units), "", "", format_money(total_value)],
    )
    _signatures(pdf, [t("pdf.sign_storekeeper"), t("pdf.sign_accountant")])
    return _output(pdf)


def movements_report(movements, org, t, days):
    pdf = _Pdf(_footer_text(t), orientation="L")
    pdf.add_page()
    _requisites(pdf, org, t)
    _title(pdf, t("pdf.movements_title"), t("pdf.period_days", days=days))
    rows = []
    totals = {"IN": 0, "OUT": 0}
    for movement in reversed(movements):
        product = movement.get("product") or {}
        document = movement.get("document") or {}
        if movement["movement_type"] in totals:
            totals[movement["movement_type"]] += movement["quantity"] * (movement.get("price") or 0)
        place = (movement.get("warehouse") or {}).get("name", "")
        if movement.get("to_warehouse"):
            place += " → " + movement["to_warehouse"]["name"]
        rows.append([
            format_datetime(movement["created_at"]), f"{document.get('number', '')}",
            t(f"movement.{movement['movement_type']}"), product.get("sku", ""), product.get("name", ""),
            place, format_number(movement["quantity"]), product.get("unit", ""),
            format_money(abs(movement["quantity"]) * (movement.get("price") or 0)),
        ])
    _table(
        pdf,
        [t("field.date"), "№", t("field.type"), t("field.sku"), t("field.name"), t("field.warehouse"),
         t("field.quantity"), t("field.unit_short"), t("field.amount")],
        rows, widths=(36, 12, 26, 26, 64, 46, 20, 14, 32),
        aligns=("LEFT", "CENTER", "LEFT", "LEFT", "LEFT", "LEFT", "RIGHT", "CENTER", "RIGHT"),
    )
    pdf.ln(4)
    _info(pdf, [(t("reports.received"), format_money(totals["IN"])), (t("reports.shipped"), format_money(totals["OUT"]))])
    return _output(pdf)


def reorder_report(rows, org, t):
    pdf = _Pdf(_footer_text(t))
    pdf.add_page()
    _requisites(pdf, org, t)
    _title(pdf, t("pdf.reorder_title"), t("pdf.as_of", date=f"{datetime.now(LOCAL_TZ):%d.%m.%Y}"))
    lines, total = [], 0
    for row in rows:
        if row["reorder"] <= 0:
            continue
        amount = row["reorder"] * row["purchase_price"]
        total += amount
        lines.append([len(lines) + 1, row["sku"], row["name"], format_number(row["quantity"]),
                      t("forecast.days", days=row["days_left"]) if row["days_left"] is not None else "—",
                      f"{format_number(row['reorder'])} {row['unit']}", format_money(amount)])
    _table(
        pdf,
        ["№", t("field.sku"), t("field.name"), t("field.quantity_left"), t("forecast.enough_for"),
         t("forecast.reorder"), t("field.amount")],
        lines, widths=(8, 22, 60, 20, 22, 22, 26),
        aligns=("CENTER", "LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
        total_row=["", "", t("pdf.total"), "", "", "", format_money(total)],
    )
    _signatures(pdf, [t("pdf.sign_storekeeper"), t("pdf.sign_approved")])
    return _output(pdf)
