"""Aggregations for the dashboard and reports. Pure functions over already-loaded rows."""

from collections import defaultdict
from datetime import timedelta

from app.services.formatting import parse_timestamp


def daily_flow(movements, today, days=14):
    """Units received and shipped per day for the last `days` days, oldest first."""
    start = today - timedelta(days=days - 1)
    buckets = {start + timedelta(days=offset): {"in": 0, "out": 0} for offset in range(days)}
    for movement in movements:
        day = parse_timestamp(movement["created_at"]).date()
        if day not in buckets:
            continue
        if movement["movement_type"] == "IN":
            buckets[day]["in"] += movement["quantity"]
        elif movement["movement_type"] == "OUT":
            buckets[day]["out"] += movement["quantity"]
    return [{"day": day, **values} for day, values in sorted(buckets.items())]


def chart_geometry(series, height=160):
    """Bar heights in px for a simple SVG chart (two bars per day)."""
    peak = max([1] + [max(point["in"], point["out"]) for point in series])
    return [
        {**point, "in_h": round(point["in"] / peak * height), "out_h": round(point["out"] / peak * height)}
        for point in series
    ], peak


def top_outflow(movements, limit=5):
    totals = defaultdict(lambda: {"quantity": 0, "name": "", "sku": "", "unit": ""})
    for movement in movements:
        if movement["movement_type"] != "OUT":
            continue
        product = movement.get("product") or {}
        entry = totals[movement["product_id"]]
        entry["quantity"] += movement["quantity"]
        entry.update(name=product.get("name", ""), sku=product.get("sku", ""), unit=product.get("unit", ""))
    rows = sorted(totals.values(), key=lambda row: row["quantity"], reverse=True)[:limit]
    peak = rows[0]["quantity"] if rows else 1
    for row in rows:
        row["share"] = round(row["quantity"] / peak * 100)
    return rows


def category_breakdown(products):
    groups = defaultdict(lambda: {"count": 0, "units": 0, "value": 0})
    for product in products:
        if not product["is_active"]:
            continue
        group = groups[product["category"]]
        group["count"] += 1
        group["units"] += product["quantity"]
        group["value"] += product["quantity"] * product["purchase_price"]
    total = sum(group["value"] for group in groups.values()) or 1
    rows = [{"category": name, **values, "share": round(values["value"] / total * 100)} for name, values in groups.items()]
    return sorted(rows, key=lambda row: row["value"], reverse=True)


def movement_totals(movements):
    totals = {"IN": [0, 0], "OUT": [0, 0], "ADJUST": [0, 0]}
    for movement in movements:
        entry = totals[movement["movement_type"]]
        entry[0] += 1
        entry[1] += movement["quantity"]
    return totals
