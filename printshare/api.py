"""HTTP API + the PrintShare web app (PWA) on port 8484.

App flow (all /api endpoints need `Authorization: Bearer <api_token>` or `?token=`):
  GET  /api/info            server name/version (the app uses it to test the connection)
  GET  /api/printers
  GET  /api/printers/{id}/options[?process=...]   presets and defaults for the pickers
  POST /api/uploads?name=part.stl   raw file body -> {"link": "upload:<id>", ...}
  GET  /api/files?link=...  (link: http(s) URL or "upload:<id>")
  GET  /api/inspect?link=...&file=...   colours/filaments of a model (downloads it, cached for a day)
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
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import BRIM_TYPES, SUPPORT_TYPES, JobOptions, PrinterConfig, load_settings
from . import gcode_preview
from .fetch import SLICEABLE, FetchError, Fetcher
from .pipeline import JobResult, inspect_model, prepare_job, run_job, send_job
from .printers import CONTROL_ACTIONS, LEVELING_TYPES, get_adapter
from . import user_profiles
from .profiles import ProfileError, ProfileLibrary, load_user_preset
from .search import Search

WEB = Path(__file__).parent / "web"
PLATES = ["Textured PEI Plate", "High Temp Plate", "Cool Plate", "Engineering Plate", "Supertack Plate"]
MAX_JOBS = 50
MAX_UPLOAD = 300 * 1024 * 1024
UPLOAD_PREFIX = "upload:"

settings = load_settings()
app = FastAPI(title="PrintShare", version="0.7.0")
app.add_middleware(GZipMiddleware, minimum_size=2000)  # layer previews are large but compress well
app.mount("/static", StaticFiles(directory=WEB), name="static")
JOBS: dict[str, dict[str, Any]] = {}
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
    return {**st, "kind": printer_kind(st.get("state"))}


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
                           leveling=req.leveling)
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
