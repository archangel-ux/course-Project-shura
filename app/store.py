"""Data access for one signed-in user. All SQL lives in Supabase (tables + RPC functions).

Rows belong to the user's current organization; row level security decides what the
user's role may read or change.
"""

import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx

from app.supabase_client import SupabaseError

logger = logging.getLogger(__name__)

PHOTO_BUCKET = "qoima-photos"

PRODUCT_COLUMNS = (
    "id,name,sku,category,unit,quantity,min_quantity,purchase_price,sale_price,"
    "description,is_active,photo_path,created_at,updated_at"
)
MOVEMENT_COLUMNS = (
    "id,product_id,movement_type,quantity,balance_after,supplier_id,warehouse_id,to_warehouse_id,"
    "document_id,price,note,created_at,"
    "product:qoima_products(name,sku,unit),supplier:qoima_suppliers(name),"
    "warehouse:qoima_warehouses!warehouse_id(name),to_warehouse:qoima_warehouses!to_warehouse_id(name),"
    "document:qoima_documents(number,doc_type)"
)
DOCUMENT_COLUMNS = (
    "id,number,doc_type,warehouse_id,to_warehouse_id,supplier_id,counterparty,note,created_at,"
    "warehouse:qoima_warehouses!warehouse_id(name,address),to_warehouse:qoima_warehouses!to_warehouse_id(name,address),"
    "supplier:qoima_suppliers(name,contact_person,phone)"
)
SUPPLIER_COLUMNS = "id,name,contact_person,phone,email,note,created_at"
WAREHOUSE_COLUMNS = "id,name,address,created_at"
PROFILE_COLUMNS = "id,full_name,company,phone,language,theme,organization_id,telegram_chat_id,notify_telegram,notify_email"
ORGANIZATION_COLUMNS = "id,name,bin,address,phone,bank,iban,bik,director"

# Messages raised by the RPC functions in supabase/schema.sql
DATABASE_MESSAGES = {
    "INSUFFICIENT_STOCK": "err.insufficient_stock",
    "PRODUCT_INACTIVE": "err.product_inactive",
    "NOT_FOUND": "err.not_found",
    "INVALID_QUANTITY": "err.quantity_positive",
    "NOT_AUTHENTICATED": "err.session_expired",
    "NO_ORGANIZATION": "err.no_organization",
    "FORBIDDEN": "err.forbidden",
    "INVALID_TRANSFER": "err.invalid_transfer",
    "LAST_WAREHOUSE": "err.last_warehouse",
    "WAREHOUSE_NOT_EMPTY": "err.warehouse_not_empty",
    "ALREADY_MEMBER": "err.already_member",
    "INVITE_EMAIL_MISMATCH": "err.invite_email",
    "LAST_OWNER": "err.last_owner",
    "INVALID_TYPE": "err.invalid_type",
    "INVALID_INPUT": "err.invalid_choice",
}

# Shared by all requests; httpx.Client is thread safe.
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="supabase")


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
    if error.code == "42501":
        return "err.forbidden"
    if error.status == 401 or error.code in ("PGRST301", "PGRST303"):
        return "err.session_expired"
    for marker, key in DATABASE_MESSAGES.items():
        if marker in error.message:
            return key
    if error.code in ("PGRST202", "PGRST205", "PGRST200", "42P01", "42703", "42883"):
        logger.error("Database schema missing: %s", error)
        return "err.schema_missing"
    logger.error("Supabase request failed: %s", error)
    return "err.server"


def _now():
    return datetime.now(timezone.utc).isoformat()


