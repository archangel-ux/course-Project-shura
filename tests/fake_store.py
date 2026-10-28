"""In-memory stand-in for SupabaseStore with the same rules as supabase/schema.sql."""

import itertools
from datetime import datetime, timedelta, timezone

from app.store import StoreError


def _now():
    return datetime.now(timezone.utc)


class FakeStore:
    def __init__(self):
        self.products = {}
        self.movements = []
        self.suppliers = {}
        self.profile = {"id": "user-1", "full_name": "", "company": "", "phone": "", "language": "kk", "theme": "dark"}
        self._ids = itertools.count(1)

    # products
    def list_products(self):
        return sorted((dict(p) for p in self.products.values()), key=lambda p: p["name"].lower())

    def get_product(self, product_id):
        product = self.products.get(int(product_id))
        return dict(product) if product else None

    def _check_sku(self, sku, own_id=None):
        for product in self.products.values():
            if product["sku"].lower() == sku.lower() and product["id"] != own_id:
                raise StoreError("err.sku_taken")

    def create_product(self, data, initial_quantity, note, created_at=None):
        self._check_sku(data["sku"])
        product_id = next(self._ids)
        stamp = (created_at or _now()).isoformat()
        self.products[product_id] = {**data, "id": product_id, "quantity": initial_quantity, "is_active": True,
                                     "created_at": stamp, "updated_at": stamp}
        if initial_quantity > 0:
            self._add_movement(product_id, "IN", initial_quantity, initial_quantity, note, None, created_at)
        return product_id

    def update_product(self, product_id, data):
        self._check_sku(data["sku"], own_id=int(product_id))
        self.products[int(product_id)].update(data)

    def set_product_active(self, product_id, is_active):
        self.products[int(product_id)]["is_active"] = bool(is_active)

    # movements
    def _add_movement(self, product_id, movement_type, quantity, balance, note, supplier_id, created_at=None):
        product = self.products[product_id]
        row = {
            "id": next(self._ids), "product_id": product_id, "movement_type": movement_type,
            "quantity": quantity, "balance_after": balance, "supplier_id": supplier_id, "note": note,
            "created_at": (created_at or _now()).isoformat(),
            "product": {"name": product["name"], "sku": product["sku"], "unit": product["unit"]},
            "supplier": {"name": self.suppliers[supplier_id]["name"]} if supplier_id else None,
        }
        self.movements.append(row)
        return row

    def list_movements(self, limit=None, since=None, product_id=None, movement_type=None):
        rows = sorted(self.movements, key=lambda m: (m["created_at"], m["id"]), reverse=True)
        if since:
            rows = [m for m in rows if datetime.fromisoformat(m["created_at"]) >= since]
        if product_id:
            rows = [m for m in rows if m["product_id"] == int(product_id)]
        if movement_type:
            rows = [m for m in rows if m["movement_type"] == movement_type]
        if limit:
            rows = rows[:limit]
        return [dict(m) for m in rows]

    def register_movement(self, product_id, movement_type, quantity, note, supplier_id=None, created_at=None):
        product = self.products.get(int(product_id))
        if product is None:
            raise StoreError("err.not_found")
        if not product["is_active"]:
            raise StoreError("err.product_inactive")
        if quantity <= 0:
            raise StoreError("err.quantity_positive")
        new_quantity = product["quantity"] + (quantity if movement_type == "IN" else -quantity)
        if new_quantity < 0:
            raise StoreError("err.insufficient_stock")
        product["quantity"] = new_quantity
        return self._add_movement(product["id"], movement_type, quantity, new_quantity, note,
                                  supplier_id if movement_type == "IN" else None, created_at)

    def stocktake(self, items, note):
        changed = 0
        for item in items:
            product = self.products.get(int(item["product_id"]))
            if product is None:
                raise StoreError("err.not_found")
            if item["counted"] != product["quantity"]:
                difference = item["counted"] - product["quantity"]
                product["quantity"] = item["counted"]
                self._add_movement(product["id"], "ADJUST", difference, item["counted"], note, None)
                changed += 1
        return changed

    # suppliers
    def list_suppliers(self):
        return sorted((dict(s) for s in self.suppliers.values()), key=lambda s: s["name"].lower())

    def get_supplier(self, supplier_id):
        supplier = self.suppliers.get(int(supplier_id))
        return dict(supplier) if supplier else None

    def create_supplier(self, data):
        if any(s["name"].lower() == data["name"].lower() for s in self.suppliers.values()):
            raise StoreError("err.supplier_taken")
        supplier_id = next(self._ids)
        self.suppliers[supplier_id] = {**data, "id": supplier_id, "created_at": _now().isoformat()}
        return supplier_id

    def update_supplier(self, supplier_id, data):
        self.suppliers[int(supplier_id)].update(data)

    def delete_supplier(self, supplier_id):
        if any(m["supplier_id"] == int(supplier_id) for m in self.movements):
            raise StoreError("err.in_use")
        del self.suppliers[int(supplier_id)]

    # profile
    def get_profile(self):
        return dict(self.profile)

    def update_profile(self, data):
        self.profile.update(data)
        return dict(self.profile)


