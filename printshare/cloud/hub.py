"""Live connections of the bridges (docs/BRIDGE.md, section 6), in this process.

Every bridge keeps one WebSocket open (opened by the bridge). The cloud sends requests over it and waits for the
answer; the bridge sends events. Only the methods in METHODS are ever sent - the bridge refuses everything else, too.

Frames (JSON):
  request   {"id", "type": "req", "method", "params"}            cloud → bridge
  response  {"id", "type": "res", "ok": true, "result"} / {"id", "type": "res", "ok": false, "error": {"code", "message"}}
  event     {"type": "event", "event", "data"}                   bridge → cloud
  hello     {"type": "hello", "bridge_id", "version", "printers"} first frame of the bridge; answered with "welcome"
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# method → timeout in seconds (BRIDGE.md section 6)
METHODS: dict[str, float] = {
    "printers.list": 10, "printer.status": 15, "printer.control": 30, "printer.controls": 15,
    "printer.adjust": 15, "printer.temperatures": 15, "printer.camera": 15, "printer.camera.snapshot": 15,
    "printer.power": 20, "printer.filament.info": 15, "printer.filament": 30,
    "job.send": 15 * 60, "watch.state": 10, "watch.mute": 10, "discover": 60,
    "printer.add": 30, "printer.update": 30, "printer.remove": 30,
}
EVENTS = ("printer.state", "watch.alert", "job.progress", "printers.changed", "timelapse.state")
HELLO_TIMEOUT_S = 10
MIN_VERSION = "0.24.0"
MAX_PENDING = 32                 # requests in flight per bridge


class BridgeError(Exception):
    """Shown to the app; `status` is the HTTP status the API answers with."""

    def __init__(self, code: str, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def _version(v: str | None) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(v or "0").split("+")[0].split(".")[:3])
    except ValueError:
        return (0,)


@dataclass
class Connection:
    bridge_id: str
    user_id: str
    ws: Any                                   # starlette WebSocket (send_text / receive_text / close)
    version: str | None = None
    printers: list[dict[str, Any]] = field(default_factory=list)
    connected: float = field(default_factory=time.time)
    pending: dict[str, asyncio.Future] = field(default_factory=dict)
    states: dict[str, dict[str, Any]] = field(default_factory=dict)   # last printer.state event per printer


class BridgeHub:
    def __init__(self, on_seen=None) -> None:
        self.conns: dict[str, Connection] = {}
        self._ids = itertools.count(1)
        self.on_seen = on_seen               # callback(bridge_id, version) → last_seen in the database
        self.listeners: list = []            # callback(bridge_id, user_id, event, data), e.g. push notifications later
        self.on_printers = None              # callback(bridge_id, user_id, printers) on hello and printers.changed

    # ---------- state ----------
    def online(self, bridge_id: str) -> bool:
        return bridge_id in self.conns

    def info(self, bridge_id: str) -> dict[str, Any]:
        c = self.conns.get(bridge_id)
        if c is None:
            return {"online": False, "printers": [], "connected": None}
        return {"online": True, "printers": c.printers, "connected": c.connected, "version": c.version}

    def count(self) -> int:
        return len(self.conns)

    # ---------- the bridge's socket ----------
    async def serve(self, ws, bridge: dict[str, Any]) -> None:
        """Runs for as long as the bridge stays connected (called by the WebSocket endpoint after accept())."""
        try:
            hello = json.loads(await asyncio.wait_for(ws.receive_text(), HELLO_TIMEOUT_S))
        except (asyncio.TimeoutError, ValueError):
            await ws.close(4400, "expected hello")
            return
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            await ws.close(4400, "expected hello")
            return
        version = str(hello.get("version") or "")[:40]
        if _version(version) < _version(MIN_VERSION):
            await ws.send_text(json.dumps({"type": "error", "code": "too_old", "min_version": MIN_VERSION}))
            await ws.close(4426, f"please update the bridge to {MIN_VERSION} or newer")
            return
        conn = Connection(bridge["id"], bridge["user_id"], ws, version, _printers(hello.get("printers")))
        old = self.conns.get(conn.bridge_id)
        self.conns[conn.bridge_id] = conn
        if old is not None:                      # the same bridge connected again: the new socket wins
            self._fail_pending(old, BridgeError("bridge_reconnected", "the bridge reconnected - please try again", 503))
            try:
                await old.ws.close(4000, "replaced by a new connection")
            except Exception:  # noqa: BLE001 - already gone
                pass
        if self.on_seen:
            self.on_seen(conn.bridge_id, version)
        self._printers_changed(conn)
        await ws.send_text(json.dumps({"type": "welcome", "bridge_id": conn.bridge_id, "min_version": MIN_VERSION,
                                       "methods": sorted(METHODS)}))
        log.info("bridge %s connected (%s, %d printers)", conn.bridge_id, version, len(conn.printers))
        try:
            while True:
                text = await ws.receive_text()
                if len(text) > 4_000_000:
                    continue
                try:
                    msg = json.loads(text)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    self._handle(conn, msg)
        except Exception:  # noqa: BLE001 - WebSocketDisconnect or a broken connection
            pass
        finally:
            if self.conns.get(conn.bridge_id) is conn:
                del self.conns[conn.bridge_id]
            self._fail_pending(conn, BridgeError("bridge_offline", "the bridge went offline", 503))
            if self.on_seen:
                self.on_seen(conn.bridge_id, None)
            log.info("bridge %s disconnected", conn.bridge_id)

    def _handle(self, conn: Connection, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "res":
            fut = conn.pending.pop(str(msg.get("id")), None)
            if fut is None or fut.done():
                return
            if msg.get("ok"):
                fut.set_result(msg.get("result"))
            else:
                err = msg.get("error") if isinstance(msg.get("error"), dict) else {}
                code = str(err.get("code") or "bridge_error")[:40]
                fut.set_exception(BridgeError(code, str(err.get("message") or code)[:500], _status(code)))
        elif kind == "event" and msg.get("event") in EVENTS:
            data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
            if msg["event"] == "printers.changed":
                conn.printers = _printers(data.get("printers"))
                self._printers_changed(conn)
            elif msg["event"] == "printer.state" and isinstance(data.get("printer"), str):
                conn.states[data["printer"]] = {**data, "at": time.time()}
            for listener in self.listeners:
                try:
                    listener(conn.bridge_id, conn.user_id, msg["event"], data)
                except Exception:  # noqa: BLE001
                    log.exception("bridge event listener")

    def _printers_changed(self, conn: Connection) -> None:
        if self.on_printers:
            try:
                self.on_printers(conn.bridge_id, conn.user_id, conn.printers)
            except Exception:  # noqa: BLE001
                log.exception("bridge printers")

    @staticmethod
    def _fail_pending(conn: Connection, err: BridgeError) -> None:
        for fut in conn.pending.values():
            if not fut.done():
                fut.set_exception(err)
        conn.pending.clear()

    # ---------- requests to a bridge ----------
    async def call(self, bridge_id: str, user_id: str, method: str, params: dict[str, Any] | None = None,
                   timeout: float | None = None) -> Any:
        if method not in METHODS:
            raise ValueError(f"not a bridge method: {method}")
        conn = self.conns.get(bridge_id)
        if conn is None or conn.user_id != user_id:
            raise BridgeError("bridge_offline", "the bridge is offline - is it running at home?", 503)
        if len(conn.pending) >= MAX_PENDING:
            raise BridgeError("bridge_busy", "the bridge is busy - please try again", 429)
        rid = f"r{next(self._ids)}"
        fut = asyncio.get_running_loop().create_future()
        conn.pending[rid] = fut
        try:
            await conn.ws.send_text(json.dumps({"id": rid, "type": "req", "method": method, "params": params or {}}))
            return await asyncio.wait_for(fut, timeout or METHODS[method])
        except asyncio.TimeoutError:
            raise BridgeError("bridge_timeout", "the bridge didn't answer in time", 504) from None
        except BridgeError:
            raise
        except Exception as e:  # noqa: BLE001 - socket broke while sending
            raise BridgeError("bridge_offline", f"the bridge connection broke ({e.__class__.__name__})", 503) from e
        finally:
            conn.pending.pop(rid, None)

    async def disconnect(self, bridge_id: str, reason: str = "removed from the account") -> None:
        conn = self.conns.pop(bridge_id, None)
        if conn is not None:
            self._fail_pending(conn, BridgeError("bridge_offline", "the bridge was removed", 503))
            try:
                await conn.ws.close(4001, reason)
            except Exception:  # noqa: BLE001
                pass


def _printers(value: Any) -> list[dict[str, Any]]:
    """Printer list as the bridge reports it - only plain fields, never addresses or secrets."""
    out = []
    for p in value if isinstance(value, list) else []:
        if isinstance(p, dict) and isinstance(p.get("id"), str):
            out.append({k: p[k] for k in ("id", "name", "type", "machine", "capabilities") if k in p})
    return out[:50]


def _status(code: str) -> int:
    return {"offline": 503, "unknown_printer": 404, "unknown_method": 501, "busy": 409, "invalid": 400,
            "confirm_required": 409, "unauthorized": 403}.get(code, 502)