def parallel(*calls):
    """Run independent store calls at the same time; returns their results in order."""
    futures = [_pool.submit(call) for call in calls]
    return [future.result() for future in futures]


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

    def _rpc(self, function, arguments=None, **kwargs):
        return self._call("rpc", function, self.token, arguments or {}, **kwargs)

    # ------------------------------------------------------------ products

    def list_products(self):
        return self._select("qoima_products", {"select": PRODUCT_COLUMNS, "order": "name.asc"})

    def get_product(self, product_id):
        return self._first("qoima_products", {"select": PRODUCT_COLUMNS, "id": f"eq.{int(product_id)}"})

    def create_product(self, data, initial_quantity, note, warehouse_id=None):
        arguments = {
            "p_name": data["name"], "p_sku": data["sku"], "p_category": data["category"],
            "p_unit": data["unit"], "p_min_quantity": data["min_quantity"],
            "p_purchase_price": data["purchase_price"], "p_sale_price": data["sale_price"],
            "p_description": data["description"], "p_initial_quantity": initial_quantity, "p_note": note,
            "p_warehouse_id": warehouse_id,
        }
        return self._rpc("qoima_create_product", arguments, duplicate_key="err.sku_taken")

    def update_product(self, product_id, data):
        self._call(
            "update", "qoima_products", self.token, {"id": f"eq.{int(product_id)}"},
            {**data, "updated_at": _now()}, duplicate_key="err.sku_taken",
        )

    def set_product_active(self, product_id, is_active):
        self.update_product(product_id, {"is_active": bool(is_active)})

    # ------------------------------------------------------------ photos

    def photo_url(self, path):
        return self.client.public_url(PHOTO_BUCKET, path) if path else ""

    def upload_photo(self, organization_id, product, content, content_type, extension):
        path = f"{int(organization_id)}/{int(product['id'])}-{secrets.token_hex(6)}.{extension}"
        self._call("upload", PHOTO_BUCKET, path, self.token, content, content_type)
        self.update_product(product["id"], {"photo_path": path})
        if product.get("photo_path"):
            self.delete_photo_file(product["photo_path"])
        return path

    def remove_photo(self, product):
        self.update_product(product["id"], {"photo_path": ""})
        if product.get("photo_path"):
            self.delete_photo_file(product["photo_path"])

    def delete_photo_file(self, path):
        try:
            self._call("remove", PHOTO_BUCKET, [path], self.token)
        except StoreError as error:  # an orphaned file is harmless
            logger.warning("Could not delete photo %s: %s", path, error.key)

    # ------------------------------------------------------------ stock & warehouses

    def list_stock(self, product_id=None, warehouse_id=None):
        params = {"select": "product_id,warehouse_id,quantity"}
        if product_id:
            params["product_id"] = f"eq.{int(product_id)}"
        if warehouse_id:
            params["warehouse_id"] = f"eq.{int(warehouse_id)}"
        return self._select("qoima_stock", params)

    def list_warehouses(self):
        return self._select("qoima_warehouses", {"select": WAREHOUSE_COLUMNS, "order": "id.asc"})

    def get_warehouse(self, warehouse_id):
        return self._first("qoima_warehouses", {"select": WAREHOUSE_COLUMNS, "id": f"eq.{int(warehouse_id)}"})

    def create_warehouse(self, data):
        self._call("insert", "qoima_warehouses", self.token, data, duplicate_key="err.warehouse_taken")

    def update_warehouse(self, warehouse_id, data):
        self._call("update", "qoima_warehouses", self.token, {"id": f"eq.{int(warehouse_id)}"}, data,
                   duplicate_key="err.warehouse_taken")

    def delete_warehouse(self, warehouse_id):
        self._rpc("qoima_delete_warehouse", {"p_warehouse_id": int(warehouse_id)})

    # ------------------------------------------------------------ movements & documents

    def list_movements(self, limit=None, since=None, product_id=None, movement_type=None, document_id=None):
        params = {"select": MOVEMENT_COLUMNS, "order": "created_at.desc,id.desc"}
        if limit:
            params["limit"] = str(int(limit))
        if since:
            params["created_at"] = f"gte.{since.isoformat()}"
        if product_id:
            params["product_id"] = f"eq.{int(product_id)}"
        if movement_type:
            params["movement_type"] = f"eq.{movement_type}"
        if document_id:
            params["document_id"] = f"eq.{int(document_id)}"
            params["order"] = "id.asc"
        return self._select("qoima_movements", params)

    def register_document(self, movement_type, warehouse_id, items, note, supplier_id=None,
                          to_warehouse_id=None, counterparty=""):
        return self._rpc("qoima_register_document", {
            "p_type": movement_type, "p_warehouse_id": int(warehouse_id),
            "p_items": [{"product_id": item["product_id"], "quantity": item["quantity"]} for item in items],
            "p_note": note, "p_supplier_id": supplier_id, "p_to_warehouse_id": to_warehouse_id,
            "p_counterparty": counterparty,
        })

    def get_document(self, document_id):
        return self._first("qoima_documents", {"select": DOCUMENT_COLUMNS, "id": f"eq.{int(document_id)}"})

    def stocktake(self, warehouse_id, items, note):
        return self._rpc("qoima_stocktake", {"p_warehouse_id": int(warehouse_id), "p_items": items, "p_note": note})

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

    # ------------------------------------------------------------ organization & team

    def my_organizations(self):
        return self._rpc("qoima_my_organizations") or []

    def get_organization(self, organization_id):
        return self._first("qoima_organizations", {"select": ORGANIZATION_COLUMNS, "id": f"eq.{int(organization_id)}"})

    def update_organization(self, organization_id, data):
        self._call("update", "qoima_organizations", self.token, {"id": f"eq.{int(organization_id)}"}, data)

    def switch_organization(self, organization_id):
        self._rpc("qoima_switch_organization", {"p_org": int(organization_id)})

    def team(self):
        return self._rpc("qoima_team") or []

    def list_invites(self, organization_id):
        return self._select("qoima_invites", {
            "select": "id,email,role,token,created_at", "organization_id": f"eq.{int(organization_id)}",
            "accepted_at": "is.null", "order": "created_at.desc",
        })

    def create_invite(self, email, role):
        return self._rpc("qoima_create_invite", {"p_email": email, "p_role": role})

    def cancel_invite(self, invite_id):
        self._rpc("qoima_cancel_invite", {"p_invite_id": int(invite_id)})

    def invite_info(self, token):
        rows = self._rpc("qoima_invite_info", {"p_token": token}) or []
        return rows[0] if rows else None

    def accept_invite(self, token):
        return self._rpc("qoima_accept_invite", {"p_token": token})

    def set_member_role(self, user_id, role):
        self._rpc("qoima_set_member_role", {"p_user_id": user_id, "p_role": role})

    def remove_member(self, user_id):
        self._rpc("qoima_remove_member", {"p_user_id": user_id})
