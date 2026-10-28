import unittest
from datetime import date, datetime, timedelta, timezone

from app.services import analytics, csv_io, inventory
from app.services.formatting import format_datetime, format_money, money_to_input, parse_timestamp
from app.services.validators import ValidationError, parse_email, parse_money, parse_password, parse_quantity
from tests.fake_store import FakeStore


def product_form(**overrides):
    form = {"name": "Қалам", "sku": "PEN-1", "category": "Кеңсе", "unit": "дана", "min_quantity": "3",
            "purchase_price": "120,50", "sale_price": "200", "description": ""}
    form.update(overrides)
    return form


class ValidatorTest(unittest.TestCase):
    def test_money_to_tiyn(self):
        self.assertEqual(parse_money("1 500,50", "field.sale_price"), 150050)
        self.assertEqual(parse_money("0.1", "field.sale_price"), 10)
        self.assertEqual(parse_money("", "field.sale_price"), 0)

    def test_money_rejects_bad_values(self):
        for value in ("-1", "abc", "1,555", "nan", "1e20"):
            with self.assertRaises(ValidationError):
                parse_money(value, "field.sale_price")

    def test_quantity(self):
        self.assertEqual(parse_quantity("1 000", "field.quantity"), 1000)
        for value in ("1.5", "-2", "x"):
            with self.assertRaises(ValidationError):
                parse_quantity(value, "field.quantity")
        with self.assertRaises(ValidationError):
            parse_quantity("0", "field.quantity", allow_zero=False)

    def test_email_and_password(self):
        self.assertEqual(parse_email(" User@Mail.KZ "), "user@mail.kz")
        with self.assertRaises(ValidationError):
            parse_email("not-an-email")
        with self.assertRaises(ValidationError):
            parse_password("short")
        with self.assertRaises(ValidationError):
            parse_password("longenough1", "different1")

    def test_error_carries_field_key(self):
        with self.assertRaises(ValidationError) as context:
            parse_quantity("abc", "field.min_quantity")
        self.assertEqual(context.exception.key, "err.integer")
        self.assertEqual(context.exception.params["field"], "field.min_quantity")


class FormattingTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(format_money(123456789), "1 234 567,89 ₸")
        self.assertEqual(money_to_input(150000), "1500")
        self.assertEqual(money_to_input(150050), "1500,50")

    def test_timestamp_from_postgrest(self):
        moment = parse_timestamp("2026-10-28T06:03:11.12+00:00")
        self.assertEqual(moment.utcoffset(), timedelta(hours=5))
        self.assertEqual(format_datetime("2026-10-28T06:03:11+00:00"), "28.10.2026 11:03")


class InventoryTest(unittest.TestCase):
    def test_clean_product(self):
        data = inventory.clean_product_form(product_form())
        self.assertEqual(data["purchase_price"], 12050)
        self.assertEqual(data["min_quantity"], 3)
        with self.assertRaises(ValidationError):
            inventory.clean_product_form(product_form(name="  "))

    def test_filters_and_summary(self):
        products = [
            {"id": 1, "name": "Қалам", "sku": "A", "category": "Кеңсе", "quantity": 2, "min_quantity": 5,
             "purchase_price": 100, "sale_price": 200, "is_active": True},
            {"id": 2, "name": "Сүт", "sku": "B", "category": "Азық", "quantity": 20, "min_quantity": 5,
             "purchase_price": 300, "sale_price": 400, "is_active": True},
            {"id": 3, "name": "Ескі", "sku": "C", "category": "Азық", "quantity": 0, "min_quantity": 0,
             "purchase_price": 0, "sale_price": 0, "is_active": False},
        ]
        self.assertEqual([p["id"] for p in inventory.filter_products(products, "ҚАЛ")], [1])
        self.assertEqual([p["id"] for p in inventory.filter_products(products, status="low")], [1])
        self.assertEqual([p["id"] for p in inventory.filter_products(products, status="inactive")], [3])
        self.assertEqual([p["id"] for p in inventory.filter_products(products, category="Азық", status="all")], [2, 3])
        summary = inventory.summary(products)
        self.assertEqual(summary["product_count"], 2)
        self.assertEqual(summary["total_units"], 22)
        self.assertEqual(summary["low_count"], 1)
        self.assertEqual(summary["purchase_value"], 2 * 100 + 20 * 300)

    def test_movement_form(self):
        data = inventory.clean_movement_form(
            {"movement_type": "IN", "product_id": "5", "quantity": "3", "supplier_id": "9"}, {5}, {9})
        self.assertEqual((data["product_id"], data["quantity"], data["supplier_id"]), (5, 3, 9))
        out = inventory.clean_movement_form(
            {"movement_type": "OUT", "product_id": "5", "quantity": "3", "supplier_id": "9"}, {5}, {9})
        self.assertIsNone(out["supplier_id"])
        for bad in ({"movement_type": "X", "product_id": "5", "quantity": "1"},
                    {"movement_type": "IN", "product_id": "6", "quantity": "1"},
                    {"movement_type": "IN", "product_id": "5", "quantity": "0"},
                    {"movement_type": "IN", "product_id": "5", "quantity": "1", "supplier_id": "77"}):
            with self.assertRaises(ValidationError):
                inventory.clean_movement_form(bad, {5}, {9})

    def test_stocktake_form(self):
        products = [{"id": 1, "quantity": 5}, {"id": 2, "quantity": 7}]
        items = inventory.clean_stocktake_form({"counted_1": "4", "counted_2": ""}, products)
        self.assertEqual(items, [{"product_id": 1, "counted": 4, "difference": -1}])
        with self.assertRaises(ValidationError):
            inventory.clean_stocktake_form({}, products)


