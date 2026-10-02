"""The bridge's side of the connection to PocketPrint3D Cloud (docs/BRIDGE.md sections 5-6).

  not paired → POST /api/bridge/pair/start → show the code (log, GET /api/bridge, web page) → poll until the user entered
               it in the app → bridge token saved in <config dir>/bridge.yaml (0600)
  paired     → WSS /api/bridge/ws (Authorization: Bearer <token>) → hello → welcome → answer requests until the
               connection drops → reconnect with backoff (1 s … 60 s)
Close codes from the cloud: 4401 unknown token / 4001 removed from the account → forget the token and pair again;
4426 bridge too old → wait an hour (the container manager updates it).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
import websockets
import yaml

from . import seal

log = logging.getLogger(__name__)

STATE_FILE = "bridge.yaml"
POLL_S = 3
PING_S = 25
FORGET_TOKEN = (4401, 4001)
TOO_OLD = 4426

Dispatch = Callable[[str, dict[str, Any], "BridgeClient"], Awaitable[Any]]


class MethodError(Exception):
    """An error answer to the cloud: `code` from BRIDGE.md (offline, unknown_printer, busy, invalid, …)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def state_path(settings) -> Path:
    return Path(settings.config_dir or ".") / STATE_FILE


def load_state(settings) -> dict[str, Any]:
    p = state_path(settings)
    data = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.is_file() else {}
    return data if isinstance(data, dict) else {}


def save_state(settings, data: dict[str, Any]) -> None:
    p = state_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(data), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def ensure_identity(settings) -> dict[str, Any]:
    """bridge_id and X25519 key pair, made once and kept."""
    st = load_state(settings)
    if not st.get("bridge_id") or not st.get("private_key"):
        st.setdefault("bridge_id", str(uuid.uuid4()))
        st["private_key"], st["public_key"] = seal.keypair()
        save_state(settings, st)
    return st


def default_name() -> str:
    """Name suggested to the cloud: PRINTSHARE_NAME, else the host name - unless it is a Docker container id."""
    name = (os.environ.get("PRINTSHARE_NAME") or socket.gethostname() or "").strip()
    if not name or re.fullmatch(r"[0-9a-f]{12}|[0-9a-f]{64}", name) or name in ("localhost", "homeassistant"):
        return "PocketPrint3D Server"
    return f"PocketPrint3D ({name[:40]})"


