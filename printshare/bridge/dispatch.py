"""The bridge's methods (docs/BRIDGE.md section 6) on top of this server's own API functions.

Every method calls the same function as the local app/web page would (status, control, adjust, camera, power, send …),
so the checks are the same: confirm for starting/cancelling/heating, busy printer, empty lane, spool rules. Only the
methods listed in METHODS exist; anything else is refused.
"""
from __future__ import annotations

import asyncio
import base64
import re
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import registry
from .client import BridgeClient, MethodError, ensure_identity
from .seal import SealError, unseal

JOB_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SNAPSHOT_MAX = 400 * 1024


def _api():
    from .. import api              # imported late: api imports this module
    return api


def _code(status: int) -> str:
    return {400: "invalid", 404: "unknown_printer", 409: "busy", 501: "unknown_method"}.get(status, "offline"
                                                                                               if status >= 500 else "invalid")


async def _call(fn, *args, **kwargs) -> Any:
    try:
        res = fn(*args, **kwargs)
        return await res if asyncio.iscoroutine(res) else res
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else str(e.detail)
        code = "confirm_required" if "confirm" in detail else _code(e.status_code)
        raise MethodError(code, detail) from None


def _local():
    api = _api()
    return api.Account("local", api.settings)


def _printer_id(params: dict[str, Any]) -> str:
    pid = params.get("printer")
    if not isinstance(pid, str) or not pid:
        raise MethodError("invalid", "printer is missing")
    return pid


def printers_list() -> list[dict[str, Any]]:
    api = _api()
    acct = _local()
    added = {p["id"] for p in registry.load(api.settings.config_dir)}
    out = []
    for p in api.settings.printers:
        j = api._printer_json(acct, p.id)
        out.append({"id": p.id, "name": j["name"], "type": p.type, "machine": j["machine"],
                    "capabilities": {"leveling": j["leveling"], "power": j["power"], "cosmos": j["cosmos"],
                                     "removable": p.id in added}})
    return out


async def _send(client: BridgeClient, params: dict[str, Any]) -> dict[str, Any]:
    api = _api()
    acct = _local()
    pid = _printer_id(params)
    job = str(params.get("job") or "")
    if not JOB_RE.match(job):
        raise MethodError("invalid", "job is missing")
    await _call(api._printer, acct, pid)                       # unknown printer → error before downloading
    local = api._new_job("prepare", "sliced", {"source": "bridge", "cloud_job": job, "printer": pid})
    local["printer"] = pid
    try:
        path = await client.download_gcode(job, Path(api.settings.gcode_dir) / pid / local["id"])
    except Exception:
        api.JOBS.pop(local["id"], None)
        raise
    local["result"] = api.JobResult(pid, path.name, str(path), None, None, None).as_dict()
    req = api.SendRequest(start=bool(params.get("start")), confirm=bool(params.get("confirm")),
                          leveling=params.get("leveling"), lanes=params.get("lanes") or None,
                          spool_id=params.get("spool_id"), timelapse=bool(params.get("timelapse")))
    try:
        await _call(api.send, local["id"], req, acct)
    except MethodError:
        api.JOBS.pop(local["id"], None)
        raise
    sent = 0
    while local["state"] == "sending":                           # the cloud waits (job.send timeout 15 min)
        await asyncio.sleep(0.3)
        for line in local["log"][sent:]:
            await client.event("job.progress", {"printer": pid, "job": job, "message": str(line)[:200]})
        sent = len(local["log"])
    if local.get("error"):
        raise MethodError("send_failed", str(local["error"]))
    return {"state": local["state"], "file": path.name, "local_job": local["id"]}


async def _snapshot(pid: str, params: dict[str, Any]) -> dict[str, Any]:
    api = _api()
    w = params.get("w")
    w = max(160, min(int(w), 1280)) if isinstance(w, (int, float)) else 960
    resp = await _call(api.camera_snapshot, pid, w, _local())
    data = bytes(resp.body)
    if len(data) > SNAPSHOT_MAX:
        resp = await _call(api.camera_snapshot, pid, 640, _local())
        data = bytes(resp.body)
    return {"jpeg": base64.b64encode(data).decode(), "type": "image/jpeg", "at": time.time()}


