"""Printers on the bridge's LAN (docs/BRIDGE.md section 9) - the rules of the app's `lib/lan/discover.ts`:
Centauri Carbon by SDCP UDP discovery, Klipper/Moonraker (COSMOS by its macros), PrusaLink and OctoPrint by a short
HTTP probe of the /24 around the bridge's address, Bambu Lab printers by their TLS certificate on port 8883 (issuer
"BBL CA", CN = serial; only in LAN-only mode) (or `lan_subnet`, e.g. when the container runs in a Docker bridge
network: broadcasts don't leave it, set PRINTSHARE_LAN_SUBNET=192.168.1.0/24 or use host networking)."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Any

import httpx

TIMEOUT_S = 1.5
WORKERS = 32


def own_address() -> str | None:
    """The address this machine uses towards the LAN (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def hosts(subnet: str | None = None) -> list[str]:
    if subnet:
        net = ipaddress.ip_network(subnet, strict=False)
    else:
        own = own_address()
        if not own:
            return []
        net = ipaddress.ip_network(f"{own}/24", strict=False)
    if net.prefixlen < 22:                      # never scan more than 1024 addresses
        raise ValueError("the LAN subnet is too large - use a /22 or smaller")
    own = own_address()
    return [str(h) for h in net.hosts() if str(h) != own]


async def _probe(c: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        return await c.get(url, headers={"Accept": "application/json, text/html"})
    except (httpx.HTTPError, OSError):
        return None


def _json(r: httpx.Response | None) -> Any:
    try:
        return r.json() if r is not None and r.status_code == 200 else None
    except ValueError:
        return None


def _is_moonraker(r: httpx.Response | None) -> bool:
    res = (_json(r) or {}).get("result") if isinstance(_json(r), dict) else None
    return isinstance(res, dict) and any(k in res for k in ("klippy_state", "moonraker_version", "klippy_connected"))


async def _port_open(host: str, port: int) -> bool:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), TIMEOUT_S)
    except (OSError, asyncio.TimeoutError):
        return False
    w.close()
    return True


async def bambu(host: str, port: int = 8883) -> dict[str, Any] | None:
    """A Bambu Lab printer in LAN-only mode? Its serial stays on the bridge - the app gets the model only."""
    if not await _port_open(host, port):
        return None
    from ..printers.bambu import machine_for, model_for, read_serial
    serial, is_bambu = await asyncio.to_thread(read_serial, host, 3.0)
    if not is_bambu:
        return None
    model = model_for(serial)
    return {"type": "bambu_lan", "address": host, "name": f"Bambu Lab {model}" if model else "Bambu Lab",
            "detail": None, "machine": machine_for(serial)}


async def identify(c: httpx.AsyncClient, host: str, web_port: int = 80, mr_port: int = 7125,
                   bambu_port: int = 8883) -> dict[str, Any] | None:
    hp = host if web_port == 80 else f"{host}:{web_port}"
    web = f"http://{hp}"
    on_web, on_mr, bbl = await asyncio.gather(_probe(c, f"{web}/server/info"), _probe(c, f"http://{host}:{mr_port}/server/info"),
                                              bambu(host, bambu_port))
    if bbl:
        return bbl
    base = web if _is_moonraker(on_web) else f"http://{host}:{mr_port}" if _is_moonraker(on_mr) else None
    if base:
        objs, info = await asyncio.gather(_probe(c, f"{base}/printer/objects/list"), _probe(c, f"{base}/printer/info"))
        objects = ((_json(objs) or {}).get("result") or {}).get("objects") or []
        cosmos = any(re.search("cosmos", str(o), re.I) for o in objects)
        hostname = str(((_json(info) or {}).get("result") or {}).get("hostname") or "")
        address = hp if base == web else (host if mr_port == 7125 else f"{host}:{mr_port}")
        return {"type": "moonraker", "address": address, "cosmos": cosmos,
                "name": "Centauri Carbon (COSMOS)" if cosmos else hostname or "Klipper",
                "detail": "OpenCentauri COSMOS" if cosmos else "Klipper" if hostname else None}
    if on_web is None:
        return None
    pl = await _probe(c, f"{web}/api/v1/info")
    if pl is not None and pl.status_code == 401 and re.search(r'realm="?Printer API', pl.headers.get("www-authenticate", ""), re.I):
        return {"type": "prusalink", "address": hp, "name": "Prusa", "detail": "PrusaLink"}
    page = await _probe(c, f"{web}/") if on_web.status_code in (401, 403, 404) else on_web
    if page is not None and re.search("octoprint", page.text[:65536], re.I):
        return {"type": "octoprint", "address": hp, "name": "OctoPrint", "detail": "OctoPrint"}
    return None


async def _sdcp(subnet: str | None) -> list[dict[str, Any]]:
    try:
        from pycentauri.discovery import discover
    except ImportError:
        return []
    targets = ["255.255.255.255"]
    if subnet:
        targets.append(str(ipaddress.ip_network(subnet, strict=False).broadcast_address))
    out = []
    for target in targets:
        try:
            for p in await discover(timeout=2.5, broadcast_address=target, retries=3):
                d = p.raw.get("Data") if isinstance(p.raw.get("Data"), dict) else {}
                address = d.get("MainboardIP") or p.host
                model = " ".join(x for x in (d.get("BrandName"), p.machine_name) if x)
                out.append({"type": "elegoo_sdcp", "address": address, "name": p.name or p.machine_name or "Centauri Carbon",
                            "detail": " · ".join(x for x in (model, p.firmware_version) if x) or None})
        except OSError:
            continue
    return out


async def discover(subnet: str | None = None, host_list: list[str] | None = None,
                   web_port: int = 80, mr_port: int = 7125, bambu_port: int = 8883) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    todo = host_list if host_list is not None else hosts(subnet)
    # the Centauri's UDP discovery runs while the addresses are probed (one after the other took > 30 s with a LAN set)
    sdcp = asyncio.ensure_future(_sdcp(subnet) if host_list is None else asyncio.sleep(0, result=[]))
    queue: asyncio.Queue[str] = asyncio.Queue()
    for h in todo:
        queue.put_nowait(h)
    limits = httpx.Limits(max_connections=WORKERS * 2, max_keepalive_connections=0)
    async with httpx.AsyncClient(timeout=TIMEOUT_S, limits=limits, follow_redirects=False) as c:
        async def worker() -> None:
            while not queue.empty():
                h = queue.get_nowait()
                p = await identify(c, h, web_port, mr_port, bambu_port)
                if p and h not in found:
                    found[h] = p
        await asyncio.gather(*(worker() for _ in range(WORKERS)))
    for p in await sdcp:                        # SDCP knows the Centauri better than the HTTP probe
        found[p["address"]] = p
    return list(found.values())


def subnet_hint(value: Any) -> str | None:
    """A home network the app suggests (its own Wi-Fi), e.g. "192.168.86.0/24": private IPv4, /22 or smaller."""
    try:
        net = ipaddress.ip_network(str(value), strict=False)
    except ValueError:
        return None
    return str(net) if net.version == 4 and net.is_private and 22 <= net.prefixlen <= 30 else None
