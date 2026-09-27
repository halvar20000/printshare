"""HTTP API + the PrintShare web app (PWA) on port 8484.

App flow (all /api endpoints need `Authorization: Bearer <api_token>` or `?token=`):
  GET  /api/info            server name/version (the app uses it to test the connection)
  GET  /api/printers
  GET  /api/printers/{id}/options[?process=...]   presets and defaults for the pickers
  POST /api/uploads?name=part.stl   raw file body -> {"link": "upload:<id>", ...}
  GET  /api/files?link=...  (link: http(s) URL or "upload:<id>")
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
import re
import secrets
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import BRIM_TYPES, SUPPORT_TYPES, JobOptions, PrinterConfig, load_settings
from .fetch import SLICEABLE, FetchError, Fetcher
from .pipeline import JobResult, prepare_job, run_job, send_job
from .printers import CONTROL_ACTIONS, get_adapter
from .profiles import ProfileError, ProfileLibrary

WEB = Path(__file__).parent / "web"
PLATES = ["Textured PEI Plate", "High Temp Plate", "Cool Plate", "Engineering Plate", "Supertack Plate"]
MAX_JOBS = 50
MAX_UPLOAD = 300 * 1024 * 1024
UPLOAD_PREFIX = "upload:"

settings = load_settings()
app = FastAPI(title="PrintShare", version="0.2")
app.mount("/static", StaticFiles(directory=WEB), name="static")
JOBS: dict[str, dict[str, Any]] = {}
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
    if s in ("paused", "unloading_paused"):
        return "paused"
    if s in ("idle", "standby", "ready"):
        return "idle"
    if s in ("completed", "complete"):
        return "done"
    if s in ("stopped", "cancelled"):
        return "stopped"
    if s == "error":
        return "error"
    return "active"


@app.get("/api/printers", dependencies=[Depends(auth)])
def printers() -> list[dict[str, Any]]:
    return [{"id": p.id, "name": p.name or p.id, "type": p.type, "machine": p.slicing.machine}
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


# ---------- app flow: slice, review, send ----------
class OptionsModel(BaseModel):
    filament: str | None = None
    process: str | None = None
    bed_type: str | None = None
    supports: str | None = None
    brim: str | None = None
    infill: int | None = None
    walls: int | None = None


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
    if opts.filament and opts.filament != s.filament and \
            opts.filament not in _library().compatible("filament", s.machine):
        raise HTTPException(400, f"material {opts.filament!r} does not fit {printer.name or printer.id}")
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
            await send_job(settings, result, req.start, progress=lambda m: job["log"].append(m))
            job.update(state="started" if req.start else "uploaded", result=result.as_dict())
        except Exception as e:  # noqa: BLE001
            # the sliced G-code is still valid: allow another attempt
            job.update(state="sliced", error=f"Sending failed: {e}")

    _spawn(worker())
    return {"job": job_id}


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
