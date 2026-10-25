"""Minimal Supabase (PostgREST) client over aiohttp. Server side only: it uses the service role key."""
import os

import aiohttp


class DbError(Exception):
    """Raised when the database is missing, misconfigured or rejects a request."""


class Supabase:
    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self._session: aiohttp.ClientSession | None = None

    @property
    def configured(self) -> bool:
        return bool(self.url and self.key)

    async def _request(self, method: str, table: str, *, params=None, json=None, prefer: str | None = None):
        if not self.configured:
            raise DbError("database is not configured")
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        try:
            async with self._session.request(method, f"{self.url}/rest/v1/{table}", params=params, json=json, headers=headers) as r:
                body = await r.json(content_type=None)
                if r.status >= 400:
                    msg = body.get("message") if isinstance(body, dict) else str(body)
                    raise DbError(f"{table}: {msg}")
                return body
        except aiohttp.ClientError as e:
            raise DbError(f"{table}: {e}") from e

    async def insert(self, table: str, rows: list[dict]) -> list[dict]:
        return await self._request("POST", table, json=rows, prefer="return=representation")

    async def select(self, table: str, params: dict) -> list[dict]:
        return await self._request("GET", table, params=params)

    async def update(self, table: str, params: dict, values: dict) -> list[dict]:
        return await self._request("PATCH", table, params=params, json=values, prefer="return=representation")

    async def close(self):
        if self._session:
            await self._session.close()
