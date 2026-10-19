"""httpx async client dla api.sejm.gov.pl (Sejm - proces legislacyjny).

API jest publiczne, bez auth, JSON-only (`Accept: application/json`). Term jest
segmentem sciezki (`/sejm/term10/...`), wiec kazda metoda bierze numer kadencji.
"""

from __future__ import annotations

import asyncio
from typing import Any, Self

import httpx

from . import BASE_URL, USER_AGENT


class SejmProcessClient:
    """Async HTTP client dla api.sejm.gov.pl.

    Uzywaj jako async context manager:
        async with SejmProcessClient() as c:
            raw, url = await c.get_process(10, "32")
    """

    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
            timeout=timeout,
            follow_redirects=True,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(
        self,
        url: str,
        params: dict | None = None,
        max_retries: int = 3,
    ) -> tuple[Any, str]:
        """GET + JSON z retry/backoff na 429/503. 404 leci jako HTTPStatusError.

        Returns:
            (parsed_json, full_url)
        """
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = await self._client.get(url, params=params)
            except httpx.RequestError as exc:
                last_exc = exc
                await asyncio.sleep(2**attempt)
                continue

            if resp.status_code in (429, 503):
                wait = resp.headers.get("Retry-After")
                try:
                    delay = float(wait) if wait is not None else 2**attempt
                except ValueError:
                    delay = 2**attempt
                await asyncio.sleep(min(delay, 60.0))
                continue

            resp.raise_for_status()
            return resp.json(), str(resp.request.url)

        if last_exc is not None:
            raise last_exc
        raise httpx.HTTPError(f"Failed after {max_retries} retries: {url}")

    # ---------- procesy legislacyjne ----------

    async def list_processes(
        self,
        term: int,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], str]:
        """GET /sejm/term{N}/processes - lista projektow (bez `stages`).

        Returns:
            (lista surowych rekordow, source_url)
        """
        url = f"/sejm/term{term}/processes"
        data, full_url = await self._get(url, params={"limit": limit, "offset": offset})
        return data, full_url

    async def get_process(self, term: int, number: str) -> tuple[dict, str]:
        """GET /sejm/term{N}/processes/{number} - pelny proces ze `stages[]`.

        Returns:
            (surowy rekord, source_url)
        """
        url = f"/sejm/term{term}/processes/{number}"
        data, full_url = await self._get(url)
        return data, full_url

    # ---------- druki ----------

    async def get_print(self, term: int, number: str) -> tuple[dict, str]:
        """GET /sejm/term{N}/prints/{number} - druk parlamentarny.

        Returns:
            (surowy rekord, source_url)
        """
        url = f"/sejm/term{term}/prints/{number}"
        data, full_url = await self._get(url)
        return data, full_url
