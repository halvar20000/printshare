"""Printers added from the app through the bridge (docs/BRIDGE.md, `printer.add`).

Kept in <config dir>/printers-added.yaml (0600: it holds addresses and passwords) next to config.yaml, which the Unraid
template / Home Assistant add-on may regenerate on every start. `config.load_settings` adds them to the printers of
config.yaml (ids already used there win).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

FILE = "printers-added.yaml"
TYPES = ("elegoo_sdcp", "moonraker", "prusalink", "octoprint", "bambu_lan")
MAX_ADDED = 20


def path(config_dir: str | Path) -> Path:
    return Path(config_dir or ".") / FILE


def load(config_dir: str | Path) -> list[dict[str, Any]]:
    p = path(config_dir)
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return [x for x in data if isinstance(x, dict) and x.get("id")] if isinstance(data, list) else []


def save(config_dir: str | Path, printers: list[dict[str, Any]]) -> None:
    p = path(config_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(printers, sort_keys=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "printer").lower()).strip("-")[:24] or "printer"
    pid, n = base, 2
    while pid in taken:
        pid, n = f"{base}-{n}", n + 1
    return pid


def build(fields: dict[str, Any], secrets: dict[str, Any], pid: str, old: dict[str, Any] | None = None) -> dict[str, Any]:
    """A config.yaml-style printer entry from the app's (plain) fields and the (unsealed) address/secrets."""
    old = dict(old or {})
    ptype = str(fields.get("type") or old.get("type") or "")
    if ptype not in TYPES:
        raise ValueError(f"type must be one of {', '.join(TYPES)}")
    address = str(secrets.get("address") or "").strip()
    if not address and not old:
        raise ValueError("the printer's address is missing")
    cfg: dict[str, Any] = {"id": pid, "type": ptype, "name": str(fields.get("name") or old.get("name") or pid)[:60]}
    if address:
        host = re.sub(r"^https?://", "", address).split("/")[0]
        if not re.fullmatch(r"[A-Za-z0-9.\-]+(:\d{1,5})?", host):
            raise ValueError("the address must be a host name or IP address, optionally with :port")
        if ptype in ("elegoo_sdcp", "bambu_lan"):
            cfg["host"] = host.split(":")[0]
        else:
            cfg["url"] = f"http://{host}"
    else:
        for k in ("host", "url"):
            if old.get(k):
                cfg[k] = old[k]
    for key, src in (("password", "password"), ("api_key", "api_key")):
        value = secrets.get(src, old.get(key))
        if value:
            cfg[key] = str(value)
    # own camera (RTSP / HTTP) - sealed like a password (it often carries the camera's login); "" removes it
    camera = secrets.get("camera_url", old.get("camera_url"))
    if camera:
        from ..camera import check_url
        cfg["camera_url"] = check_url(str(camera))
    slicing = dict(old.get("slicing") or {})
    if fields.get("machine"):
        slicing["machine"] = str(fields["machine"])
    if "cosmos" in fields and ptype == "moonraker":
        if fields["cosmos"]:
            slicing["machine_preset"] = "cosmos"
        else:
            slicing.pop("machine_preset", None)
    if slicing:
        cfg["slicing"] = slicing
    return cfg
