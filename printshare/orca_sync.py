"""Sync a user's own OrcaSlicer presets from their Orca Cloud account (issue #7, 0.41.0).

Orca Cloud lets external apps read a user's synced presets ("External App Pairing"):
- Pairing = OAuth 2.0 Device Authorization Grant (RFC 8628): `POST /oauth/device/code` (form: client_id, scope
  `sync:read`) → the user confirms the code in their Orca Cloud settings → `POST /oauth/token` is polled until it
  answers with tokens. No redirect URL, so it works from a LAN address or a phone.
- `GET /api/v1/external/sync/pull` (Bearer access token) → `{next_cursor, upserts: [{id, name, content, …}], deletes}`;
  `content` = the preset JSON (with `inherits`).
- Access tokens `oc_ext_…` last 24 h; refresh tokens `oc_ext_rt_…` are single-use and rotate: re-using a spent one
  revokes the whole pairing → the new pair is saved (atomically) before it is used, refreshes run under a lock.
- Every app needs a `client_id` registered with the Orca Cloud team (public client, no secret). PocketPrint3D has none
  yet, so it is a setting: env ORCA_CLOUD_CLIENT_ID (server operator) or entered by the user in the app. It is never
  part of the source code.

State per account in `<config dir>/orca_cloud.yaml` (0600, tokens never leave the server). Synced presets are stored
like uploaded ones (`profiles/`, `user_profiles.store_presets`), so choosing them works unchanged; presets that
disappeared from Orca Cloud are removed unless a printer uses them. Checked against the real API's error answers
(form-encoded requests, 2026-10-07); a full pairing still needs a registered client_id.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml

from . import user_profiles
from .orca_cloud import presets_of
from .profiles import ProfileLibrary

log = logging.getLogger(__name__)

BASE = "https://api.orcaslicer.com"
FILE = "orca_cloud.yaml"
SCOPE = "sync:read"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
MAX_PRESETS = 500
MAX_PAGES = 20
SYNC_EVERY_S = 6 * 3600


def user_agent(version: str) -> str:
    # Cloudflare in front of api.orcaslicer.com blocks unusual user agents: an honest one
    return f"PocketPrint3D/{version} (+https://github.com/halvar20000/printshare)"


class OrcaSyncError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ---------- state ----------
def _path(config_dir: str | Path) -> Path:
    return Path(config_dir or ".") / FILE


def load(config_dir: str | Path) -> dict[str, Any]:
    p = _path(config_dir)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, yaml.YAMLError):
        data = {}
    return data if isinstance(data, dict) else {}


def save(config_dir: str | Path, data: dict[str, Any]) -> None:
    p = _path(config_dir)
    data = {k: v for k, v in data.items() if v not in (None, "", [])}
    if not data:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("# Orca Cloud pairing of PocketPrint3D - holds tokens, keep it private.\n"
                   + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(p)


def update(config_dir: str | Path, **changes: Any) -> dict[str, Any]:
    data = {**load(config_dir), **changes}
    save(config_dir, data)
    return load(config_dir)


def client_id(config_dir: str | Path) -> tuple[str | None, str | None]:
    """(client_id, where from: "server" | "user")."""
    env = os.environ.get("ORCA_CLOUD_CLIENT_ID", "").strip()
    if env:
        return env, "server"
    own = str(load(config_dir).get("client_id") or "").strip()
    return (own, "user") if own else (None, None)


def check_client_id(value: str) -> str:
    v = (value or "").strip()
    if not v or len(v) > 200 or any(c.isspace() for c in v) or not v.isprintable():
        raise OrcaSyncError("the Orca app ID looks wrong (no spaces, at most 200 characters)")
    return v


def mask(value: str | None) -> str | None:
    if not value:
        return None
    return value if len(value) <= 12 else f"{value[:7]}…{value[-4:]}"


# ---------- pairing (device flow) ----------
# config dir → {"device_code", "user_code", "verification_uri", "verification_uri_complete", "expires_at", "interval",
#               "task", "error"} - in memory: a restart only means "start pairing again"
PENDING: dict[str, dict[str, Any]] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def _lock(config_dir: str | Path) -> asyncio.Lock:
    return _LOCKS.setdefault(str(config_dir), asyncio.Lock())


def _error_text(r: httpx.Response) -> tuple[str, str]:
    try:
        body = r.json()
    except ValueError:
        return "", f"HTTP {r.status_code}"
    err = body.get("error")
    if isinstance(err, dict):           # {"error": {"code", "message"}} on the API
        return str(err.get("code") or ""), str(err.get("message") or err.get("code") or r.status_code)
    return str(err or ""), str(body.get("error_description") or err or f"HTTP {r.status_code}")


class OrcaSync:
    """All calls for one server; `http` can be replaced in tests (base URL included)."""

    def __init__(self, library: Callable[[], ProfileLibrary], version: str = "0", base: str = BASE, http: httpx.AsyncClient | None = None) -> None:
        self.library = library          # () -> ProfileLibrary (OrcaSlicer system presets, to check `inherits`)
        self.base = base.rstrip("/")
        self.version = version
        self._http = http

    def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=20, follow_redirects=False,
                                               headers={"User-Agent": user_agent(self.version)})

    async def _post_form(self, path: str, form: dict[str, str]) -> httpx.Response:
        c = self._client()
        try:
            return await c.post(self.base + path, data=form, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise OrcaSyncError(f"Orca Cloud not reachable ({e.__class__.__name__})", 502) from e
        finally:
            if c is not self._http:
                await c.aclose()

    # -- pairing --
    async def start(self, config_dir: str) -> dict[str, Any]:
        cid, _ = client_id(config_dir)
        if not cid:
            raise OrcaSyncError("enter the Orca app ID first", 409)
        r = await self._post_form("/oauth/device/code", {"client_id": cid, "scope": SCOPE})
        if r.status_code != 200:
            code, text = _error_text(r)
            if code == "invalid_client":
                raise OrcaSyncError("Orca Cloud doesn't know this app ID")
            raise OrcaSyncError(f"Orca Cloud: {text}", 502)
        d = r.json()
        if not d.get("device_code") or not d.get("user_code"):
            raise OrcaSyncError("Orca Cloud sent no pairing code", 502)
        old = PENDING.pop(config_dir, None)
        if old and old.get("task"):
            old["task"].cancel()
        p = {"device_code": d["device_code"], "user_code": d["user_code"],
             "verification_uri": d.get("verification_uri") or d.get("verification_url"),
             "verification_uri_complete": d.get("verification_uri_complete"),
             "expires_at": time.time() + float(d.get("expires_in") or 600),
             "interval": max(2.0, float(d.get("interval") or 5)), "error": None}
        PENDING[config_dir] = p
        p["task"] = asyncio.get_running_loop().create_task(self._poll(config_dir, p, cid))
        return public_pending(p)

    async def _poll(self, config_dir: str, p: dict[str, Any], cid: str) -> None:
        try:
            while time.time() < p["expires_at"]:
                await asyncio.sleep(p["interval"])
                r = await self._post_form("/oauth/token", {"grant_type": DEVICE_GRANT, "device_code": p["device_code"],
                                                           "client_id": cid})
                if r.status_code == 200:
                    self._store_tokens(config_dir, r.json(), connected=True)
                    PENDING.pop(config_dir, None)
                    try:
                        await self.sync(config_dir)
                    except OrcaSyncError as e:
                        update(config_dir, last_error=str(e))
                    return
                code, text = _error_text(r)
                if code == "authorization_pending":
                    continue
                if code == "slow_down":
                    p["interval"] += 5
                    continue
                p["error"] = {"access_denied": "denied", "expired_token": "expired"}.get(code, text)
                return
            p["error"] = "expired"
        except OrcaSyncError as e:
            p["error"] = str(e)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - a pairing must never take the server down
            log.exception("Orca Cloud pairing failed")
            p["error"] = str(e)

    def _store_tokens(self, config_dir: str, t: dict[str, Any], connected: bool = False) -> None:
        if not t.get("access_token"):
            raise OrcaSyncError("Orca Cloud sent no token", 502)
        changes: dict[str, Any] = {"access_token": t["access_token"],
                                   "access_expires": time.time() + float(t.get("expires_in") or 86400) - 300}
        if t.get("refresh_token"):
            changes["refresh_token"] = t["refresh_token"]
        if connected:
            changes.update(connected_at=time.time(), last_error=None)
        update(config_dir, **changes)        # saved before anything uses it (rotating refresh tokens)

    async def access_token(self, config_dir: str) -> str:
        async with _lock(config_dir):
            st = load(config_dir)
            if not st.get("access_token") and not st.get("refresh_token"):
                raise OrcaSyncError("not connected to Orca Cloud", 409)
            if st.get("access_token") and float(st.get("access_expires") or 0) > time.time():
                return st["access_token"]
            cid, _ = client_id(config_dir)
            if not cid or not st.get("refresh_token"):
                raise OrcaSyncError("the Orca Cloud connection has expired - connect again", 409)
            r = await self._post_form("/oauth/token", {"grant_type": "refresh_token",
                                                       "refresh_token": st["refresh_token"], "client_id": cid})
            if r.status_code != 200:
                code, text = _error_text(r)
                if code in ("invalid_grant", "invalid_client", "unauthorized_client"):
                    update(config_dir, access_token=None, access_expires=None, refresh_token=None,
                           last_error="the Orca Cloud connection was ended - connect again")
                    raise OrcaSyncError("the Orca Cloud connection was ended - connect again", 409)
                raise OrcaSyncError(f"Orca Cloud: {text}", 502)
            self._store_tokens(config_dir, r.json())
            return load(config_dir)["access_token"]

    # -- presets --
    async def pull(self, config_dir: str) -> list[dict[str, Any]]:
        token = await self.access_token(config_dir)
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        c = self._client()
        try:
            for _ in range(MAX_PAGES):
                try:
                    r = await c.get(self.base + "/api/v1/external/sync/pull", params={"cursor": cursor} if cursor else None,
                                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
                except httpx.HTTPError as e:
                    raise OrcaSyncError(f"Orca Cloud not reachable ({e.__class__.__name__})", 502) from e
                if r.status_code == 401:
                    update(config_dir, access_token=None, access_expires=None)
                    raise OrcaSyncError("Orca Cloud refused the token - try again", 502)
                if r.status_code != 200:
                    raise OrcaSyncError(f"Orca Cloud: {_error_text(r)[1]}", 502)
                body = r.json()
                out += [u for u in body.get("upserts") or [] if isinstance(u, dict)]
                cursor = body.get("next_cursor")
                if not body.get("has_more") or not cursor or len(out) >= MAX_PRESETS:
                    break
        finally:
            if c is not self._http:
                await c.aclose()
        return out[:MAX_PRESETS]

    async def sync(self, config_dir: str, lib: ProfileLibrary | None = None) -> dict[str, Any]:
        upserts = await self.pull(config_dir)
        lib = lib or await asyncio.to_thread(self.library)
        result = await asyncio.to_thread(store, config_dir, upserts, lib)
        update(config_dir, last_sync=time.time(), last_error=None, files=result["files"], count=len(result["files"]),
               skipped=result["skipped"][:50])
        return result


def public_pending(p: dict[str, Any]) -> dict[str, Any]:
    return {"user_code": p["user_code"], "verification_uri": p.get("verification_uri"),
            "verification_uri_complete": p.get("verification_uri_complete"),
            "expires_in": max(0, int(p["expires_at"] - time.time())), "error": p.get("error")}


def _in_use(config_dir: str | Path) -> set[str]:
    used = set()
    for f in (Path(config_dir) / "printers.d").glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        mf = ((data.get("slicing") or {}) if isinstance(data, dict) else {}).get("machine_file")
        if mf:
            used.add(Path(str(mf)).name)
    return used


def store(config_dir: str | Path, upserts: list[dict[str, Any]], lib: ProfileLibrary) -> dict[str, Any]:
    """Store the pulled presets; presets OrcaSlicer 2.4.2 can't use are skipped, presets gone from Orca Cloud are
    removed (unless a printer uses them)."""
    presets = presets_of({"shared_profiles": [{"content": u.get("content")} for u in upserts]})
    files, skipped = [], []
    for preset in presets:
        try:
            files += [i["file"] for i in user_profiles.store_presets(config_dir, [preset], lib)]
        except user_profiles.ProfileUploadError as e:
            skipped.append({"name": preset.get("name"), "error": str(e)})
    keep = set(files) | _in_use(config_dir)
    removed = []
    for old in load(config_dir).get("files") or []:
        if old not in keep:
            try:
                user_profiles.resolve_file(config_dir, old).unlink()
                removed.append(old)
            except (user_profiles.ProfileUploadError, OSError):
                pass
    return {"files": sorted(set(files)), "skipped": skipped, "removed": removed}


def status(config_dir: str) -> dict[str, Any]:
    st = load(config_dir)
    cid, src = client_id(config_dir)
    p = PENDING.get(config_dir)
    return {"client_id": mask(cid) if src == "server" else cid, "client_id_from": src,
            "connected": bool(st.get("refresh_token") or st.get("access_token")),
            "connected_at": st.get("connected_at"), "last_sync": st.get("last_sync"), "count": st.get("count") or 0,
            "skipped": st.get("skipped") or [], "last_error": st.get("last_error"),
            "pending": public_pending(p) if p else None}


def disconnect(config_dir: str, remove_presets: bool = False) -> dict[str, Any]:
    p = PENDING.pop(config_dir, None)
    if p and p.get("task"):
        p["task"].cancel()
    st = load(config_dir)
    removed = []
    if remove_presets:
        used = _in_use(config_dir)
        for f in st.get("files") or []:
            if f not in used:
                try:
                    user_profiles.resolve_file(config_dir, f).unlink()
                    removed.append(f)
                except (user_profiles.ProfileUploadError, OSError):
                    pass
    save(config_dir, {"client_id": st.get("client_id")})
    return {"removed": removed}


def connected_dirs(config_dir: str | Path, cloud: bool) -> list[str]:
    """Config dirs with an Orca Cloud pairing: the server's own, or every cloud user's."""
    base = Path(config_dir or "/config")
    found = [base / "users" / d.name for d in (base / "users").iterdir() if (d / FILE).is_file()] \
        if cloud and (base / "users").is_dir() else ([base] if (base / FILE).is_file() else [])
    return [str(d) for d in found if load(d).get("refresh_token") or load(d).get("access_token")]