async def _add_or_update(client: BridgeClient, params: dict[str, Any], pid: str | None) -> dict[str, Any]:
    api = _api()
    cfg_dir = api.settings.config_dir
    fields = params.get("printer") if isinstance(params.get("printer"), dict) else {}
    secrets: dict[str, Any] = {}
    if params.get("sealed"):
        try:
            secrets = unseal(ensure_identity(api.settings)["private_key"], str(params["sealed"]))
        except SealError as e:
            raise MethodError("invalid", str(e)) from None
    added = registry.load(cfg_dir)
    if pid is None:
        if len(added) >= registry.MAX_ADDED:
            raise MethodError("invalid", f"at most {registry.MAX_ADDED} printers can be added this way")
        taken = {p.id for p in api.settings.printers} | {p["id"] for p in added}
        new_id = registry.slug(str(fields.get("name") or fields.get("type") or "printer"), taken)
        old = None
    else:
        old = next((p for p in added if p["id"] == pid), None)
        if old is None:
            known = any(p.id == pid for p in api.settings.printers)
            raise MethodError("invalid" if known else "unknown_printer",
                              "this printer is set up on the server itself - change it there" if known else "unknown printer")
        new_id = pid
    try:
        cfg = registry.build(fields, secrets, new_id, old)
        from ..config import printer_from_config
        printer_from_config(cfg, Path(cfg_dir or "."), api.settings.orca_profiles_dir)   # must load (machine preset …)
    except (ValueError, TypeError) as e:
        raise MethodError("invalid", str(e)) from None
    added = [p for p in added if p["id"] != new_id] + [cfg]
    registry.save(cfg_dir, added)
    api._reload_settings()
    printers = printers_list()
    await client.event("printers.changed", {"printers": printers})
    return next(p for p in printers if p["id"] == new_id)


async def _remove(client: BridgeClient, pid: str) -> dict[str, Any]:
    api = _api()
    added = registry.load(api.settings.config_dir)
    if not any(p["id"] == pid for p in added):
        raise MethodError("invalid", "this printer is set up on the server at home itself - remove it there")
    registry.save(api.settings.config_dir, [p for p in added if p["id"] != pid])
    api._reload_settings()
    await client.event("printers.changed", {"printers": printers_list()})
    return {"removed": pid}


async def dispatch(method: str, params: dict[str, Any], client: BridgeClient) -> Any:
    api = _api()
    if method == "printers.list":
        return printers_list()
    if method == "discover":
        from . import discovery
        try:
            # a bridge in Docker's bridge network only sees its own network: then the phone's Wi-Fi (sent along by the
            # app at home) tells where to look
            found = await discovery.discover(getattr(api.settings, "lan_subnet", "") or discovery.subnet_hint(params.get("subnet")))
        except ValueError as e:
            raise MethodError("invalid", str(e)) from None
        known = {(p.host or (p.url or "").removeprefix("http://").removeprefix("https://").rstrip("/")) for p in api.settings.printers}
        return [{**f, "added": f["address"] in known or f["address"].split(":")[0] in known} for f in found]
    if method == "printer.add":
        return await _add_or_update(client, params, None)
    if method == "job.send":
        return await _send(client, params)
    pid = _printer_id(params)
    acct = _local()
    if method == "printer.status":
        return await _call(api.status, pid, acct)
    if method == "printer.control":
        return await _call(api.control, pid, api.ControlRequest(action=str(params.get("action") or ""),
                                                               confirm=bool(params.get("confirm"))), acct)
    if method == "printer.controls":
        return await _call(api.printer_controls, pid, acct)
    if method == "printer.adjust":
        try:
            req = api.Adjustment(kind=params.get("kind"), id=params.get("id") or "", value=params.get("value"),
                                 confirm=bool(params.get("confirm")))
        except Exception as e:  # noqa: BLE001 - pydantic validation
            raise MethodError("invalid", str(e)[:300]) from None
        return await _call(api.adjust, pid, req, acct)
    if method == "printer.temperatures":
        return await _call(api.temperatures, pid, acct)
    if method == "printer.filament.info":
        return await _call(api.filament_info, pid, acct)
    if method == "printer.filament":
        try:
            req = api.FilamentRequest(**{k: params.get(k) for k in ("action", "slot", "material", "color", "temp")
                                         if params.get(k) is not None}, confirm=bool(params.get("confirm")))
        except Exception as e:  # noqa: BLE001 - pydantic validation
            raise MethodError("invalid", str(e)[:300]) from None
        return await _call(api.filament_action, pid, req, acct)
    if method == "printer.camera":
        return await _call(api.camera_info, pid, acct)
    if method == "printer.camera.snapshot":
        return await _snapshot(pid, params)
    if method == "printer.power":
        if "on" in params:
            return await _call(api.power_switch, pid, api.PowerSwitch(on=bool(params["on"])), acct)
        return await _call(api.power_state, pid, acct)
    if method == "watch.state":
        await _call(api._printer, acct, pid)
        return api.WATCHER.state(pid, api.fw.load_config(api.settings))
    if method == "watch.mute":
        return await _call(api.watch_mute, pid, acct)
    if method == "printer.update":
        return await _add_or_update(client, params, pid)
    if method == "printer.remove":
        return await _remove(client, pid)
    raise MethodError("unknown_method", f"unknown method {method}")