def seed_demo(store):
    """A realistic small warehouse for previews and tests."""
    now = _now()
    supplier_a = store.create_supplier({"name": "Kanc Market", "contact_person": "Айгүл Серікова",
                                        "phone": "+7 701 555 12 40", "email": "orders@kancmarket.kz", "note": ""})
    supplier_b = store.create_supplier({"name": "Altyn Dala Food", "contact_person": "Ержан Қасымов",
                                        "phone": "+7 747 210 33 08", "email": "", "note": ""})
    catalog = [
        ("Шариктік қалам, көк", "PEN-001", "Кеңсе тауарлары", "дана", 180, 40, 4500, 9000),
        ("A4 қағаз, 500 парақ", "PAP-A4", "Кеңсе тауарлары", "қорап", 6, 10, 210000, 289000),
        ("Степлер №24", "STP-24", "Кеңсе тауарлары", "дана", 14, 5, 189000, 260000),
        ("Сүт 3,2%, 1 л", "MLK-32", "Азық-түлік", "л", 42, 20, 38050, 52000),
        ("Қант, 1 кг", "SGR-1", "Азық-түлік", "кг", 0, 10, 45000, 60000),
        ("Күріш, 5 кг", "RCE-5", "Азық-түлік", "қорап", 23, 8, 310000, 420000),
        ("USB-C кабель, 1 м", "USB-C1", "Электроника", "дана", 35, 10, 120000, 250000),
        ("Батарейка AA, 4 дана", "BAT-AA4", "Электроника", "орам", 9, 12, 95000, 160000),
        ("Сабын, 90 г", "SOAP-90", "Тұрмыстық", "дана", 64, 20, 25000, 40000),
        ("Қоқыс пакеті, 30 л", "BAG-30", "Тұрмыстық", "орам", 31, 10, 60000, 95000),
    ]
    ids = {}
    for name, sku, category, unit, qty, min_qty, cost, price in catalog:
        ids[sku] = store.create_product(
            {"name": name, "sku": sku, "category": category, "unit": unit, "min_quantity": min_qty,
             "purchase_price": cost, "sale_price": price, "description": ""},
            0, "", created_at=now - timedelta(days=20),
        )
        if qty:
            store.register_movement(ids[sku], "IN", qty + 40, "Бастапқы қалдық",
                                    supplier_a if category == "Кеңсе тауарлары" else supplier_b,
                                    created_at=now - timedelta(days=15))
            store.register_movement(ids[sku], "OUT", 40, "", created_at=now - timedelta(days=14))
    pattern = [("PEN-001", "OUT", 12), ("MLK-32", "OUT", 18), ("MLK-32", "IN", 30), ("SOAP-90", "OUT", 9),
               ("USB-C1", "OUT", 6), ("RCE-5", "OUT", 4), ("PEN-001", "IN", 50), ("MLK-32", "OUT", 22),
               ("BAG-30", "OUT", 7), ("PEN-001", "OUT", 25), ("STP-24", "OUT", 3), ("SOAP-90", "IN", 24),
               ("MLK-32", "OUT", 14), ("PEN-001", "OUT", 18), ("USB-C1", "IN", 15), ("BAT-AA4", "OUT", 5)]
    for day, (sku, kind, qty) in enumerate(pattern):
        try:
            store.register_movement(ids[sku], kind, qty, "Чек №" + str(1020 + day) if kind == "OUT" else "Накладная",
                                    supplier_b if kind == "IN" else None,
                                    created_at=now - timedelta(days=13 - day % 14, hours=day % 5))
        except StoreError:
            pass
    return ids
