"""Where an account keeps its spools (0.39.0): the PocketPrint3D cloud ("cloud") or the user's own Spoolman ("spoolman").

The choice is the user's (Settings → Spoolman in the app). Spool numbers mean different spools in the two lists, so the
server has to know which one counts - for an NFC reader that reports a spool, and to tell the printer what is in a slot.

- Cloud account: the choice is stored in its config folder. A cloud server can't reach a Spoolman at home: printers
  behind a bridge ask the bridge, which reads its own Spoolman.
- Home server / bridge: the Spoolman address comes from PRINTSHARE_SPOOLMAN_URL or is set from the app (stored here).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import httpx
import yaml

FILE = "spools.yaml"
SOURCES = ("cloud", "spoolman")
DEFAULT_PORT = 7912


def _path(config_dir: str | Path) -> Path:
    return Path(config_dir or ".") / FILE


def load(config_dir: str | Path) -> dict[str, Any]:
    p = _path(config_dir)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, yaml.YAMLError):
        data = {}
    return data if isinstance(data, dict) else {}


def save(config_dir: str | Path, **changes: Any) -> dict[str, Any]:
    data = {**load(config_dir), **{k: v for k, v in changes.items()}}
    data = {k: v for k, v in data.items() if v not in (None, "")}
    p = _path(config_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("# Set from the PocketPrint3D app - where this account keeps its spools.\n"
                   + yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(p)
    return data


def check_url(url: str) -> str:
    """"192.168.1.20:7912" / "http://spoolman.local" → "http://…" without a trailing slash (ValueError otherwise)."""
    u = (url or "").strip().rstrip("/")
    if u and not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    if not re.match(r"^https?://[^/\s?#]+(/[^\s?#]*)?$", u, re.I) or len(u) > 300:
        raise ValueError("the Spoolman address must look like http://192.168.1.20:7912")
    return u


def spoolman_url(config_dir: str | Path) -> str | None:
    """The Spoolman this server / bridge reaches: PRINTSHARE_SPOOLMAN_URL, else the address set from the app."""
    env = os.environ.get("PRINTSHARE_SPOOLMAN_URL", "").strip()
    url = env or load(config_dir).get("spoolman_url")
    try:
        return check_url(url) if url else None
    except ValueError:
        return None


def candidates(url: str) -> list[str]:
    """The address as given, and with Spoolman's default port when none is given (like the app)."""
    out = [url]
    host = re.sub(r"^https?://", "", url).split("/")[0]
    if ":" not in host:
        out.append(re.sub(r"^(https?://[^/]+)", rf"\1:{DEFAULT_PORT}", url))
    return out


async def check(url: str, timeout: float = 8.0) -> dict[str, Any]:
    """Connection test: {"url" (the address that answered), "version", "spools" (not archived)}."""
    last: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as c:
        for base in candidates(url):
            try:
                info = await c.get(f"{base}/api/v1/info")
                spools = await c.get(f"{base}/api/v1/spool", params={"allow_archived": "false"})
            except httpx.HTTPError as e:
                last = e
                continue
            if info.status_code != 200 or spools.status_code != 200:
                last = RuntimeError(f"HTTP {info.status_code if info.status_code != 200 else spools.status_code}")
                continue
            try:
                version, count = (info.json() or {}).get("version"), len(spools.json() or [])
            except ValueError:
                last = RuntimeError("no Spoolman answer")
                continue
            return {"url": base, "version": version, "spools": count}
    raise RuntimeError(f"Spoolman not reachable: {last}")


async def fetch_spool(url: str, spool_id: int, timeout: float = 8.0) -> dict[str, Any]:
    """{"material", "color" ("#RRGGBB" or None), "name", "vendor"} of a Spoolman spool."""
    last: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as c:
        for base in candidates(url):
            try:
                r = await c.get(f"{base}/api/v1/spool/{int(spool_id)}")
            except httpx.HTTPError as e:
                last = e
                continue
            if r.status_code == 404:
                raise LookupError(f"Spoolman has no spool #{spool_id}")
            if r.status_code != 200:
                last = RuntimeError(f"Spoolman answered HTTP {r.status_code}")
                continue
            f = (r.json() or {}).get("filament") or {}
            hexc = str(f.get("color_hex") or "").lstrip("#")
            return {"material": f.get("material"), "color": "#" + hexc[:6].upper() if len(hexc) >= 6 else None,
                    "name": f.get("name"), "vendor": ((f.get("vendor") or {}).get("name"))}
    raise RuntimeError(f"Spoolman not reachable: {last}")