class FakeStoreRulesTest(unittest.TestCase):
    """The fake store mirrors schema.sql rules; these tests document those rules."""

    def setUp(self):
        self.store = FakeStore()
        data = inventory.clean_product_form(product_form())
        self.product_id = self.store.create_product(data, 5, "start")

    def test_stock_cannot_go_negative(self):
        from app.store import StoreError
        with self.assertRaises(StoreError):
            self.store.register_movement(self.product_id, "OUT", 6, "")
        self.assertEqual(self.store.get_product(self.product_id)["quantity"], 5)

    def test_balance_matches_history(self):
        self.store.register_movement(self.product_id, "IN", 10, "")
        self.store.register_movement(self.product_id, "OUT", 4, "")
        self.store.stocktake([{"product_id": self.product_id, "counted": 9}], "count")
        history = self.store.list_movements()
        total = sum(m["quantity"] if m["movement_type"] != "OUT" else -m["quantity"] for m in history)
        self.assertEqual(total, self.store.get_product(self.product_id)["quantity"])
        self.assertEqual(history[0]["balance_after"], 9)


class AnalyticsTest(unittest.TestCase):
    def test_daily_flow_and_top(self):
        today = date(2026, 10, 28)
        stamp = datetime(2026, 10, 28, 6, tzinfo=timezone.utc).isoformat()
        old = datetime(2026, 9, 1, tzinfo=timezone.utc).isoformat()
        movements = [
            {"movement_type": "IN", "quantity": 10, "created_at": stamp, "product_id": 1, "product": {"name": "A"}},
            {"movement_type": "OUT", "quantity": 4, "created_at": stamp, "product_id": 1, "product": {"name": "A"}},
            {"movement_type": "OUT", "quantity": 7, "created_at": stamp, "product_id": 2, "product": {"name": "B"}},
            {"movement_type": "OUT", "quantity": 99, "created_at": old, "product_id": 2, "product": {"name": "B"}},
        ]
        series = analytics.daily_flow(movements, today, days=14)
        self.assertEqual(len(series), 14)
        self.assertEqual((series[-1]["in"], series[-1]["out"]), (10, 11))
        bars, peak = analytics.chart_geometry(series)
        self.assertEqual(peak, 11)
        self.assertEqual(bars[-1]["out_h"], 160)
        top = analytics.top_outflow(movements[:3])
        self.assertEqual([row["name"] for row in top], ["B", "A"])


class CsvTest(unittest.TestCase):
    def t(self, key, **_):
        return key

    def test_import_semicolon_with_kazakh_headers(self):
        text = "﻿Атауы;Артикул;Санаты;Қалдық;Сатып алу бағасы\nҚалам;P-1;Кеңсе;10;45,5\nДәптер;P-2;;x;1\n;;;;\nҚалам 2;p-1;;1;1\n"
        rows, errors = csv_io.parse_import(text)
        self.assertEqual(len(rows), 1)
        line, data, quantity = rows[0]
        self.assertEqual((line, data["sku"], quantity, data["purchase_price"]), (2, "P-1", 10, 4550))
        self.assertEqual([line for line, _ in errors], [3, 5])

    def test_import_comma_english_headers(self):
        rows, errors = csv_io.parse_import("name,sku,quantity\nPen,A1,3\n")
        self.assertEqual((len(rows), len(errors)), (1, 0))

    def test_import_requires_headers(self):
        with self.assertRaises(ValidationError):
            csv_io.parse_import("foo;bar\n1;2\n")
        with self.assertRaises(ValidationError):
            csv_io.parse_import("   ")

    def test_export_products(self):
        content = csv_io.products_csv([{
            "sku": "A", "name": "Қалам", "category": "", "unit": "дана", "quantity": 3, "min_quantity": 1,
            "purchase_price": 12050, "sale_price": 20000, "is_active": True, "description": "",
        }], self.t)
        self.assertTrue(content.startswith("﻿"))
        self.assertIn("A;Қалам;;дана;3;1;120,50;200,00;status.active;", content)


if __name__ == "__main__":
    unittest.main()
