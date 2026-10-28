"""Thin HTTP client for Supabase Auth (GoTrue) and the REST API (PostgREST).

Every data request is sent with the signed-in user's access token, so Postgres
row level security decides what the user may read or change.
"""

import httpx


class SupabaseError(Exception):
    def __init__(self, status, code, message):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code or ""
        self.message = message or ""

    @classmethod
    def from_response(cls, response):
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        code = body.get("error_code") or body.get("code") or body.get("error") or ""
        message = body.get("message") or body.get("msg") or body.get("error_description") or response.text
        return cls(response.status_code, str(code), str(message))


class Supabase:
    def __init__(self, url, key, timeout=15.0):
        self.key = key
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout, headers={"apikey": key})

    def _request(self, method, path, token=None, params=None, json=None, prefer=None):
        headers = {"Authorization": f"Bearer {token or self.key}"}
        if prefer:
            headers["Prefer"] = prefer
        response = self.http.request(method, path, params=params, json=json, headers=headers)
        if response.status_code >= 400:
            raise SupabaseError.from_response(response)
        if not response.content:
            return None
        return response.json()

    # ------------------------------------------------------------ auth

    def sign_up(self, email, password, metadata, redirect_to):
        return self._request(
            "POST", "/auth/v1/signup", params={"redirect_to": redirect_to},
            json={"email": email, "password": password, "data": metadata},
        )

    def sign_in(self, email, password):
        return self._request(
            "POST", "/auth/v1/token", params={"grant_type": "password"},
            json={"email": email, "password": password},
        )

    def refresh(self, refresh_token):
        return self._request(
            "POST", "/auth/v1/token", params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token},
        )

    def sign_out(self, token):
        return self._request("POST", "/auth/v1/logout", token=token)

    def recover(self, email, redirect_to):
        return self._request("POST", "/auth/v1/recover", params={"redirect_to": redirect_to}, json={"email": email})

    def get_user(self, token):
        return self._request("GET", "/auth/v1/user", token=token)

    def update_user(self, token, attributes, redirect_to=None):
        params = {"redirect_to": redirect_to} if redirect_to else None
        return self._request("PUT", "/auth/v1/user", token=token, params=params, json=attributes)

    # ------------------------------------------------------------ data

    def select(self, table, token, params):
        return self._request("GET", f"/rest/v1/{table}", token=token, params=params)

    def insert(self, table, token, row):
        return self._request("POST", f"/rest/v1/{table}", token=token, json=row, prefer="return=representation")

    def update(self, table, token, filters, values):
        return self._request(
            "PATCH", f"/rest/v1/{table}", token=token, params=filters, json=values, prefer="return=representation"
        )

    def delete(self, table, token, filters):
        return self._request("DELETE", f"/rest/v1/{table}", token=token, params=filters)

    def rpc(self, function, token, arguments):
        return self._request("POST", f"/rest/v1/rpc/{function}", token=token, json=arguments)

    # ------------------------------------------------------------ storage

    def upload(self, bucket, path, token, content, content_type):
        response = self.http.post(
            f"/storage/v1/object/{bucket}/{path}", content=content,
            headers={"Authorization": f"Bearer {token}", "Content-Type": content_type,
                     "x-upsert": "true", "Cache-Control": "max-age=31536000"},
        )
        if response.status_code >= 400:
            raise SupabaseError.from_response(response)

    def remove(self, bucket, paths, token):
        return self._request("DELETE", f"/storage/v1/object/{bucket}", token=token, json={"prefixes": list(paths)})

    def public_url(self, bucket, path):
        return f"{str(self.http.base_url).rstrip('/')}/storage/v1/object/public/{bucket}/{path}"
