"""Smart plug through the Home Assistant REST API (issue #9).

  GET  /api/                        -> {"message": "API running."}   (checks URL + token)
  GET  /api/states                  -> all entities (for the picker on the web page)
  GET  /api/states/<entity>         -> {"state": "on" | "off" | "unavailable", "attributes": {...}}
  POST /api/services/<domain>/turn_on | turn_off   {"entity_id": "<entity>"}

Auth: `Authorization: Bearer <long-lived access token>`. As Home Assistant add-on (homeassistant_api: true)
the same API is at http://supervisor/core/api with SUPERVISOR_TOKEN, so nothing has to be entered.
"""
from __future__ import annotations

import os
import re
from typing import Any

import httpx

from . import SUPERVISOR_URL, PowerConfig, PowerError

DOMAINS = ("switch", "light", "input_boolean")
TIMEOUT = 8


class HomeAssistantPower:
    def __init__(self, cfg: PowerConfig) -> None:
        self.cfg = cfg
        if cfg.supervisor:
            self.base, token = SUPERVISOR_URL, os.environ.get("SUPERVISOR_TOKEN", "")
        else:
            if not re.match(r"^https?://[^/\s]+", cfg.url or ""):
                raise PowerError("Home Assistant address must look like http://192.168.1.5:8123")
            self.base, token = cfg.url.rstrip("/"), cfg.token
        if not token:
            raise PowerError("Home Assistant token missing (profile → Security → Long-lived access tokens)")
        self.headers = {"Authorization": f"Bearer {token}"}

    async def _request(self, method: str, path: str, json: Any = None) -> Any:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.request(method, f"{self.base}/api{path}", headers=self.headers, json=json)
        except httpx.HTTPError as e:
            raise PowerError(f"Home Assistant not reachable at {self.base}: {type(e).__name__}") from e
        if r.status_code == 401:
            raise PowerError("Home Assistant refused the token (401) - create a new long-lived access token")
        if r.status_code == 404 and path.startswith("/states/"):
            raise PowerError(f"Home Assistant has no entity {self.cfg.entity!r}")
        if r.status_code >= 400:
            raise PowerError(f"Home Assistant answered HTTP {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else None

    def _domain(self) -> str:
        domain = self.cfg.entity.split(".", 1)[0]
        # the entity goes into the URL: only HA's own format (domain.object_id), nothing else
        if domain not in DOMAINS or not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", self.cfg.entity):
            raise PowerError(f"entity must be a {', '.join(d + '.…' for d in DOMAINS)} (got {self.cfg.entity!r})")
        return domain

    async def state(self) -> str:
        """"on", "off", "unavailable" (plug offline in HA) or "unknown"."""
        self._domain()
        data = await self._request("GET", f"/states/{self.cfg.entity}")
        st = str((data or {}).get("state") or "unknown").lower()
        return st if st in ("on", "off", "unavailable") else "unknown"

    async def turn(self, on: bool) -> None:
        domain = self._domain()
        await self._request("POST", f"/services/{domain}/turn_{'on' if on else 'off'}", {"entity_id": self.cfg.entity})

    async def test(self) -> dict[str, Any]:
        """Check address, token and entity; returns the plug's name and state."""
        await self._request("GET", "/")
        self._domain()
        data = await self._request("GET", f"/states/{self.cfg.entity}")
        return {"state": str(data.get("state")), "name": (data.get("attributes") or {}).get("friendly_name")}

    async def entities(self) -> list[dict[str, Any]]:
        """Switchable entities for the picker: switches, lights, input booleans."""
        data = await self._request("GET", "/states") or []
        out = [{"entity": e["entity_id"], "name": (e.get("attributes") or {}).get("friendly_name") or e["entity_id"],
                "state": e.get("state")}
               for e in data if isinstance(e, dict) and str(e.get("entity_id", "")).split(".", 1)[0] in DOMAINS]
        return sorted(out, key=lambda e: (DOMAINS.index(e["entity"].split(".", 1)[0]), e["name"].lower()))
