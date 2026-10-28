"""Stock forecast: average daily consumption → "enough for N days" and a suggested order quantity.

Consumption is the sum of OUT movements over the last WINDOW_DAYS (shorter for products
created recently, but never less than MIN_WINDOW_DAYS so one big issue does not explode
the rate). The suggested order brings the stock up to min_quantity + COVER_DAYS of use.
"""

import math
from datetime import timedelta

from app.services.formatting import parse_timestamp

WINDOW_DAYS = 30
MIN_WINDOW_DAYS = 7
COVER_DAYS = 30
CRITICAL_DAYS = 7
WARNING_DAYS = 14


def consumption(movements, since):
    """{product_id: units issued} for OUT movements created at or after `since`."""
    totals = {}
    for movement in movements:
        if movement["movement_type"] != "OUT":
            continue
        if parse_timestamp(movement["created_at"]) < since:
            continue
        totals[movement["product_id"]] = totals.get(movement["product_id"], 0) + movement["quantity"]
    return totals


def forecast(product, issued, now, window_days=WINDOW_DAYS):
    created = parse_timestamp(product.get("created_at")) or now
    age_days = max((now - created).days, 0)
    window = max(MIN_WINDOW_DAYS, min(window_days, age_days or window_days))
    rate = issued / window if issued else 0.0
    quantity = product["quantity"]
    minimum = product["min_quantity"]

    if rate > 0:
        days_left = math.floor(quantity / rate)
        target = minimum + math.ceil(rate * COVER_DAYS)
    else:
        days_left = None
        target = minimum * 2 if quantity <= minimum else 0
    reorder = max(0, target - quantity)

    if days_left is not None and days_left <= CRITICAL_DAYS:
        level = "critical"
    elif days_left is not None and days_left <= WARNING_DAYS:
        level = "warning"
    elif quantity <= minimum and product["is_active"]:
        level = "warning"
    else:
        level = "ok"
    return {
        "rate": rate,
        "days_left": days_left,
        "reorder": reorder,
        "level": level,
        # meter: how much of a 30-day horizon is covered
        "cover_pct": 100 if days_left is None else min(100, round(days_left / COVER_DAYS * 100)),
    }


def forecast_all(products, movements, now):
    issued = consumption(movements, now - timedelta(days=WINDOW_DAYS))
    return {p["id"]: forecast(p, issued.get(p["id"], 0), now) for p in products}


def forecast_rows(products, forecasts, limit=None):
    """Active products that are consumed or need ordering, most urgent first."""
    rows = []
    for product in products:
        if not product["is_active"]:
            continue
        info = forecasts.get(product["id"])
        if not info or (info["rate"] == 0 and info["reorder"] == 0):
            continue
        rows.append({**product, **info})
    rows.sort(key=lambda row: (row["days_left"] if row["days_left"] is not None else 10**9, -row["reorder"]))
    return rows[:limit] if limit else rows


def format_rate(rate):
    if rate >= 10:
        return f"{rate:.0f}"
    return f"{rate:.1f}".replace(".", ",")
