"""Aggregations for the dashboard and reports. Pure functions over already-loaded rows."""

import math
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
    totals = {"IN": [0, 0], "OUT": [0, 0], "ADJUST": [0, 0], "TRANSFER": [0, 0]}
    for movement in movements:
        entry = totals[movement["movement_type"]]
        entry[0] += 1
        entry[1] += movement["quantity"]
    return totals


# ---------------------------------------------------------------- period flow (reports)

def flow_buckets(movements, today, days):
    """In/out units grouped so the chart always has 7–30 bars: daily up to 30 days,
    weekly for 90, monthly for 365."""
    if days <= 30:
        return [{**point, "label": point["day"].strftime("%d"), "title": point["day"].strftime("%d.%m")}
                for point in daily_flow(movements, today, days)]

    if days <= 90:
        size = 7
        count = -(-days // size)
        start = today - timedelta(days=count * size - 1)
        buckets = [{"start": start + timedelta(days=i * size), "in": 0, "out": 0} for i in range(count)]
        for movement in movements:
            day = parse_timestamp(movement["created_at"]).date()
            index = (day - start).days // size
            if 0 <= index < count:
                _add(buckets[index], movement)
        for bucket in buckets:
            end = bucket["start"] + timedelta(days=size - 1)
            bucket["label"] = bucket["start"].strftime("%d.%m")
            bucket["title"] = f"{bucket['start']:%d.%m}–{end:%d.%m}"
        return buckets

    months = []
    year, month = today.year, today.month
    for _ in range(12):
        months.append((year, month))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    months.reverse()
    buckets = {key: {"in": 0, "out": 0, "label": f"{key[1]:02d}", "title": f"{key[1]:02d}.{key[0]}"} for key in months}
    for movement in movements:
        moment = parse_timestamp(movement["created_at"])
        bucket = buckets.get((moment.year, moment.month))
        if bucket:
            _add(bucket, movement)
    return [buckets[key] for key in months]


def _add(bucket, movement):
    if movement["movement_type"] == "IN":
        bucket["in"] += movement["quantity"]
    elif movement["movement_type"] == "OUT":
        bucket["out"] += movement["quantity"]


# ---------------------------------------------------------------- donuts

DONUT_RADIUS = 42
DONUT_CIRCUMFERENCE = 2 * math.pi * DONUT_RADIUS
DONUT_GAP = 1.6


def donut(segments):
    """segments: [{"label", "value", "key"}] → adds dash/offset for an SVG circle donut."""
    total = sum(s["value"] for s in segments)
    shown = [s for s in segments if s["value"] > 0]
    gap = DONUT_GAP if len(shown) > 1 else 0
    position = 0.0
    result = []
    for segment in segments:
        share = segment["value"] / total if total else 0
        length = share * DONUT_CIRCUMFERENCE
        result.append({
            **segment,
            "pct": round(share * 100),
            "dash": f"{max(length - gap, 0):.2f} {DONUT_CIRCUMFERENCE:.2f}",
            "offset": f"{-position:.2f}",
        })
        position += length
    return {"segments": result, "total": total, "circumference": f"{DONUT_CIRCUMFERENCE:.2f}"}


def stock_status(products):
    active = [p for p in products if p["is_active"]]
    out = sum(1 for p in active if p["quantity"] == 0)
    low = sum(1 for p in active if 0 < p["quantity"] <= p["min_quantity"])
    return donut([
        {"key": "ok", "label": "status.ok", "value": len(active) - out - low},
        {"key": "low", "label": "status.low", "value": low},
        {"key": "out", "label": "status.out", "value": out},
    ])


def category_donut(rows, slots=5):
    """Top categories by value get series colours in fixed order; the rest fold into 'Other'."""
    head, tail = rows[:slots], rows[slots:]
    segments = [{"key": f"s{i + 1}", "label": row["category"], "value": row["value"]} for i, row in enumerate(head)]
    if tail:
        segments.append({"key": "other", "label": None, "value": sum(row["value"] for row in tail)})
    return donut(segments)


# ---------------------------------------------------------------- ABC analysis

def abc_analysis(products, movements):
    """Classify products by issued value in the period: A ≤ 80 %, B ≤ 95 %, C — the rest."""
    names = {p["id"]: p for p in products}
    values = defaultdict(int)
    for movement in movements:
        if movement["movement_type"] == "OUT":
            product = names.get(movement["product_id"])
            price = movement.get("price") or (product["sale_price"] if product else 0)
            values[movement["product_id"]] += movement["quantity"] * price
    total = sum(values.values())
    groups = {key: {"key": key, "count": 0, "value": 0} for key in "ABC"}
    rows = []
    running = 0
    for product_id, value in sorted(values.items(), key=lambda item: item[1], reverse=True):
        share_before = running / total if total else 0
        running += value
        group = "A" if share_before < 0.8 else "B" if share_before < 0.95 else "C"
        groups[group]["count"] += 1
        groups[group]["value"] += value
        product = names.get(product_id) or {}
        rows.append({"id": product_id, "name": product.get("name", ""), "sku": product.get("sku", ""),
                     "value": value, "group": group, "share": round(value / total * 100, 1) if total else 0})
    for group in groups.values():
        group["share"] = round(group["value"] / total * 100) if total else 0
    return {"groups": list(groups.values()), "rows": rows, "total": total}


# ---------------------------------------------------------------- balance history (product page)

def balance_series(movements, current_quantity, now, width=640, height=150):
    """Step line of the product total over time from movement 'balance_after' values."""
    points = []
    for movement in sorted(movements, key=lambda m: (m["created_at"], m["id"])):
        moment = parse_timestamp(movement["created_at"])
        if not points:
            delta = {"IN": movement["quantity"], "OUT": -movement["quantity"]}.get(movement["movement_type"], 0)
            if movement["movement_type"] == "ADJUST":
                delta = movement["quantity"]
            points.append((moment, movement["balance_after"] - delta))
        points.append((moment, movement["balance_after"]))
    if len(points) < 2:
        return None
    points.append((now, current_quantity))

    start, end = points[0][0], points[-1][0]
    span = max((end - start).total_seconds(), 1)
    peak = max(1, max(value for _, value in points))
    pad_top = 8

    def x(moment):
        return round((moment - start).total_seconds() / span * width, 1)

    def y(value):
        return round(height - value / peak * (height - pad_top), 1)

    path = f"M0 {y(points[0][1])}"
    for moment, value in points[1:]:
        path += f" H{x(moment)} V{y(value)}"
    area = path + f" H{width} V{height} H0 Z"
    markers = [{"x": x(moment), "y": y(value), "value": value, "time": moment} for moment, value in points[1:-1]][-40:]
    return {
        "path": path, "area": area, "width": width, "height": height, "peak": peak,
        "markers": markers, "start": start, "end": end,
    }