class BridgeClient:
    def __init__(self, settings_getter: Callable[[], Any], dispatch: Dispatch, version: str) -> None:
        self.settings = settings_getter
        self.dispatch = dispatch
        self.version = version
        self.state = "off"                # off | pairing | connecting | connected | error
        self.code: str | None = None
        self.code_expires: float | None = None
        self.last_error: str | None = None
        self.connected_since: float | None = None
        self._ws = None
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    # ---------- settings ----------
    def enabled(self) -> bool:
        s = self.settings()
        if getattr(s, "cloud", False):
            return False
        flag = load_state(s).get("enabled")
        return bool(flag) if flag is not None else bool(getattr(s, "bridge", False))

    def base_url(self) -> str:
        return str(getattr(self.settings(), "bridge_url", "") or "https://api.pocketprint3d.com").rstrip("/")

    def public(self) -> dict[str, Any]:
        st = load_state(self.settings())
        return {"enabled": self.enabled(), "state": self.state if self.enabled() else "off",
                "code": self.code if self.state == "pairing" else None,
                "code_expires_in": max(0, int(self.code_expires - time.time())) if self.code_expires and self.state == "pairing" else None,
                "paired": bool(st.get("token")), "account": st.get("account"), "cloud": self.base_url(),
                "bridge_id": st.get("bridge_id"), "connected_since": self.connected_since, "error": self.last_error}

    def set_enabled(self, on: bool) -> None:
        st = load_state(self.settings())
        st["enabled"] = bool(on)
        save_state(self.settings(), st)
        self._kick()

    def forget(self) -> None:
        """Pair again (e.g. another account): drop the token; the cloud replaces it when the new code is entered."""
        st = load_state(self.settings())
        st.pop("token", None)
        st.pop("account", None)
        save_state(self.settings(), st)
        self._kick()

    def _kick(self) -> None:
        self._wake.set()
        if self._ws is not None:
            asyncio.ensure_future(self._ws.close(1000, "settings changed"))

    async def _sleep(self, seconds: float) -> None:
        """Wait, but wake up at once when the settings change."""
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), seconds)
        except asyncio.TimeoutError:
            pass

    # ---------- main loop ----------
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                if not self.enabled():
                    self.state, self.code = "off", None
                    await self._sleep(30)
                    continue
                st = ensure_identity(self.settings())
                if not st.get("token"):
                    await self._pair(st)
                    backoff = 1.0
                    continue
                wait = await self._connect(st)
                backoff = 1.0 if wait == 0 else backoff
                if wait is None:                              # dropped: reconnect with backoff
                    await self._sleep(backoff + random.random())
                    backoff = min(backoff * 2, 60)
                elif wait:
                    await self._sleep(wait)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - never let the loop die
                self.state, self.last_error = "error", str(e)[:300]
                log.warning("bridge: %s", e)
                await self._sleep(backoff + random.random())
                backoff = min(backoff * 2, 60)

    # ---------- pairing ----------
    async def _pair(self, st: dict[str, Any]) -> None:
        base = self.base_url()
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(f"{base}/api/bridge/pair/start", json={
                "bridge_id": st["bridge_id"], "public_key": st["public_key"], "version": self.version,
                "name": default_name()})
            if r.status_code != 200:
                raise RuntimeError(f"pairing refused by {base}: HTTP {r.status_code} {r.text[:200]}")
            start = r.json()
            self.state, self.code = "pairing", start["code"]
            self.code_expires = time.time() + float(start.get("expires_in") or 600)
            self.last_error = None
            log.info("PocketPrint3D Cloud: pairing code %s - enter it in the app (Settings → Brücke verbinden)", self.code)
            while self.enabled() and time.time() < self.code_expires:
                await self._sleep(POLL_S)
                r = await http.post(f"{base}/api/bridge/pair/poll", json={"bridge_id": st["bridge_id"],
                                                                         "poll": start["poll"]})
                if r.status_code in (404, 410):
                    break                                    # expired or reset: start again with a new code
                if r.status_code != 200:
                    continue
                body = r.json()
                if body.get("status") == "paired" and body.get("token"):
                    st = load_state(self.settings())
                    st["token"], st["account"] = body["token"], body.get("account")
                    save_state(self.settings(), st)
                    self.code = None
                    log.info("PocketPrint3D Cloud: paired with %s", body.get("account"))
                    return
        self.code = None

    # ---------- connection ----------
    async def _connect(self, st: dict[str, Any]) -> float | None:
        """Returns how long to wait before the next attempt: 0 = at once, None = backoff."""
        url = self.base_url().replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/api/bridge/ws"
        self.state = "connecting"
        try:
            async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {st['token']}"},
                                          open_timeout=15, ping_interval=PING_S, ping_timeout=20,
                                          max_size=8 * 1024 * 1024) as ws:
                await ws.send(json.dumps({"type": "hello", "bridge_id": st["bridge_id"], "version": self.version,
                                          "printers": await self._printers()}))
                welcome = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if welcome.get("type") != "welcome":
                    raise RuntimeError(f"unexpected answer from the cloud: {str(welcome)[:200]}")
                self._ws, self.state, self.connected_since, self.last_error = ws, "connected", time.time(), None
                log.info("PocketPrint3D Cloud: connected")
                tasks: set[asyncio.Task] = set()
                async for text in ws:
                    try:
                        msg = json.loads(text)
                    except ValueError:
                        continue
                    if isinstance(msg, dict) and msg.get("type") == "req":
                        t = asyncio.create_task(self._answer(ws, msg))
                        tasks.add(t)
                        t.add_done_callback(tasks.discard)
                return self._closed(ws.close_code, ws.close_reason or "")
        except websockets.ConnectionClosed as e:
            code = e.rcvd.code if e.rcvd else None
            return self._closed(code, e.rcvd.reason if e.rcvd else "")
        except (OSError, asyncio.TimeoutError, websockets.InvalidHandshake) as e:
            self.state, self.last_error = "connecting", f"cloud not reachable ({e.__class__.__name__})"
            return None
        finally:
            self._ws, self.connected_since = None, None

    def _closed(self, code: int | None, reason: str) -> float | None:
        if code in FORGET_TOKEN:
            log.warning("PocketPrint3D Cloud: %s - pairing again", reason or code)
            st = load_state(self.settings())
            st.pop("token", None)
            st.pop("account", None)
            save_state(self.settings(), st)
            self.last_error = reason or None
            return 0
        if code == TOO_OLD:
            self.state, self.last_error = "error", reason or "this bridge is too old - please update it"
            return 3600
        if code == 1000:                       # closed on purpose (settings changed)
            return 0
        self.state = "connecting"
        return None

    async def _printers(self) -> list[dict[str, Any]]:
        try:
            return await self.dispatch("printers.list", {}, self)
        except Exception:  # noqa: BLE001
            return []

    async def _answer(self, ws, msg: dict[str, Any]) -> None:
        rid, method = msg.get("id"), str(msg.get("method") or "")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        try:
            result = await self.dispatch(method, params, self)
            out = {"id": rid, "type": "res", "ok": True, "result": result}
        except MethodError as e:
            out = {"id": rid, "type": "res", "ok": False, "error": {"code": e.code, "message": str(e)[:500]}}
        except Exception as e:  # noqa: BLE001
            log.exception("bridge method %s", method)
            out = {"id": rid, "type": "res", "ok": False, "error": {"code": "bridge_error", "message": str(e)[:500]}}
        try:
            await ws.send(json.dumps(out))
        except websockets.ConnectionClosed:
            pass

    async def event(self, name: str, data: dict[str, Any]) -> None:
        """Send an event to the cloud (dropped while not connected)."""
        ws = self._ws
        if ws is not None:
            try:
                await ws.send(json.dumps({"type": "event", "event": name, "data": data}))
            except websockets.ConnectionClosed:
                pass

    # ---------- for the methods ----------
    async def download_gcode(self, job: str, target_dir: Path, max_bytes: int = 200 * 1024 * 1024) -> Path:
        """G-code of a job of the paired account (only from the cloud's own job endpoint)."""
        st = load_state(self.settings())
        url = f"{self.base_url()}/api/bridge/jobs/{job}/gcode"
        target_dir.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=120)) as http:
            async with http.stream("GET", url, headers={"Authorization": f"Bearer {st.get('token', '')}"}) as r:
                if r.status_code != 200:
                    await r.aread()
                    raise MethodError("download_failed", f"G-code download failed: HTTP {r.status_code}")
                name = _filename(r.headers.get("content-disposition", "")) or f"{job}.gcode"
                path = target_dir / name
                size = 0
                with path.open("wb") as fh:
                    async for chunk in r.aiter_bytes(1 << 16):
                        size += len(chunk)
                        if size > max_bytes:
                            raise MethodError("too_large", "the G-code is too large")
                        fh.write(chunk)
        return path


def _filename(disposition: str) -> str | None:
    import re
    m = re.search(r"filename\*=UTF-8''([^;]+)", disposition) or re.search(r'filename="?([^";]+)"?', disposition)
    if not m:
        return None
    from urllib.parse import unquote
    name = Path(unquote(m.group(1))).name                       # never a path from the outside
    name = re.sub(r"[^\w.\- ()]+", "_", name).strip(" .")[:120]
    return name if name.lower().endswith(".gcode") else (name + ".gcode" if name else None)
