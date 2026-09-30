"""HTTP API + the PrintShare web app (PWA) on port 8484.

App flow (all /api endpoints need `Authorization: Bearer <api_token>` or `?token=`):
  GET  /api/info            server name/version (the app uses it to test the connection)
  GET  /api/pairing?url=&remote=   pairing link + QR code (SVG) for the app, shown in the web UI (#10)
  GET  /api/printers
  GET  /api/printers/{id}/options[?process=...]   presets and defaults for the pickers
  POST /api/uploads?name=part.stl   raw file body -> {"link": "upload:<id>", ...}
  GET  /api/files?link=...  (link: http(s) URL or "upload:<id>")
  GET  /api/inspect?link=...&file=...   colours/filaments of a model (downloads it, cached for a day)
  GET  /api/model-file?link=...&file=... the model file itself, for the 3D view in the app (same cache)
  GET  /api/sources         model sources for search (Thingiverse only with a token)
  GET  /api/profiles        uploaded OrcaSlicer presets;  POST /api/profiles?filename=x.json (raw body)
  DELETE /api/profiles/{file}
  GET|PUT /api/printers/{id}/profile   {"machine_file": "<uploaded file>" | null}
  GET  /api/search?q=...&source=printables|thingiverse&page=1&sort=relevant|popular|makes
  GET  /api/models/{source}/{id}   details: images, description, license, author's settings, files
  POST /api/jobs            {"link", "printer", "file", "options": {...}}  -> download + slice only
  GET  /api/jobs            recent jobs, newest first
  GET  /api/jobs/{id}
  POST /api/jobs/{id}/send  {"start": true, "confirm": true}  -> upload (and start) after review
  DELETE /api/jobs/{id}
  GET  /api/printers/{id}/status   (+ "kind": idle|active|paused|done|stopped|error|unknown)
  GET  /api/printers/{id}/controls   heaters/fans/lights/speed the printer has (issue #5)
  POST /api/printers/{id}/adjust     {"kind": "heater"|"fan"|"light"|"speed", "id", "value", "confirm"}
  GET  /api/printers/{id}/temperatures   history {heater: [[seconds before now, actual, target], …]}
  GET  /api/printers/{id}/camera   {"available", "stream", …};  …/camera/snapshot?w=640 (JPEG);  …/camera/stream (MJPEG)
  POST /api/printers/{id}/control  {"action": "pause"|"resume"|"cancel", "confirm": true}
One-shot (CLI / iOS Shortcut):
  POST /api/print   {"link": "...", "printer": "cc-thomas", "file": 1, "start": true}
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import shutil
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import BRIM_TYPES, SUPPORT_TYPES, JobOptions, PrinterConfig, load_settings
from . import camera as cam
from . import gcode_preview
from .fetch import SLICEABLE, FetchError, Fetcher
from .pipeline import JobResult, fetch_model, inspect_model, prepare_job, run_job, send_job
from .printers import CONTROL_ACTIONS, LEVELING_TYPES, get_adapter
from . import lanes as lane_map
from . import user_profiles
from .profiles import ProfileError, ProfileLibrary, load_user_preset
from .search import Search

WEB = Path(__file__).parent / "web"
PLATES = ["Textured PEI Plate", "High Temp Plate", "Cool Plate", "Engineering Plate", "Supertack Plate"]
MAX_JOBS = 50
MAX_UPLOAD = 300 * 1024 * 1024
UPLOAD_PREFIX = "upload:"

settings = load_settings()
app = FastAPI(title="PrintShare", version="0.10.3")
app.add_middleware(GZipMiddleware, minimum_size=2000)  # layer previews are large but compress well
app.mount("/static", StaticFiles(directory=WEB), name="static")
JOBS: dict[str, dict[str, Any]] = {}
# temperature history for printers that don't keep one (Centauri): filled from status queries
TEMP_LOG: dict[str, deque] = {}
TEMP_LOG_SECONDS = 30 * 60
_SEARCH: Search | None = None
_TASKS: set[asyncio.Task] = set()  # keep references so tasks are not garbage-collected


def auth(request: Request) -> None:
    if not settings.api_token:
        return  # no token configured (only acceptable on a trusted LAN)
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip() or request.query_params.get("token", "")
    if not secrets.compare_digest(token, settings.api_token):
        raise HTTPException(401, "invalid token")


def _printer(printer_id: str | None) -> PrinterConfig:
    try:
        return settings.printer(printer_id)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))


def _library() -> ProfileLibrary:
    return ProfileLibrary.cached(settings.orca_profiles_dir)


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _new_job(kind: str, state: str, request: dict[str, Any]) -> dict[str, Any]:
    # forget the oldest finished jobs (in memory only; G-code cleanup is BE-05)
    for old in sorted(JOBS.values(), key=lambda j: j["created"])[:max(0, len(JOBS) - MAX_JOBS + 1)]:
        if old["state"] not in ("slicing", "sending", "running"):
            JOBS.pop(old["id"], None)
    job = {"id": uuid.uuid4().hex[:10], "kind": kind, "state": state, "log": [], "result": None,
           "error": None, "created": time.time(), "request": request}
    JOBS[job["id"]] = job
    return job


@app.get("/api/info", dependencies=[Depends(auth)])
def info() -> dict[str, Any]:
    return {"name": "PrintShare", "version": app.version, "printers": len(settings.printers)}


@app.get("/api/pairing", dependencies=[Depends(auth)])
async def pairing(request: Request, url: str | None = None, remote: str | None = None) -> dict[str, Any]:
    """Pairing code for the app (issue #10), so nobody needs the command line or the container log.
    Addresses: query > PRINTSHARE_URL / HA server_url (remote: PRINTSHARE_REMOTE_URL / HA remote_url) >
    the address this page was opened with. Needs the token like every /api endpoint - the code contains it."""
    import segno

    from . import bootstrap
    from .cli import pairing_link
    configured = await asyncio.to_thread(bootstrap.server_url) if url is None else ""
    home = (url if url is not None else configured or str(request.base_url)).strip().rstrip("/")
    away = (remote if remote is not None else bootstrap.remote_url()).strip().rstrip("/")
    if not home:
        raise HTTPException(400, "url is required")
    hosts = {}
    for u, name in ((home, "url"), (away, "remote")):
        if not u:
            continue
        try:
            parts = urlsplit(u)
            parts.port                       # raises ValueError for a broken port
        except ValueError:
            parts = None
        if not parts or parts.scheme not in ("http", "https") or not parts.hostname or re.search(r"\s", u) \
                or parts.query or parts.fragment:
            raise HTTPException(400, f"{name} must look like http://192.168.1.10:8484 or https://name:port")
        hosts[name] = parts.hostname.lower()
    warnings = []
    host = hosts["url"]
    if host in ("localhost", "::1", "0.0.0.0") or host.startswith("127."):
        warnings.append("localhost")          # the phone can't reach the server's own loopback address
    if request.headers.get("x-ingress-path") or "/api/hassio_ingress/" in home:
        warnings.append("ingress")            # Home Assistant ingress: not reachable for the app
    link = pairing_link(home, settings.api_token, away)
    svg = segno.make(link, error="m").svg_inline(scale=5, border=2, light="#fff", omitsize=True)  # viewBox: scales in CSS
    return {"link": link, "svg": svg, "url": home, "remote_url": away, "token": settings.api_token,
            "configured": bool(configured), "warnings": warnings}


# ---------- printers ----------
def printer_kind(state: str | None) -> str:
    """Normalise Moonraker/SDCP states for the app (same buckets for every adapter)."""
    s = (state or "").lower()
    if not s:
        return "unknown"
    if s in ("paused", "unloading_paused", "attention"):  # attention: Prusa waits for the user
        return "paused"
    if s in ("idle", "standby", "ready"):
        return "idle"
    if s in ("completed", "complete"):
        return "done"
    if s in ("stopped", "cancelled"):
        return "stopped"
    if s in ("error", "offline"):
        return "error"
    return "active"


@app.get("/api/printers", dependencies=[Depends(auth)])
def printers() -> list[dict[str, Any]]:
    return [{"id": p.id, "name": p.name or p.id, "type": p.type, "machine": p.slicing.machine,
             # DO-01: the app shows the leveling switch only where it works per print
             "leveling": p.auto_leveling if p.type in LEVELING_TYPES else None}
            for p in settings.printers]


def _defaults(printer: PrinterConfig, process: str) -> dict[str, Any]:
    s = printer.slicing
    proc = _library().resolve("process", process, s.process_overrides if process == s.process else None)
    support = "off"
    if str(proc.get("enable_support", "0")) == "1":
        support = "tree" if str(proc.get("support_type", "")).startswith("tree") else "normal"
    brim = next((k for k, v in BRIM_TYPES.items() if v == proc.get("brim_type")), "auto")
    try:
        infill = int(str(proc.get("sparse_infill_density", "")).rstrip("%"))
    except ValueError:
        infill = None
    try:
        walls = int(proc.get("wall_loops"))
    except (TypeError, ValueError):
        walls = None
    return {"filament": s.filament, "process": process, "bed_type": s.bed_type,
            "supports": support, "brim": brim, "infill": infill, "walls": walls,
            "layer_height": proc.get("layer_height")}


@app.get("/api/printers/{printer_id}/options", dependencies=[Depends(auth)])
async def options(printer_id: str, process: str | None = None) -> dict[str, Any]:
    printer = _printer(printer_id)
    lib = await asyncio.to_thread(_library)
    machine = printer.slicing.machine
    materials, processes = await asyncio.gather(
        asyncio.to_thread(lib.compatible, "filament", machine),
        asyncio.to_thread(lib.compatible, "process", machine))
    # configured presets are always offered, even if Orca doesn't list them as compatible
    for name, names in ((printer.slicing.filament, materials), (printer.slicing.process, processes)):
        if name not in names:
            names.insert(0, name)
    try:
        defaults = await asyncio.to_thread(_defaults, printer, process or printer.slicing.process)
    except ProfileError as e:
        raise HTTPException(400, str(e))
    return {"printer": printer.id, "materials": materials, "processes": processes,
            "plates": PLATES, "supports": ["off", *SUPPORT_TYPES], "brims": list(BRIM_TYPES),
            "defaults": defaults}


@app.get("/api/printers/{printer_id}/status", dependencies=[Depends(auth)])
async def status(printer_id: str) -> dict[str, Any]:
    printer = _printer(printer_id)
    try:
        st = await get_adapter(printer).status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"printer not reachable: {e}")
    _log_temperatures(printer_id, st)
    return {**st, "kind": printer_kind(st.get("state"))}


def _log_temperatures(printer_id: str, st: dict[str, Any]) -> None:
    heaters = st.get("heaters") or {}
    if not heaters:
        return
    log = TEMP_LOG.setdefault(printer_id, deque(maxlen=TEMP_LOG_SECONDS // 4))
    now = time.time()
    if log and now - log[-1][0] < 4:
        return
    log.append((now, {h: (v.get("actual"), v.get("target")) for h, v in heaters.items() if v.get("actual") is not None}))


# ---------- printer control (issue #5) ----------
@app.get("/api/printers/{printer_id}/controls", dependencies=[Depends(auth)])
async def printer_controls(printer_id: str) -> dict[str, Any]:
    adapter = get_adapter(_printer(printer_id))
    if not hasattr(adapter, "controls"):
        return {"heaters": [], "fans": [], "lights": [], "speed": None, "history": False}
    try:
        return await adapter.controls()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"printer not reachable: {e}")


class Adjustment(BaseModel):
    kind: str                     # heater | fan | light | speed
    id: str = ""
    value: float | bool
    confirm: bool = False


@app.post("/api/printers/{printer_id}/adjust", dependencies=[Depends(auth)])
async def adjust(printer_id: str, req: Adjustment) -> dict[str, Any]:
    adapter = get_adapter(_printer(printer_id))
    caps = await printer_controls(printer_id)
    value = req.value
    if req.kind == "heater":
        heater = next((h for h in caps.get("heaters") or [] if h["id"] == req.id), None)
        if heater is None:
            raise HTTPException(400, f"no heater {req.id!r} on this printer")
        if not 0 <= float(value) <= float(heater["max"]):
            raise HTTPException(400, f"{req.id} target must be 0-{heater['max']:g} °C")
    elif req.kind == "fan":
        if not any(f["id"] == req.id for f in caps.get("fans") or []):
            raise HTTPException(400, f"no fan {req.id!r} on this printer")
        if not 0 <= float(value) <= 100:
            raise HTTPException(400, "fan speed must be 0-100 %")
    elif req.kind == "light":
        if not any(li["id"] == req.id for li in caps.get("lights") or []):
            raise HTTPException(400, f"no light {req.id!r} on this printer")
        value = bool(value)
    elif req.kind == "speed":
        sp = caps.get("speed") or {}
        v = int(value)
        if not sp or (sp.get("modes") and v not in sp["modes"]) or \
                (not sp.get("modes") and not sp.get("min", 10) <= v <= sp.get("max", 300)):
            raise HTTPException(400, "speed not supported by this printer")
    else:
        raise HTTPException(400, "kind must be heater, fan, light or speed")
    # NF-05 / issue #5: nothing that could spoil a running print without an explicit confirmation
    risky = req.kind == "heater" or (req.kind == "fan" and float(value) == 0)
    if risky and not req.confirm:
        try:
            state = (await adapter.status()).get("state")
        except Exception:  # noqa: BLE001
            state = None
        if printer_kind(state) in ("active", "paused"):
            raise HTTPException(409, "a print is running - confirm this change (confirm=true)")
    try:
        await adapter.adjust(req.kind, req.id, value)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"printer not reachable: {e}")
    return {"ok": True}


@app.get("/api/printers/{printer_id}/temperatures", dependencies=[Depends(auth)])
async def temperatures(printer_id: str) -> dict[str, Any]:
    """Temperature history: from the printer where it keeps one (Moonraker, OctoPrint), else what
    PrintShare saw in the last 30 minutes of status queries."""
    adapter = get_adapter(_printer(printer_id))
    if hasattr(adapter, "temperature_history"):
        try:
            return {"series": await adapter.temperature_history(), "source": "printer"}
        except Exception:  # noqa: BLE001 - fall back to our own record
            pass
    now = time.time()
    series: dict[str, list] = {}
    for t, heaters in TEMP_LOG.get(printer_id, ()):
        for h, (actual, target) in heaters.items():
            series.setdefault(h, []).append([round(t - now), actual, target])
    return {"series": series, "source": "printshare"}


# ---------- camera (issue #3, DR-06): the app only talks to PrintShare, also away from home ----------
async def _camera(printer_id: str) -> cam.Camera:
    printer = _printer(printer_id)
    adapter = get_adapter(printer)
    try:
        source = await adapter.camera() if hasattr(adapter, "camera") else None
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"camera not reachable: {e}")
    if source is None:
        raise HTTPException(404, "this printer has no camera")
    return source


@app.get("/api/printers/{printer_id}/camera", dependencies=[Depends(auth)])
async def camera_info(printer_id: str) -> dict[str, Any]:
    try:
        return (await _camera(printer_id)).info()
    except HTTPException as e:
        if e.status_code == 404:
            return {"available": False, "stream": False, "snapshot": False, "name": None}
        raise


@app.get("/api/printers/{printer_id}/camera/snapshot", dependencies=[Depends(auth)])
async def camera_snapshot(printer_id: str, w: int | None = None) -> Response:
    """Current camera image; `w` scales it down (thumbnails, mobile data)."""
    source = await _camera(printer_id)
    try:
        jpeg = await cam.snapshot(source)
        if w:
            jpeg = await asyncio.to_thread(cam.scale, jpeg, max(160, min(w, 1920)))
    except cam.CameraError as e:
        raise HTTPException(502, str(e))
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/printers/{printer_id}/camera/stream", dependencies=[Depends(auth)])
async def camera_stream(printer_id: str) -> StreamingResponse:
    """Live MJPEG from the printer, passed through (ends when the app closes the view)."""
    source = await _camera(printer_id)
    try:
        content_type, chunks, close = await cam.open_stream(source)
    except cam.CameraError as e:
        raise HTTPException(502, str(e))

    async def body():
        try:
            async for chunk in chunks:
                yield chunk
        finally:
            await close()

    return StreamingResponse(body(), media_type=content_type, headers={"Cache-Control": "no-store"})


class ControlRequest(BaseModel):
    action: str
    confirm: bool = False


@app.post("/api/printers/{printer_id}/control", dependencies=[Depends(auth)])
async def control(printer_id: str, req: ControlRequest) -> dict[str, Any]:
    printer = _printer(printer_id)
    if req.action not in CONTROL_ACTIONS:
        raise HTTPException(400, f"action must be one of {', '.join(CONTROL_ACTIONS)}")
    if req.action == "cancel" and not req.confirm:
        raise HTTPException(400, "cancelling a print needs confirm=true")
    try:
        await get_adapter(printer).control(req.action)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{req.action} failed: {e}")
    return {"ok": True, "action": req.action}


# ---------- models ----------
def _uploads() -> Path:
    return Path(settings.work_dir) / "uploads"


def _resolve_link(link: str) -> str:
    """Only http(s) links and files uploaded through /api/uploads; never arbitrary server paths."""
    if link.startswith(UPLOAD_PREFIX):
        uid = link[len(UPLOAD_PREFIX):]
        d = _uploads() / uid
        found = [f for f in d.iterdir() if f.is_file()] if re.fullmatch(r"[0-9a-f]{12}", uid) and d.is_dir() else []
        if not found:
            raise HTTPException(404, "uploaded file not found - please choose it again")
        return str(found[0])
    if not link.startswith(("http://", "https://")):
        raise HTTPException(400, "link must be an http(s) URL")
    return link


@app.post("/api/uploads", dependencies=[Depends(auth)])
async def upload(request: Request, name: str) -> dict[str, Any]:
    """Model file from the phone (Files app, share menu); body = raw file content."""
    safe = re.sub(r"[^\w.\- ]+", "_", Path(name).name).strip()
    if not safe.lower().endswith(SLICEABLE):
        raise HTTPException(400, f"unsupported file type - use {', '.join(SLICEABLE)}")
    uid = uuid.uuid4().hex[:12]
    d = _uploads() / uid
    d.mkdir(parents=True)
    size = 0
    try:
        with open(d / safe, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, f"file too large (max {MAX_UPLOAD // 1048576} MB)")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "empty file")
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return {"id": uid, "link": UPLOAD_PREFIX + uid, "name": safe, "size": size}


@app.get("/api/files", dependencies=[Depends(auth)])
async def files(link: str) -> list[dict[str, Any]]:
    local = _resolve_link(link)
    try:
        listed = await asyncio.to_thread(Fetcher(settings.thingiverse_token).list_files, local)
        fl = [f for f in listed if f.sliceable]
    except FetchError as e:
        raise HTTPException(400, str(e))
    return [{"index": i, "name": f.name, "size": f.size} for i, f in enumerate(fl, 1)]


@app.get("/api/inspect", dependencies=[Depends(auth)])
async def inspect(link: str, file: str | None = None) -> dict[str, Any]:
    """Filaments (colours) of a model, so the app can offer a material per colour (MA-04)."""
    local = _resolve_link(link)
    try:
        return await asyncio.to_thread(inspect_model, settings, local, file)
    except FetchError as e:
        raise HTTPException(400, str(e))


# ---------- own OrcaSlicer presets (issue #2) ----------
def _reload_settings() -> None:
    """Printer settings changed from the app: take effect without restarting the container."""
    global settings
    settings = load_settings()


def _profile_error(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


@app.get("/api/profiles", dependencies=[Depends(auth)])
async def profiles_list() -> list[dict[str, Any]]:
    lib = await asyncio.to_thread(_library)
    return await asyncio.to_thread(user_profiles.list_profiles, settings.config_dir, lib)


@app.post("/api/profiles", dependencies=[Depends(auth)])
async def profiles_upload(request: Request, filename: str = "profile.json") -> list[dict[str, Any]]:
    """A preset exported from OrcaSlicer (JSON) or a preset bundle (zip); raw body."""
    content = await request.body()
    lib = await asyncio.to_thread(_library)
    try:
        return await asyncio.to_thread(user_profiles.store, settings.config_dir, filename, content, lib)
    except user_profiles.ProfileUploadError as e:
        raise _profile_error(e)


@app.delete("/api/profiles/{file}", dependencies=[Depends(auth)])
def profiles_delete(file: str) -> dict[str, Any]:
    try:
        user_profiles.delete(settings.config_dir, file, [p.id for p in settings.printers])
    except user_profiles.ProfileUploadError as e:
        raise _profile_error(e)
    return {"deleted": file}


@app.get("/api/printers/{printer_id}/profile", dependencies=[Depends(auth)])
def printer_profile(printer_id: str) -> dict[str, Any]:
    """Printer preset in use: an uploaded one (`machine_file`), one set by hand in config.yaml
    (`config_file`), or the OrcaSlicer system preset `machine` (+ built-in `machine_preset`)."""
    s = _printer(printer_id).slicing
    uploaded = (user_profiles.read_overlay(settings.config_dir, printer_id).get("slicing") or {}).get("machine_file")
    return {"machine": s.machine, "machine_file": uploaded,
            "config_file": None if uploaded or not s.machine_file else Path(s.machine_file).name,
            "machine_preset": s.machine_preset}


class ProfileAssignment(BaseModel):
    machine_file: str | None = None


@app.put("/api/printers/{printer_id}/profile", dependencies=[Depends(auth)])
async def set_printer_profile(printer_id: str, req: ProfileAssignment) -> dict[str, Any]:
    _printer(printer_id)
    lib = await asyncio.to_thread(_library)
    try:
        await asyncio.to_thread(user_profiles.assign_machine, settings.config_dir, printer_id, req.machine_file, lib)
    except user_profiles.ProfileUploadError as e:
        raise _profile_error(e)
    _reload_settings()
    return printer_profile(printer_id)


@app.get("/api/model-file", dependencies=[Depends(auth)])
async def model_file(link: str, file: str | None = None) -> FileResponse:
    """One file of a model (index as in /api/files), so the app can show it in 3D before slicing (MQ-06).
    Served from the download cache that inspect and slicing use; never re-hosted anywhere else."""
    local = _resolve_link(link)
    try:
        chosen, path = await asyncio.to_thread(fetch_model, settings, local, file)
    except FetchError as e:
        raise HTTPException(400, str(e))
    if path.stat().st_size > MAX_UPLOAD:
        raise HTTPException(413, "model file too large for the 3D view")
    return FileResponse(path, media_type="application/octet-stream", filename=Path(chosen.name).name)


# ---------- search (MQ-05/06) ----------
def _search() -> Search:
    global _SEARCH
    if _SEARCH is None:
        _SEARCH = Search(settings.thingiverse_token)
    return _SEARCH


def _search_error(e: FetchError) -> HTTPException:
    msg = str(e)
    return HTTPException(404 if "not found" in msg else 502 if "API error" in msg else 400, msg)


@app.get("/api/sources", dependencies=[Depends(auth)])
def sources() -> list[dict[str, Any]]:
    return _search().list_sources()


@app.get("/api/search", dependencies=[Depends(auth)])
async def search(q: str, source: str = "printables", page: int = 1, sort: str = "relevant") -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_search().search, source, q, page, sort)
    except FetchError as e:
        raise _search_error(e)


@app.get("/api/models/{source}/{model_id}", dependencies=[Depends(auth)])
async def model_detail(source: str, model_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_search().detail, source, model_id)
    except FetchError as e:
        raise _search_error(e)


# ---------- app flow: slice, review, send ----------
class OptionsModel(BaseModel):
    filament: str | None = None
    process: str | None = None
    bed_type: str | None = None
    supports: str | None = None
    brim: str | None = None
    infill: int | None = None
    walls: int | None = None
    filaments: list[str | None] | None = None   # multicolour: preset per filament of the model


class JobRequest(BaseModel):
    link: str
    printer: str | None = None
    file: str | None = None
    options: OptionsModel = Field(default_factory=OptionsModel)


def _validate_options(printer: PrinterConfig, o: OptionsModel) -> JobOptions:
    opts = JobOptions(**o.model_dump())
    try:
        opts.process_overrides()
    except ValueError as e:
        raise HTTPException(400, str(e))
    if opts.bed_type and opts.bed_type not in PLATES:
        raise HTTPException(400, f"unknown plate {opts.bed_type!r}")
    s = printer.slicing
    for f in [opts.filament, *(opts.filaments or [])]:
        if f and f != s.filament and f not in _library().compatible("filament", s.machine):
            raise HTTPException(400, f"material {f!r} does not fit {printer.name or printer.id}")
    if opts.filaments and len(opts.filaments) > 16:
        raise HTTPException(400, "at most 16 filaments")
    if opts.process and opts.process != s.process and \
            opts.process not in _library().compatible("process", s.machine):
        raise HTTPException(400, f"quality {opts.process!r} does not fit {printer.name or printer.id}")
    return opts


@app.post("/api/jobs", dependencies=[Depends(auth)])
async def create_job(req: JobRequest) -> dict[str, Any]:
    source = _resolve_link(req.link)
    printer = _printer(req.printer)
    opts = await asyncio.to_thread(_validate_options, printer, req.options)
    job = _new_job("prepare", "slicing", req.model_dump())
    job["printer"] = printer.id

    async def worker() -> None:
        try:
            res = await prepare_job(settings, source, printer.id, req.file, opts, out_name=job["id"],
                                    progress=lambda m: job["log"].append(m))
            job.update(state="sliced", result=res.as_dict())
        except Exception as e:  # noqa: BLE001 - report every failure to the phone
            job.update(state="error", error=str(e))

    _spawn(worker())
    return {"job": job["id"]}


@app.get("/api/jobs", dependencies=[Depends(auth)])
def list_jobs() -> list[dict[str, Any]]:
    jobs = sorted(JOBS.values(), key=lambda j: j["created"], reverse=True)
    return [{k: j.get(k) for k in ("id", "kind", "state", "error", "created", "printer")}
            | {"link": j["request"].get("link"),
               "file": (j["result"] or {}).get("source_file"),
               "print_time": (j["result"] or {}).get("print_time"),
               "filament_g": (j["result"] or {}).get("filament_g")}
            for j in jobs]


@app.get("/api/jobs/{job_id}", dependencies=[Depends(auth)])
def job(job_id: str) -> dict[str, Any]:
    if job_id not in JOBS:
        raise HTTPException(404, "unknown job")
    return JOBS[job_id]


class SendRequest(BaseModel):
    start: bool = True
    confirm: bool = False
    leveling: bool | None = None  # bed leveling before the print; None = printer default
    # lane selection (issue #6): {"<model filament, 1-based>": <printer tool of the lane>}
    lanes: dict[str, int] | None = None


@app.post("/api/jobs/{job_id}/send", dependencies=[Depends(auth)])
async def send(job_id: str, req: SendRequest) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    if req.start and not req.confirm:
        raise HTTPException(400, "starting a print needs confirm=true")  # NF-05
    if job["state"] not in ("sliced", "uploaded"):
        raise HTTPException(409, f"job is {job['state']}, not ready to send")
    result = JobResult(**job["result"])
    try:
        tools = lane_map.parse_mapping(req.lanes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if tools:
        # the chosen lanes must exist and hold filament (DR-03)
        try:
            lanes = (await get_adapter(_printer(result.printer)).status()).get("lanes") or []
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"printer not reachable: {e}")
        by_tool = {ln.get("tool"): ln for ln in lanes}
        for idx, tool in sorted(tools.items()):
            ln = by_tool.get(tool)
            if ln is None:
                raise HTTPException(400, f"the printer has no lane for T{tool}")
            if req.start and not ln.get("loaded"):
                raise HTTPException(409, f"lane {ln.get('id')} (T{tool}) is empty - load filament or choose another lane")
    if req.start:
        # DR-03: never start on a printer that is still busy (an unreachable printer fails in send_job)
        try:
            state = (await get_adapter(_printer(result.printer)).status()).get("state")
        except Exception:  # noqa: BLE001
            state = None
        if printer_kind(state) in ("active", "paused"):
            raise HTTPException(409, "printer is busy - wait until the current print has finished")
    job.update(state="sending", error=None)

    async def worker() -> None:
        try:
            await send_job(settings, result, req.start, progress=lambda m: job["log"].append(m),
                           leveling=req.leveling, tools=tools)
            job["leveling"] = req.leveling
            job.update(state="started" if req.start else "uploaded", result=result.as_dict())
        except Exception as e:  # noqa: BLE001
            # the sliced G-code is still valid: allow another attempt
            job.update(state="sliced", error=f"Sending failed: {e}")

    _spawn(worker())
    return {"job": job_id}


def _job_gcode(job_id: str) -> tuple[dict[str, Any], Path]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    gcode = Path((job.get("result") or {}).get("gcode") or "")
    if not gcode.name or not gcode.is_file():
        raise HTTPException(404, "no G-code for this job (yet)")
    return job, gcode


def _bed(printer_id: str) -> tuple[float, float] | None:
    try:
        s = settings.printer(printer_id).slicing
        area = (load_user_preset(Path(s.machine_file), None, _library(), "machine") if s.machine_file
                else _library().resolve("machine", s.machine)).get("printable_area")
        return gcode_preview.bed_size(area)
    except Exception:  # noqa: BLE001 - the preview works without the bed outline
        return None


@app.get("/api/jobs/{job_id}/preview", dependencies=[Depends(auth)])
async def preview(job_id: str, format: int = 1) -> dict[str, Any]:
    """Layer data for the G-code viewer (SL-06/07). Apps ask for the format they understand
    (?format=2 adds the filament per line); without it, app builds from before 0.6.0 keep working."""
    job, gcode = _job_gcode(job_id)
    bed = await asyncio.to_thread(_bed, job["result"]["printer"])
    data = await asyncio.to_thread(gcode_preview.build, gcode, bed)
    return gcode_preview.as_version(data, format)


@app.get("/api/jobs/{job_id}/gcode", dependencies=[Depends(auth)])
def download_gcode(job_id: str) -> FileResponse:
    """The sliced G-code itself (SL-10)."""
    job, gcode = _job_gcode(job_id)
    name = Path((job.get("result") or {}).get("source_file") or gcode.stem).stem + ".gcode"
    return FileResponse(gcode, media_type="text/x.gcode", filename=name)


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(auth)])
def delete_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    if job["state"] in ("slicing", "sending", "running"):
        raise HTTPException(409, "job is still running")
    JOBS.pop(job_id)
    if job.get("kind") == "prepare" and job.get("printer"):
        shutil.rmtree(Path(settings.gcode_dir) / job["printer"] / job_id, ignore_errors=True)
    return {"deleted": job_id}


# ---------- one-shot (kept for the CLI docs and iOS Shortcuts) ----------
class PrintRequest(BaseModel):
    link: str
    printer: str | None = None
    file: str | None = None
    start: bool = True


@app.post("/api/print", dependencies=[Depends(auth)])
async def print_(req: PrintRequest) -> dict[str, Any]:
    source = _resolve_link(req.link)
    job = _new_job("oneshot", "running", req.model_dump())

    async def worker() -> None:
        try:
            res = await run_job(settings, source, req.printer, req.file, send=True, start=req.start,
                                progress=lambda m: job["log"].append(m))
            job.update(state="done", result=res.as_dict())
        except Exception as e:  # noqa: BLE001 - report every failure to the phone
            job.update(state="error", error=str(e))

    _spawn(worker())
    return {"job": job["id"]}


# ---------- web app ----------
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((WEB / "index.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(WEB / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    # served from the root so its scope covers the whole app
    return FileResponse(WEB / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})
