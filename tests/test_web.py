"""End-to-end page tests with the Flask test client and the in-memory store."""

import time
import unittest
from unittest import mock

from app import create_app
from tests.fake_store import FakeStore, seed_demo

CSRF = "test-token"


class WebTestCase(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.ids = seed_demo(self.store)
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test", "SUPABASE_URL": "http://supabase.test",
                               "SUPABASE_PUBLISHABLE_KEY": "key"},
                              store_factory=lambda token, user_id: self.store)
        self.client = self.app.test_client()

    def sign_in(self, language="kk", theme="dark"):
        with self.client.session_transaction() as session:
            session["auth"] = {"access_token": "a", "refresh_token": "r", "expires_at": int(time.time()) + 3600,
                               "user_id": "user-1", "email": "demo@qoima.kz"}
            session["profile"] = {"full_name": "Demo", "company": "", "phone": "", "language": language, "theme": theme}
            session["csrf"] = CSRF

    def post(self, url, data=None, **kwargs):
        return self.client.post(url, data={"csrf_token": CSRF, **(data or {})}, **kwargs)


class PagesTest(WebTestCase):
    PAGES = ["/", "/products/", "/products/?status=low", "/products/new", "/products/import", "/movements/",
             "/movements/?type=OUT&q=сүт", "/stocktake/", "/suppliers/", "/suppliers/new", "/reports/",
             "/reports/?days=7", "/account/"]

    def test_login_required(self):
        response = self.client.get("/products/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_public_pages(self):
        for url in ("/login", "/register", "/forgot", "/auth/callback", "/healthz"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_all_pages_render_in_every_language_and_theme(self):
        for language in ("kk", "ru", "en"):
            for theme in ("dark", "light"):
                self.sign_in(language, theme)
                for url in self.PAGES + [f"/products/{self.ids['PEN-001']}", f"/products/{self.ids['PEN-001']}/edit"]:
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200, f"{url} {language} {theme}")
                    html = response.get_data(as_text=True)
                    self.assertIn(f'lang="{language}"', html)
                    self.assertIn(f'data-theme="{theme}"', html)
                    self.assertNotIn("err.", html.replace("err.css", ""))

    def test_empty_warehouse_shows_onboarding(self):
        self.store.__init__()
        self.sign_in()
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("onboard", html)

    def test_unknown_product_is_404(self):
        self.sign_in()
        self.assertEqual(self.client.get("/products/99999").status_code, 404)

    def test_csv_downloads(self):
        self.sign_in("ru")
        for url in ("/reports/products.csv", "/reports/movements.csv?days=30", "/products/import/template.csv"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertIn("text/csv", response.headers["Content-Type"])
            self.assertTrue(response.get_data(as_text=True).startswith("﻿"))


class ActionsTest(WebTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_post_without_csrf_is_rejected(self):
        response = self.client.post("/products/new", data={"name": "X", "sku": "X"})
        self.assertEqual(response.status_code, 400)

    def test_create_product_with_initial_stock(self):
        response = self.post("/products/new", {"name": "Дәптер", "sku": "NB-1", "unit": "дана", "quantity": "12",
                                               "min_quantity": "2", "purchase_price": "150", "sale_price": "250,50"})
        self.assertEqual(response.status_code, 302)
        product = next(p for p in self.store.list_products() if p["sku"] == "NB-1")
        self.assertEqual((product["quantity"], product["sale_price"]), (12, 25050))
        self.assertEqual(self.store.list_movements(product_id=product["id"])[0]["movement_type"], "IN")

    def test_duplicate_sku_shows_error(self):
        response = self.post("/products/new", {"name": "Copy", "sku": "pen-001", "unit": "дана"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("артикулмен", response.get_data(as_text=True))

    def test_edit_does_not_touch_quantity(self):
        product_id = self.ids["PEN-001"]
        before = self.store.get_product(product_id)["quantity"]
        response = self.post(f"/products/{product_id}/edit", {"name": "Жаңа атау", "sku": "PEN-001", "unit": "дана",
                                                               "quantity": "999"})
        self.assertEqual(response.status_code, 302)
        product = self.store.get_product(product_id)
        self.assertEqual((product["name"], product["quantity"]), ("Жаңа атау", before))

    def test_stock_out_more_than_available_fails(self):
        product_id = self.ids["PAP-A4"]
        quantity = self.store.get_product(product_id)["quantity"]
        response = self.post("/movements/", {"movement_type": "OUT", "product_id": str(product_id),
                                             "quantity": str(quantity + 1)})
        self.assertEqual(response.status_code, 400)
        self.assertIn("жеткіліксіз", response.get_data(as_text=True))
        self.assertEqual(self.store.get_product(product_id)["quantity"], quantity)

    def test_stock_in_with_supplier_redirects_back(self):
        product_id = self.ids["SGR-1"]
        supplier_id = self.store.list_suppliers()[0]["id"]
        response = self.post("/movements/", {"movement_type": "IN", "product_id": str(product_id), "quantity": "30",
                                             "supplier_id": str(supplier_id), "next": f"/products/{product_id}"})
        self.assertEqual(response.headers["Location"], f"/products/{product_id}")
        self.assertEqual(self.store.get_product(product_id)["quantity"], 30)
        self.assertEqual(self.store.list_movements(product_id=product_id)[0]["supplier_id"], supplier_id)

    def test_open_redirect_is_blocked(self):
        response = self.post("/movements/", {"movement_type": "IN", "product_id": str(self.ids["SGR-1"]),
                                             "quantity": "1", "next": "//evil.example"})
        self.assertEqual(response.headers["Location"], "/")

    def test_archive_blocks_movements(self):
        product_id = self.ids["USB-C1"]
        self.post(f"/products/{product_id}/toggle")
        self.assertFalse(self.store.get_product(product_id)["is_active"])
        response = self.post("/movements/", {"movement_type": "IN", "product_id": str(product_id), "quantity": "1"})
        self.assertEqual(response.status_code, 400)

    def test_stocktake(self):
        product_id = self.ids["RCE-5"]
        current = self.store.get_product(product_id)["quantity"]
        response = self.post("/stocktake/", {f"counted_{product_id}": str(current - 2), "note": "Айлық"})
        self.assertEqual(response.status_code, 302)
        last = self.store.list_movements(product_id=product_id)[0]
        self.assertEqual((last["movement_type"], last["quantity"], last["note"]), ("ADJUST", -2, "Айлық"))

    def test_import(self):
        csv_text = "name;sku;quantity;min_quantity\nМаркер;MRK-1;5;1\nДубль;PEN-001;1;0\nЖаман;BAD;x;0\n"
        response = self.post("/products/import", {"text": csv_text})
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(p["sku"] == "MRK-1" for p in self.store.list_products()))
        self.assertIn("PEN-001", html)

    def test_supplier_crud(self):
        response = self.post("/suppliers/new", {"name": "Жаңа серіктес", "email": "a@b.kz"})
        self.assertEqual(response.status_code, 302)
        supplier = next(s for s in self.store.list_suppliers() if s["name"] == "Жаңа серіктес")
        self.post(f"/suppliers/{supplier['id']}/delete")
        self.assertIsNone(self.store.get_supplier(supplier["id"]))
        used = self.store.list_suppliers()[0]["id"]
        self.post(f"/suppliers/{used}/delete")
        self.assertIsNotNone(self.store.get_supplier(used))

    def test_preferences_switch_language_and_theme(self):
        response = self.post("/preferences", {"language": "en", "next": "/products/"})
        self.assertEqual(response.headers["Location"], "/products/")
        self.assertEqual(self.store.profile["language"], "en")
        html = self.client.get("/products/").get_data(as_text=True)
        self.assertIn("Products", html)
        self.post("/account/preferences", {"language": "ru", "theme": "light"})
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-theme="light"', html)
        self.assertIn("Склад сегодня", html)

    def test_profile_update(self):
        self.post("/account/profile", {"full_name": "Айбек Нұров", "company": "ЖШС Қойма", "phone": "+7 700"})
        self.assertEqual(self.store.profile["company"], "ЖШС Қойма")
        self.assertIn("АН", self.client.get("/").get_data(as_text=True))

    def test_password_change_calls_supabase(self):
        with mock.patch.object(self.app.extensions["supabase"], "update_user", return_value={}) as update:
            self.post("/account/password", {"password": "newpassword1", "password_confirm": "newpassword1"})
        update.assert_called_once()
        self.assertEqual(update.call_args.args[1], {"password": "newpassword1"})


class AuthFlowTest(WebTestCase):
    def test_login_success_and_failure(self):
        from app.supabase_client import SupabaseError
        supabase = self.app.extensions["supabase"]
        with self.client.session_transaction() as session:
            session["csrf"] = CSRF
        with mock.patch.object(supabase, "sign_in", side_effect=SupabaseError(400, "invalid_credentials", "x")):
            response = self.post("/login", {"email": "a@b.kz", "password": "wrong"})
        self.assertIn("қате", response.get_data(as_text=True))

        payload = {"access_token": "a", "refresh_token": "r", "expires_in": 3600,
                   "user": {"id": "user-1", "email": "a@b.kz"}}
        with mock.patch.object(supabase, "sign_in", return_value=payload):
            response = self.post("/login?next=/reports/", {"email": "a@b.kz", "password": "right-password"})
        self.assertEqual(response.headers["Location"], "/reports/")
        self.assertEqual(self.client.get("/reports/").status_code, 200)

    def test_register_signs_in_immediately(self):
        with self.client.session_transaction() as session:
            session["csrf"] = CSRF
        supabase = self.app.extensions["supabase"]
        session_payload = {"access_token": "a", "refresh_token": "r", "expires_in": 3600,
                           "user": {"id": "user-1", "email": "n@b.kz"}}
        # Supabase returns no session when its "Confirm email" switch is on; the app then signs in itself
        with mock.patch.object(supabase, "sign_up", return_value={"id": "u", "email": "n@b.kz"}), \
                mock.patch.object(supabase, "sign_in", return_value=session_payload) as sign_in:
            response = self.post("/register", {"full_name": "Н", "email": "n@b.kz", "password": "password12",
                                               "password_confirm": "password12"})
        self.assertEqual(response.headers["Location"], "/")
        sign_in.assert_called_once_with("n@b.kz", "password12")
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_register_with_session_in_response(self):
        with self.client.session_transaction() as session:
            session["csrf"] = CSRF
        payload = {"access_token": "a", "refresh_token": "r", "expires_in": 3600,
                   "user": {"id": "user-1", "email": "n@b.kz"}}
        with mock.patch.object(self.app.extensions["supabase"], "sign_up", return_value=payload):
            response = self.post("/register", {"email": "n@b.kz", "password": "password12",
                                               "password_confirm": "password12"})
        self.assertEqual(response.headers["Location"], "/")

    def test_expired_token_is_refreshed(self):
        with self.client.session_transaction() as session:
            session["auth"] = {"access_token": "old", "refresh_token": "r", "expires_at": int(time.time()) - 10,
                               "user_id": "user-1", "email": "a@b.kz"}
        fresh = {"access_token": "new", "refresh_token": "r2", "expires_in": 3600,
                 "user": {"id": "user-1", "email": "a@b.kz"}}
        with mock.patch.object(self.app.extensions["supabase"], "refresh", return_value=fresh):
            self.assertEqual(self.client.get("/").status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session["auth"]["access_token"], "new")


if __name__ == "__main__":
    unittest.main()
