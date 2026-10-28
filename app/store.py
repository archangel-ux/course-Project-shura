"""Data access for one signed-in user. All SQL lives in Supabase (tables + RPC functions)."""

import logging
from datetime import datetime, timezone

import httpx

from app.supabase_client import SupabaseError

logger = logging.getLogger(__name__)

PRODUCT_COLUMNS = (
    "id,name,sku,category,unit,quantity,min_quantity,purchase_price,sale_price,"
    "description,is_active,created_at,updated_at"
)
MOVEMENT_COLUMNS = (
    "id,product_id,movement_type,quantity,balance_after,supplier_id,note,created_at,"
    "product:qoima_products(name,sku,unit),supplier:qoima_suppliers(name)"
)
SUPPLIER_COLUMNS = "id,name,contact_person,phone,email,note,created_at"
PROFILE_COLUMNS = "id,full_name,company,phone,language,theme"

# Messages raised by the RPC functions in supabase/schema.sql
DATABASE_MESSAGES = {
    "INSUFFICIENT_STOCK": "err.insufficient_stock",
    "PRODUCT_INACTIVE": "err.product_inactive",
    "NOT_FOUND": "err.not_found",
    "INVALID_QUANTITY": "err.quantity_positive",
    "NOT_AUTHENTICATED": "err.session_expired",
}


class StoreError(Exception):
    def __init__(self, key):
        super().__init__(key)
        self.key = key


def _error_key(error, duplicate_key):
    if error.code == "23505":
        return duplicate_key
    if error.code == "23503":
        return "err.in_use"
    if error.code == "22003":
        return "err.number_too_large"
    if error.status == 401 or error.code in ("PGRST301", "PGRST303"):
        return "err.session_expired"
    for marker, key in DATABASE_MESSAGES.items():
        if marker in error.message:
            return key
    if error.code in ("PGRST202", "PGRST205", "42P01", "42883"):
        logger.error("Database schema missing: %s", error)
        return "err.schema_missing"
    logger.error("Supabase request failed: %s", error)
    return "err.server"


def _now():
    return datetime.now(timezone.utc).isoformat()


class SupabaseStore:
    def __init__(self, client, token, user_id):
        self.client = client
        self.token = token
        self.user_id = user_id

    def _call(self, method, *args, duplicate_key="err.duplicate"):
        try:
            return getattr(self.client, method)(*args)
        except SupabaseError as error:
            raise StoreError(_error_key(error, duplicate_key)) from error
        except httpx.HTTPError as error:
            logger.error("Network error talking to Supabase: %s", error)
            raise StoreError("err.network") from error

    def _select(self, table, params):
        return self._call("select", table, self.token, params) or []

    def _first(self, table, params):
        rows = self._select(table, {**params, "limit": "1"})
        return rows[0] if rows else None

    # ------------------------------------------------------------ products

    def list_products(self):
        return self._select("qoima_products", {"select": PRODUCT_COLUMNS, "order": "name.asc"})

    def get_product(self, product_id):
        return self._first("qoima_products", {"select": PRODUCT_COLUMNS, "id": f"eq.{int(product_id)}"})

    def create_product(self, data, initial_quantity, note):
        arguments = {
            "p_name": data["name"], "p_sku": data["sku"], "p_category": data["category"],
            "p_unit": data["unit"], "p_min_quantity": data["min_quantity"],
            "p_purchase_price": data["purchase_price"], "p_sale_price": data["sale_price"],
            "p_description": data["description"], "p_initial_quantity": initial_quantity, "p_note": note,
        }
        return self._call("rpc", "qoima_create_product", self.token, arguments, duplicate_key="err.sku_taken")

    def update_product(self, product_id, data):
        self._call(
            "update", "qoima_products", self.token, {"id": f"eq.{int(product_id)}"},
            {**data, "updated_at": _now()}, duplicate_key="err.sku_taken",
        )

    def set_product_active(self, product_id, is_active):
        self._call(
            "update", "qoima_products", self.token, {"id": f"eq.{int(product_id)}"},
            {"is_active": bool(is_active), "updated_at": _now()},
        )

    # ------------------------------------------------------------ movements

    def list_movements(self, limit=None, since=None, product_id=None, movement_type=None):
        params = {"select": MOVEMENT_COLUMNS, "order": "created_at.desc,id.desc"}
        if limit:
            params["limit"] = str(int(limit))
        if since:
            params["created_at"] = f"gte.{since.isoformat()}"
        if product_id:
            params["product_id"] = f"eq.{int(product_id)}"
        if movement_type:
            params["movement_type"] = f"eq.{movement_type}"
        return self._select("qoima_movements", params)

    def register_movement(self, product_id, movement_type, quantity, note, supplier_id=None):
        return self._call("rpc", "qoima_register_movement", self.token, {
            "p_product_id": int(product_id), "p_type": movement_type, "p_quantity": quantity,
            "p_note": note, "p_supplier_id": supplier_id,
        })

    def stocktake(self, items, note):
        return self._call("rpc", "qoima_stocktake", self.token, {"p_items": items, "p_note": note})

    # ------------------------------------------------------------ suppliers

    def list_suppliers(self):
        return self._select("qoima_suppliers", {"select": SUPPLIER_COLUMNS, "order": "name.asc"})

    def get_supplier(self, supplier_id):
        return self._first("qoima_suppliers", {"select": SUPPLIER_COLUMNS, "id": f"eq.{int(supplier_id)}"})

    def create_supplier(self, data):
        rows = self._call("insert", "qoima_suppliers", self.token, data, duplicate_key="err.supplier_taken")
        return rows[0]["id"] if rows else None

    def update_supplier(self, supplier_id, data):
        self._call("update", "qoima_suppliers", self.token, {"id": f"eq.{int(supplier_id)}"}, data,
                   duplicate_key="err.supplier_taken")

    def delete_supplier(self, supplier_id):
        self._call("delete", "qoima_suppliers", self.token, {"id": f"eq.{int(supplier_id)}"})

    # ------------------------------------------------------------ profile

    def get_profile(self):
        profile = self._first("qoima_profiles", {"select": PROFILE_COLUMNS, "id": f"eq.{self.user_id}"})
        if profile is None:
            rows = self._call("insert", "qoima_profiles", self.token, {"id": self.user_id})
            profile = rows[0] if rows else {"id": self.user_id}
        return profile

    def update_profile(self, data):
        rows = self._call("update", "qoima_profiles", self.token, {"id": f"eq.{self.user_id}"},
                          {**data, "updated_at": _now()})
        return rows[0] if rows else None
