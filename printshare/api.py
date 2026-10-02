"""HTTP API + the PocketPrint3D web app (PWA) on port 8484.

App flow (all /api endpoints need `Authorization: Bearer <api_token>` or `?token=`):
  GET  /api/info            server name/version (the app uses it to test the connection)
  GET  /api/server          public: {"cloud": bool, "login": "token"|"email"} (no login needed)
Cloud mode only (settings.cloud, docs/CLOUD.md) - accounts instead of one token:
  POST /api/auth/code {"email", "lang"} -> login code by e-mail;  POST /api/auth/login {"email", "code", "device"}
  GET /api/auth/me · POST /api/auth/logout · DELETE /api/auth/account?confirm=true · GET /api/admin/stats (operator)
  POST /api/printers · PATCH|DELETE /api/printers/{id}   the account's printers (no addresses)
  GET  /api/machines   OrcaSlicer printer models [{"name", "vendor"}] (model choice for Prusa/OctoPrint printers)
  /spoolman/api/v1/info|spool|spool/{id}|spool/{id}/use   the account's spools in Spoolman's shapes (0.17.0)
  POST /api/profiles/orca-cloud {"link"}   import a bundle shared on cloud.orcaslicer.com (#7, 0.18.0)
  GET  /api/filament-db/brands · /api/filament-db/filaments?brand=&diameter=   SpoolmanDB presets for spools (0.19.0)
  GET|PUT|DELETE /api/manyfold/config · GET /api/manyfold/image/{model}/{file}   own Manyfold library (0.21.0, not in the cloud)
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
  GET  /api/printers/{id}/power     smart plug state {available, state}; POST {"on": bool} (issue #9)
  GET/PUT/DELETE /api/printers/{id}/power/config   Home Assistant URL / token (never returned) / entity
  POST /api/printers/{id}/power/test | /power/entities   check the settings, list switchable entities
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
import dataclasses
import json
import os
import re
import secrets
import shutil
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .cloud import accounts
from .cloud.spools import Spools
from . import orca_cloud
from . import filament_db
from . import manyfold as mf
from .cloud.mail import BrevoMailer, LogMailer, Mailer, MailError
from .config import BRIM_TYPES, INFILL_PATTERNS, SUPPORT_TYPES, JobOptions, PrinterConfig, Settings, load_settings, printer_from_config
from . import camera as cam
from . import gcode_preview
from .fetch import SLICEABLE, FetchError, Fetcher
from .pipeline import JobResult, fetch_model, inspect_model, prepare_job, run_job, send_job
from .printers import CONTROL_ACTIONS, LEVELING_TYPES, PRINTER_TYPES, get_adapter
from . import lanes as lane_map
from . import power as plug
from . import user_profiles
from .profiles import ProfileError, ProfileLibrary, load_user_preset
from .search import Search

WEB = Path(__file__).parent / "web"
PLATES = ["Textured PEI Plate", "High Temp Plate", "Cool Plate", "Engineering Plate", "Supertack Plate"]
MAX_JOBS = 50
MAX_UPLOAD = 300 * 1024 * 1024
UPLOAD_PREFIX = "upload:"

settings = load_settings()
app = FastAPI(title="PocketPrint3D", version="0.22.0")
app.add_middleware(GZipMiddleware, minimum_size=2000)  # layer previews are large but compress well
app.mount("/static", StaticFiles(directory=WEB), name="static")
JOBS: dict[str, dict[str, Any]] = {}
# temperature history for printers that don't keep one (Centauri): filled from status queries
TEMP_LOG: dict[str, deque] = {}
TEMP_LOG_SECONDS = 30 * 60
_SEARCH: Search | None = None
_TASKS: set[asyncio.Task] = set()  # keep references so tasks are not garbage-collected


@dataclass
class Account:
    """Who is asking. Single household: "local" with the server's own configuration. Cloud mode: one user with
    their own printers, profiles, uploads, downloads and G-code (a per-user copy of the settings)."""
    id: str
    settings: Settings
    user: accounts.User | None = None
    token: str | None = None

    @property
    def cloud(self) -> bool:
        return self.user is not None


ACCOUNTS: accounts.Accounts | None = None
MAILER: Mailer | None = None
SPOOLS: Spools | None = None


def _cloud_setup() -> None:
    global ACCOUNTS, MAILER, SPOOLS
    if not settings.cloud:
        ACCOUNTS = MAILER = SPOOLS = None
        return
    ACCOUNTS = accounts.Accounts(settings.cloud_db)
    SPOOLS = Spools(ACCOUNTS)
    MAILER = BrevoMailer(settings.brevo_api_key) if settings.mail == "brevo" else LogMailer()


def _user_account(user: accounts.User, token: str) -> Account:
    base = settings
    cfg_dir = Path(base.config_dir or "/config") / "users" / user.id
    work, gcode = Path(base.work_dir) / "users" / user.id, Path(base.gcode_dir) / "users" / user.id
    for d in (cfg_dir, work, gcode):
        d.mkdir(parents=True, exist_ok=True)
    printers = []
    for p in ACCOUNTS.printers(user.id):
        try:
            printers.append(printer_from_config(p, cfg_dir, base.orca_profiles_dir))
        except (TypeError, ValueError):      # a stored printer that no longer loads: leave it out, don't lock the user out
            continue
    view = dataclasses.replace(base, printers=printers, config_dir=str(cfg_dir), work_dir=str(work),
                               gcode_dir=str(gcode), api_token="")
    return Account(user.id, view, user, token)


_cloud_setup()


def _token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header.removeprefix("Bearer ").strip() or request.query_params.get("token", "")


def auth(request: Request) -> Account:
    token = _token(request)
    if settings.cloud:
        user = ACCOUNTS.user_for_token(token) if token else None
        if user is not None:
            return _user_account(user, token)
        if settings.api_token and token and secrets.compare_digest(token, settings.api_token):
            return Account("admin", dataclasses.replace(settings, printers=[]))   # operator: stats only
        raise HTTPException(401, "please log in")
    if settings.api_token and not secrets.compare_digest(token, settings.api_token):
        raise HTTPException(401, "invalid token")
    return Account("local", settings)       # no token configured: only acceptable on a trusted LAN


def _local_only(acct: Account) -> None:
    """In the cloud the printer is on the user's home network: the app talks to it, not the server."""
    if acct.cloud or acct.id == "admin":
        raise HTTPException(409, "the printer is reached through the app on your home network")


def _printer(acct: "Account", printer_id: str | None) -> PrinterConfig:
    try:
        return acct.settings.printer(printer_id)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))


def _library() -> ProfileLibrary:
    return ProfileLibrary.cached(settings.orca_profiles_dir)


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _new_job(kind: str, state: str, request: dict[str, Any], owner: str = "local") -> dict[str, Any]:
    # forget the oldest finished jobs (in memory only; G-code cleanup is BE-05)
    for old in sorted(JOBS.values(), key=lambda j: j["created"])[:max(0, len(JOBS) - MAX_JOBS + 1)]:
        if old["state"] not in ("slicing", "sending", "running"):
            JOBS.pop(old["id"], None)
    job = {"id": uuid.uuid4().hex[:10], "kind": kind, "state": state, "log": [], "result": None,
           "error": None, "created": time.time(), "request": request, "owner": owner}
    JOBS[job["id"]] = job
    return job


@app.get("/api/info")
def info(acct: Account = Depends(auth)) -> dict[str, Any]:
    return {"name": "PrintShare", "version": app.version, "printers": len(acct.settings.printers),
            "cloud": settings.cloud}


@app.get("/api/server")
def server_info() -> dict[str, Any]:
    """Public (no login): what kind of server this is, so an app knows whether to ask for a token or an e-mail."""
    return {"name": "PrintShare", "version": app.version, "cloud": settings.cloud,
            "login": "email" if settings.cloud else "token"}


# ---------- cloud mode: accounts (docs/CLOUD.md) ----------
def _cloud_only() -> accounts.Accounts:
    if not settings.cloud or ACCOUNTS is None:
        raise HTTPException(404, "this server has no accounts - it uses an access token")
    return ACCOUNTS


def _client_ip(request: Request) -> str | None:
    """Behind Caddy the client address comes in X-Forwarded-For (only trusted from a private proxy address)."""
    peer = request.client.host if request.client else None
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if fwd and peer and re.match(r"^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|127\.|::1|fd)", peer):
        return fwd
    return peer


class CodeRequest(BaseModel):
    email: str
    lang: str = "en"


class LoginRequest(BaseModel):
    email: str
    code: str
    device: str | None = None       # e.g. "Pixel 8" - shown later in a list of logged-in devices


@app.post("/api/auth/code")
async def auth_code(req: CodeRequest, request: Request) -> dict[str, Any]:
    """Step 1: send a 6-digit login code by e-mail (creates the account on the first login)."""
    db = _cloud_only()
    try:
        email = accounts.normalize_email(req.email)
        code = await asyncio.to_thread(db.request_code, email, _client_ip(request))
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e))
    try:
        await asyncio.to_thread(MAILER.send_code, email, code, "de" if req.lang.lower().startswith("de") else "en")
    except MailError as e:
        raise HTTPException(502, str(e))
    return {"sent": True, "email": email}


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest) -> dict[str, Any]:
    """Step 2: the code from the e-mail -> a session token for this device (send it as `Authorization: Bearer`)."""
    db = _cloud_only()
    try:
        user, token = await asyncio.to_thread(db.verify_code, req.email, req.code, req.device)
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e))
    return {"token": token, "user": {"id": user.id, "email": user.email}}


@app.get("/api/auth/me")
def auth_me(acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud:
        raise HTTPException(404, "not logged in with an account")
    return {"id": acct.user.id, "email": acct.user.email, "printers": len(acct.settings.printers),
            "limits": {"slices_per_day": settings.limit_slices_per_day,
                       "slices_today": ACCOUNTS.usage_today(acct.id), "upload_mb": settings.limit_upload_mb}}


@app.post("/api/auth/logout")
def auth_logout(acct: Account = Depends(auth)) -> dict[str, Any]:
    if acct.cloud:
        ACCOUNTS.logout(acct.token)
    return {"ok": True}


@app.delete("/api/auth/account")
def auth_delete_account(confirm: bool = False, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Delete the account and everything of it: printers, profiles, uploads, G-code, jobs (Apple/Google require
    this in the app). Needs ?confirm=true."""
    if not acct.cloud:
        raise HTTPException(404, "not logged in with an account")
    if not confirm:
        raise HTTPException(400, "deleting the account needs confirm=true")
    for jid in [j["id"] for j in JOBS.values() if j.get("owner") == acct.id]:
        JOBS.pop(jid, None)
    for d in (acct.settings.config_dir, acct.settings.work_dir, acct.settings.gcode_dir):
        shutil.rmtree(d, ignore_errors=True)
    ACCOUNTS.delete_user(acct.id)
    return {"deleted": True}


@app.get("/api/admin/stats")
def admin_stats(acct: Account = Depends(auth)) -> dict[str, Any]:
    if acct.id != "admin":
        raise HTTPException(403, "operator only")
    return {**ACCOUNTS.stats(), "spools": SPOOLS.count(), "jobs_in_memory": len(JOBS),
            "slicing_now": sum(1 for j in JOBS.values() if j["state"] == "slicing")}


@app.get("/api/machines")
async def machines(acct: Account = Depends(auth)) -> list[dict[str, str]]:
    """OrcaSlicer printer models to choose from (cloud printers of type prusalink/octoprint need one)."""
    return await asyncio.to_thread(lambda: _library().machines())


# ---------- cloud mode: the account's printers (no addresses - the app reaches them at home) ----------
MAX_PRINTERS = 10


class PrinterSettings(BaseModel):
    name: str | None = None
    type: str | None = None             # elegoo_sdcp | moonraker | prusalink | octoprint
    machine: str | None = None          # OrcaSlicer printer preset; required for Prusa/OctoPrint
    cosmos: bool | None = None          # Centauri Carbon with OpenCentauri COSMOS (Klipper)
    auto_leveling: bool | None = None


def _printer_config(pid: str, req: PrinterSettings, old: dict[str, Any] | None = None) -> dict[str, Any]:
    old = old or {}
    name = (req.name if req.name is not None else old.get("name", "")).strip()
    ptype = req.type or old.get("type")
    if not 1 <= len(name) <= 60:
        raise HTTPException(400, "the printer needs a name (up to 60 characters)")
    if ptype not in PRINTER_TYPES:
        raise HTTPException(400, f"type must be one of {', '.join(PRINTER_TYPES)}")
    sl = dict(old.get("slicing") or {})
    if req.machine is not None:
        sl["machine"] = req.machine
    if req.cosmos is not None:
        if req.cosmos:
            sl["machine_preset"] = "cosmos"
        else:
            sl.pop("machine_preset", None)
    if ptype in ("prusalink", "octoprint") and not sl.get("machine"):
        raise HTTPException(400, "choose the printer model (OrcaSlicer printer profile) for this printer")
    if sl.get("machine"):
        try:
            _library().resolve("machine", sl["machine"])
        except ProfileError as e:
            raise HTTPException(400, str(e))
    cfg = {"id": pid, "name": name, "type": ptype,
           "auto_leveling": req.auto_leveling if req.auto_leveling is not None else old.get("auto_leveling", True),
           "slicing": sl}
    return cfg


@app.post("/api/printers")
def add_printer(req: PrinterSettings, acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud:
        raise HTTPException(409, "printers are set up in the server's configuration")
    if len(acct.settings.printers) >= MAX_PRINTERS:
        raise HTTPException(400, f"at most {MAX_PRINTERS} printers per account")
    pid = re.sub(r"[^a-z0-9]+", "-", (req.name or "printer").lower()).strip("-")[:24] or "printer"
    if any(p.id == pid for p in acct.settings.printers):
        pid = f"{pid}-{uuid.uuid4().hex[:4]}"
    cfg = _printer_config(pid, req)
    try:
        printer_from_config(cfg, Path(acct.settings.config_dir), settings.orca_profiles_dir)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))
    ACCOUNTS.save_printer(acct.id, cfg)
    return _printer_json(_user_account(acct.user, acct.token), pid)


@app.patch("/api/printers/{printer_id}")
def update_printer(printer_id: str, req: PrinterSettings, acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud:
        raise HTTPException(409, "printers are set up in the server's configuration")
    old = next((p for p in ACCOUNTS.printers(acct.id) if p["id"] == printer_id), None)
    if old is None:
        raise HTTPException(404, f"Unknown printer {printer_id!r}")
    cfg = _printer_config(printer_id, req, old)
    try:
        printer_from_config(cfg, Path(acct.settings.config_dir), settings.orca_profiles_dir)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))
    ACCOUNTS.save_printer(acct.id, cfg)
    return _printer_json(_user_account(acct.user, acct.token), printer_id)


@app.delete("/api/printers/{printer_id}")
def delete_printer(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud:
        raise HTTPException(409, "printers are set up in the server's configuration")
    if not ACCOUNTS.delete_printer(acct.id, printer_id):
        raise HTTPException(404, f"Unknown printer {printer_id!r}")
    user_profiles.write_overlay(acct.settings.config_dir, printer_id, {})     # its profile/power settings too
    return {"deleted": printer_id}


# ---------- cloud: spools of the account, in Spoolman's API shapes (docs/API.md "Spoolman") ----------
class SpoolFilament(BaseModel):
    name: str | None = Field(None, max_length=64)
    vendor: str | None = Field(None, max_length=64)
    material: str | None = Field(None, max_length=64)
    color_hex: str | None = Field(None, pattern=r"^#?[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
    density: float | None = Field(None, gt=0.3, le=5)        # g/cm³
    diameter: float | None = Field(None, gt=0.5, le=5)       # mm
    weight: float | None = Field(None, gt=0, le=20000)       # g of filament on a new spool


class SpoolChange(BaseModel):
    filament: SpoolFilament | None = None
    initial_weight: float | None = Field(None, gt=0, le=20000)
    remaining_weight: float | None = Field(None, ge=0, le=20000)
    spool_weight: float | None = Field(None, ge=0, le=5000)
    location: str | None = Field(None, max_length=64)
    comment: str | None = Field(None, max_length=1024)
    archived: bool | None = None


class SpoolUse(BaseModel):
    use_weight: float | None = Field(None, ge=-20000, le=20000)
    use_length: float | None = Field(None, ge=-1e7, le=1e7)


def _spool_user(acct: Account = Depends(auth)) -> str:
    if not acct.cloud or SPOOLS is None:
        raise HTTPException(404, "spools are kept in the cloud only - at home use your own Spoolman")
    return acct.id


def _spools_call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e))


@app.get("/spoolman/api/v1/info")
def spools_info(user: str = Depends(_spool_user)) -> dict[str, Any]:
    return {"version": app.version, "name": "PocketPrint3D", "debug_mode": False, "automatic_backups": True,
            "data_dir": "", "logs_dir": "", "backups_dir": "", "db_type": "sqlite", "external_db_name": ""}


@app.get("/spoolman/api/v1/spool")
def spools_list(allow_archived: bool = False, user: str = Depends(_spool_user)) -> list[dict[str, Any]]:
    """Like Spoolman's GET /spool: recently used first (other filter/sort parameters are accepted and ignored)."""
    return SPOOLS.list(user, allow_archived)


@app.post("/spoolman/api/v1/spool")
def spools_create(req: SpoolChange, user: str = Depends(_spool_user)) -> dict[str, Any]:
    return _spools_call(SPOOLS.create, user, req.model_dump(exclude_unset=True))


@app.get("/spoolman/api/v1/spool/{num}")
def spools_get(num: int, user: str = Depends(_spool_user)) -> dict[str, Any]:
    return _spools_call(SPOOLS.get, user, num)


@app.patch("/spoolman/api/v1/spool/{num}")
def spools_update(num: int, req: SpoolChange, user: str = Depends(_spool_user)) -> dict[str, Any]:
    return _spools_call(SPOOLS.update, user, num, req.model_dump(exclude_unset=True))


@app.delete("/spoolman/api/v1/spool/{num}")
def spools_delete(num: int, user: str = Depends(_spool_user)) -> dict[str, Any]:
    _spools_call(SPOOLS.delete, user, num)
    return {"deleted": num}


@app.put("/spoolman/api/v1/spool/{num}/use")
def spools_use(num: int, req: SpoolUse, user: str = Depends(_spool_user)) -> dict[str, Any]:
    return _spools_call(SPOOLS.use, user, num, req.use_weight, req.use_length)


@app.get("/api/pairing")
async def pairing(request: Request, url: str | None = None, remote: str | None = None, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Pairing code for the app (issue #10), so nobody needs the command line or the container log.
    Addresses: query > PRINTSHARE_URL / HA server_url (remote: PRINTSHARE_REMOTE_URL / HA remote_url) >
    the address this page was opened with. Needs the token like every /api endpoint - the code contains it."""
    _local_only(acct)
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
    link = pairing_link(home, acct.settings.api_token, away)
    svg = segno.make(link, error="m").svg_inline(scale=5, border=2, light="#fff", omitsize=True)  # viewBox: scales in CSS
    return {"link": link, "svg": svg, "url": home, "remote_url": away, "token": acct.settings.api_token,
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


@app.get("/api/printers")
def printers(acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    return [_printer_json(acct, p.id) for p in acct.settings.printers]


def _printer_json(acct: Account, printer_id: str) -> dict[str, Any]:
    p = _printer(acct, printer_id)
    return {"id": p.id, "name": p.name or p.id, "type": p.type, "machine": p.slicing.machine,
            # DO-01: the app shows the leveling switch only where it works per print
            "leveling": p.auto_leveling if p.type in LEVELING_TYPES else None,
            # issue #9: a smart plug is set up -> the app offers "switch on" while the printer is off
            "power": plug.load(acct.settings.config_dir, p.id) is not None,
            "cosmos": p.slicing.machine_preset == "cosmos"}


def _defaults(acct: "Account", printer: PrinterConfig, process: str) -> dict[str, Any]:
    s = printer.slicing
    proc = user_profiles.resolve_preset(_library(), acct.settings.config_dir or None, "process", process,
                                        s.process_overrides if process == s.process else None)
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
    try:  # mm; a percentage of the nozzle (e.g. "100%") gives null, the apps assume ~0.45 mm then
        line_width = float(proc.get("sparse_infill_line_width"))
    except (TypeError, ValueError):
        line_width = None
    return {"filament": s.filament, "process": process, "bed_type": s.bed_type,
            "supports": support, "brim": brim, "infill": infill, "walls": walls,
            # Orca reads the legacy "zig-zag" as rectilinear (PrintConfig handle_legacy); Elegoo CC presets still use it
            "infill_pattern": {"zig-zag": "rectilinear"}.get(pat := proc.get("sparse_infill_pattern") or None, pat),
            "infill_line_width": line_width or None,
            "layer_height": proc.get("layer_height")}


def _own_presets(acct: "Account", printer: PrinterConfig, kind: str, lib: ProfileLibrary) -> list[str]:
    """Uploaded presets of `kind` that fit this printer (its system base or its own uploaded printer preset)."""
    machines = [printer.slicing.machine]
    if printer.slicing.machine_file:
        try:
            machines.append(json.loads(Path(printer.slicing.machine_file).read_text(encoding="utf-8")).get("name"))
        except (OSError, ValueError):
            pass
    return user_profiles.compatible_user_presets(lib, acct.settings.config_dir or None, kind, [m for m in machines if m])


@app.get("/api/printers/{printer_id}/options")
async def options(printer_id: str, process: str | None = None, acct: Account = Depends(auth)) -> dict[str, Any]:
    printer = _printer(acct, printer_id)
    lib = await asyncio.to_thread(_library)
    machine = printer.slicing.machine
    materials, processes = await asyncio.gather(
        asyncio.to_thread(lib.compatible, "filament", machine),
        asyncio.to_thread(lib.compatible, "process", machine))
    # uploaded quality/material presets (#2, later Orca Cloud #7) come first, marked as own
    own_m, own_p = await asyncio.gather(
        asyncio.to_thread(_own_presets, acct, printer, "filament", lib),
        asyncio.to_thread(_own_presets, acct, printer, "process", lib))
    materials = own_m + [m for m in materials if m not in own_m]
    processes = own_p + [p for p in processes if p not in own_p]
    # configured presets are always offered, even if Orca doesn't list them as compatible
    for name, names in ((printer.slicing.filament, materials), (printer.slicing.process, processes)):
        if name not in names:
            names.insert(0, name)
    try:
        defaults = await asyncio.to_thread(_defaults, acct, printer, process or printer.slicing.process)
    except ProfileError as e:
        raise HTTPException(400, str(e))
    return {"printer": printer.id, "materials": materials, "processes": processes,
            "own": {"materials": own_m, "processes": own_p},
            "plates": PLATES, "supports": ["off", *SUPPORT_TYPES], "brims": list(BRIM_TYPES),
            "infill_patterns": list(INFILL_PATTERNS), "defaults": defaults}


@app.get("/api/printers/{printer_id}/status")
async def status(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    printer = _printer(acct, printer_id)
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
# ---------- power: smart plug through Home Assistant (issue #9) ----------
class PowerSwitch(BaseModel):
    on: bool


class PowerSettings(BaseModel):
    url: str = ""
    token: str | None = None      # None = keep the stored token, "" = remove it
    entity: str = ""


def _power_cfg(acct: "Account", printer_id: str, body: PowerSettings | None = None) -> plug.PowerConfig:
    """Stored settings, or the ones being edited on the web page (token kept unless a new one is given)."""
    _printer(acct, printer_id)
    stored = plug.load(acct.settings.config_dir, printer_id)
    if body is None:
        if stored is None:
            raise HTTPException(404, "no power switch set up for this printer")
        return stored
    token = body.token if body.token is not None else (stored.token if stored else "")
    return plug.PowerConfig(url=body.url.strip().rstrip("/"), token=token.strip(), entity=body.entity.strip())


async def _power_call(coro_fn):
    try:
        return await coro_fn()
    except plug.PowerError as e:
        raise HTTPException(502, str(e))


@app.get("/api/printers/{printer_id}/power")
async def power_state(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    _printer(acct, printer_id)
    cfg = plug.load(acct.settings.config_dir, printer_id)
    if cfg is None:
        return {"available": False, "state": None}
    try:
        state = await plug.get_power(cfg).state()
        return {"available": True, "state": state, "error": None}
    except plug.PowerError as e:
        return {"available": True, "state": "unknown", "error": str(e)}


@app.post("/api/printers/{printer_id}/power")
async def power_switch(printer_id: str, req: PowerSwitch, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    cfg = _power_cfg(acct, printer_id)
    if not req.on:
        # never cut the power of a running print - checked here, not only in the app
        try:
            state = (await get_adapter(_printer(acct, printer_id)).status()).get("state")
        except Exception:  # noqa: BLE001 - printer unreachable: it can't be printing
            state = None
        if printer_kind(state) in ("active", "paused"):
            raise HTTPException(409, "the printer is printing - it can't be switched off now")
    await _power_call(lambda: plug.get_power(cfg).turn(req.on))
    return {"ok": True, "state": "on" if req.on else "off"}


@app.get("/api/printers/{printer_id}/power/config")
def power_config(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    _printer(acct, printer_id)
    cfg = plug.load(acct.settings.config_dir, printer_id)
    return {"configured": cfg is not None, "addon": bool(os.environ.get("SUPERVISOR_TOKEN")),
            **(cfg or plug.PowerConfig()).public()}


@app.put("/api/printers/{printer_id}/power/config")
async def set_power_config(printer_id: str, req: PowerSettings, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    cfg = _power_cfg(acct, printer_id, req)
    try:
        plug.get_power(cfg)._domain()            # address, token and entity format checked before saving
    except plug.PowerError as e:
        raise HTTPException(400, str(e))
    plug.save(acct.settings.config_dir, printer_id, cfg)
    return power_config(printer_id, acct)


@app.delete("/api/printers/{printer_id}/power/config")
def delete_power_config(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    _printer(acct, printer_id)
    plug.save(acct.settings.config_dir, printer_id, None)
    return power_config(printer_id, acct)


@app.post("/api/printers/{printer_id}/power/test")
async def power_test(printer_id: str, req: PowerSettings, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    cfg = _power_cfg(acct, printer_id, req)
    try:
        return {"ok": True, **(await plug.get_power(cfg).test())}
    except plug.PowerError as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/printers/{printer_id}/power/entities")
async def power_entities(printer_id: str, req: PowerSettings, acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    _local_only(acct)
    cfg = _power_cfg(acct, printer_id, req)
    try:
        return await plug.get_power(cfg).entities()
    except plug.PowerError as e:
        raise HTTPException(502, str(e))


@app.get("/api/printers/{printer_id}/controls")
async def printer_controls(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    adapter = get_adapter(_printer(acct, printer_id))
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


@app.post("/api/printers/{printer_id}/adjust")
async def adjust(printer_id: str, req: Adjustment, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    adapter = get_adapter(_printer(acct, printer_id))
    caps = await printer_controls(printer_id, acct)
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


@app.get("/api/printers/{printer_id}/temperatures")
async def temperatures(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Temperature history: from the printer where it keeps one (Moonraker, OctoPrint), else what
    PocketPrint3D saw in the last 30 minutes of status queries."""
    _local_only(acct)
    adapter = get_adapter(_printer(acct, printer_id))
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


# ---------- camera (issue #3, DR-06): the app only talks to PocketPrint3D, also away from home ----------
async def _camera(acct: "Account", printer_id: str) -> cam.Camera:
    printer = _printer(acct, printer_id)
    adapter = get_adapter(printer)
    try:
        source = await adapter.camera() if hasattr(adapter, "camera") else None
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"camera not reachable: {e}")
    if source is None:
        raise HTTPException(404, "this printer has no camera")
    return source


@app.get("/api/printers/{printer_id}/camera")
async def camera_info(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    try:
        return (await _camera(acct, printer_id)).info()
    except HTTPException as e:
        if e.status_code == 404:
            return {"available": False, "stream": False, "snapshot": False, "name": None}
        raise


@app.get("/api/printers/{printer_id}/camera/snapshot")
async def camera_snapshot(printer_id: str, w: int | None = None, acct: Account = Depends(auth)) -> Response:
    """Current camera image; `w` scales it down (thumbnails, mobile data)."""
    _local_only(acct)
    source = await _camera(acct, printer_id)
    try:
        jpeg = await cam.snapshot(source)
        if w:
            jpeg = await asyncio.to_thread(cam.scale, jpeg, max(160, min(w, 1920)))
    except cam.CameraError as e:
        raise HTTPException(502, str(e))
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/printers/{printer_id}/camera/stream")
async def camera_stream(printer_id: str, acct: Account = Depends(auth)) -> StreamingResponse:
    """Live MJPEG from the printer, passed through (ends when the app closes the view)."""
    _local_only(acct)
    source = await _camera(acct, printer_id)
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


@app.post("/api/printers/{printer_id}/control")
async def control(printer_id: str, req: ControlRequest, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    printer = _printer(acct, printer_id)
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
def _uploads(acct: "Account") -> Path:
    return Path(acct.settings.work_dir) / "uploads"


def _resolve_link(acct: "Account", link: str) -> str:
    """Only http(s) links and files uploaded through /api/uploads; never arbitrary server paths."""
    if link.startswith(UPLOAD_PREFIX):
        uid = link[len(UPLOAD_PREFIX):]
        d = _uploads(acct) / uid
        found = [f for f in d.iterdir() if f.is_file()] if re.fullmatch(r"[0-9a-f]{12}", uid) and d.is_dir() else []
        if not found:
            raise HTTPException(404, "uploaded file not found - please choose it again")
        return str(found[0])
    if re.fullmatch(r"manyfold:[A-Za-z0-9_-]{1,64}", link):      # a model of the own Manyfold library (0.21.0)
        return link
    if not link.startswith(("http://", "https://")):
        raise HTTPException(400, "link must be an http(s) URL")
    return link


@app.post("/api/uploads")
async def upload(request: Request, name: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Model file from the phone (Files app, share menu); body = raw file content."""
    safe = re.sub(r"[^\w.\- ]+", "_", Path(name).name).strip()
    if not safe.lower().endswith(SLICEABLE):
        raise HTTPException(400, f"unsupported file type - use {', '.join(SLICEABLE)}")
    uid = uuid.uuid4().hex[:12]
    d = _uploads(acct) / uid
    d.mkdir(parents=True)
    size = 0
    limit = settings.limit_upload_mb * 1048576 if acct.cloud else MAX_UPLOAD
    try:
        with open(d / safe, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"file too large (max {limit // 1048576} MB)")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "empty file")
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return {"id": uid, "link": UPLOAD_PREFIX + uid, "name": safe, "size": size}


@app.get("/api/files")
async def files(link: str, acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    local = _resolve_link(acct, link)
    try:
        fetcher = Fetcher(acct.settings.thingiverse_token, manyfold=mf.client_for(acct.settings))
        listed = await asyncio.to_thread(fetcher.list_files, local)
        fl = [f for f in listed if f.sliceable]
    except FetchError as e:
        raise HTTPException(400, str(e))
    return [{"index": i, "name": f.name, "size": f.size} for i, f in enumerate(fl, 1)]


@app.get("/api/inspect")
async def inspect(link: str, file: str | None = None, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Filaments (colours) of a model, so the app can offer a material per colour (MA-04)."""
    local = _resolve_link(acct, link)
    try:
        return await asyncio.to_thread(inspect_model, acct.settings, local, file)
    except FetchError as e:
        raise HTTPException(400, str(e))


# ---------- own OrcaSlicer presets (issue #2) ----------
def _reload_settings() -> None:
    """Printer settings changed from the app: take effect without restarting the container."""
    global settings
    settings = load_settings()


def _profile_error(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


@app.get("/api/profiles")
async def profiles_list(acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    lib = await asyncio.to_thread(_library)
    return await asyncio.to_thread(user_profiles.list_profiles, acct.settings.config_dir, lib)


@app.post("/api/profiles")
async def profiles_upload(request: Request, filename: str = "profile.json", acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    """A preset exported from OrcaSlicer (JSON) or a preset bundle (zip); raw body."""
    content = await request.body()
    lib = await asyncio.to_thread(_library)
    try:
        return await asyncio.to_thread(user_profiles.store, acct.settings.config_dir, filename, content, lib)
    except user_profiles.ProfileUploadError as e:
        raise _profile_error(e)


# ---------- SpoolmanDB: filament presets for adding spools ----------
_FILAMENT_DB: filament_db.FilamentDb | None = None


def _filament_db() -> filament_db.FilamentDb:
    global _FILAMENT_DB
    if _FILAMENT_DB is None:
        _FILAMENT_DB = filament_db.FilamentDb(Path(settings.work_dir) / "cache")
    return _FILAMENT_DB


@app.get("/api/filament-db/brands")
async def filament_brands(acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    try:
        return await asyncio.to_thread(_filament_db().brand_list)
    except filament_db.FilamentDbError as e:
        raise HTTPException(503, str(e))


@app.get("/api/filament-db/filaments")
async def filament_list(brand: str, diameter: float = 1.75, acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    try:
        return await asyncio.to_thread(_filament_db().filaments, brand, diameter)
    except filament_db.FilamentDbError as e:
        raise HTTPException(404 if "unknown brand" in str(e) else 503, str(e))


class OrcaCloudImport(BaseModel):
    link: str = Field(..., max_length=300)


@app.post("/api/profiles/orca-cloud")
async def profiles_orca_cloud(req: OrcaCloudImport, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Import a bundle shared on cloud.orcaslicer.com (issue #7) - no Orca account needed."""
    lib = await asyncio.to_thread(_library)
    try:
        return await asyncio.to_thread(orca_cloud.import_bundle, acct.settings.config_dir, req.link, lib)
    except orca_cloud.OrcaCloudError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/profiles/{file}")
def profiles_delete(file: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    try:
        user_profiles.delete(acct.settings.config_dir, file, [p.id for p in acct.settings.printers])
    except user_profiles.ProfileUploadError as e:
        raise _profile_error(e)
    return {"deleted": file}


@app.get("/api/printers/{printer_id}/profile")
def printer_profile(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Printer preset in use: an uploaded one (`machine_file`), one set by hand in config.yaml
    (`config_file`), or the OrcaSlicer system preset `machine` (+ built-in `machine_preset`)."""
    s = _printer(acct, printer_id).slicing
    uploaded = (user_profiles.read_overlay(acct.settings.config_dir, printer_id).get("slicing") or {}).get("machine_file")
    return {"machine": s.machine, "machine_file": uploaded,
            "config_file": None if uploaded or not s.machine_file else Path(s.machine_file).name,
            "machine_preset": s.machine_preset}


class ProfileAssignment(BaseModel):
    machine_file: str | None = None


@app.put("/api/printers/{printer_id}/profile")
async def set_printer_profile(printer_id: str, req: ProfileAssignment, acct: Account = Depends(auth)) -> dict[str, Any]:
    _printer(acct, printer_id)
    lib = await asyncio.to_thread(_library)
    try:
        await asyncio.to_thread(user_profiles.assign_machine, acct.settings.config_dir, printer_id, req.machine_file, lib)
    except user_profiles.ProfileUploadError as e:
        raise _profile_error(e)
    if acct.cloud:
        acct = _user_account(acct.user, acct.token)      # the printer view now includes the new profile
    else:
        _reload_settings()
        acct = Account("local", settings)
    return printer_profile(printer_id, acct)


@app.get("/api/model-file")
async def model_file(link: str, file: str | None = None, acct: Account = Depends(auth)) -> FileResponse:
    """One file of a model (index as in /api/files), so the app can show it in 3D before slicing (MQ-06).
    Served from the download cache that inspect and slicing use; never re-hosted anywhere else."""
    local = _resolve_link(acct, link)
    try:
        chosen, path = await asyncio.to_thread(fetch_model, acct.settings, local, file)
    except FetchError as e:
        raise HTTPException(400, str(e))
    if path.stat().st_size > MAX_UPLOAD:
        raise HTTPException(413, "model file too large for the 3D view")
    return FileResponse(path, media_type="application/octet-stream", filename=Path(chosen.name).name)


# ---------- search (MQ-05/06) ----------
def _search() -> Search:
    """One search for the server; rebuilt when the Manyfold library is set up or changed (never in the cloud)."""
    global _SEARCH
    library = mf.client_for(settings)
    if _SEARCH is None or _SEARCH.manyfold is not library:
        _SEARCH = Search(settings.thingiverse_token, manyfold=library)
    return _SEARCH


# ---------- own Manyfold library (home servers) ----------
class ManyfoldSettings(BaseModel):
    url: str = Field(..., max_length=300)
    token: str | None = Field(None, max_length=500)            # None = keep the stored one
    client_id: str | None = Field(None, max_length=200)
    client_secret: str | None = Field(None, max_length=500)


def _manyfold_home(acct: Account) -> None:
    if acct.cloud or settings.cloud:
        raise HTTPException(409, "Manyfold works with your own PocketPrint3D server, which can reach it at home")


@app.get("/api/manyfold/config")
def manyfold_config(acct: Account = Depends(auth)) -> dict[str, Any]:
    _manyfold_home(acct)
    cfg = mf.load_config(settings)
    return {"configured": cfg.configured, "url": cfg.url or None, "token_set": bool(cfg.token),
            "client_set": bool(cfg.client_id and cfg.client_secret)}


@app.put("/api/manyfold/config")
async def manyfold_config_set(req: ManyfoldSettings, acct: Account = Depends(auth)) -> dict[str, Any]:
    _manyfold_home(acct)
    url = req.url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
        raise HTTPException(400, "the Manyfold address looks like http://192.168.1.20:3214")
    old = mf.load_config(settings)
    new = mf.ManyfoldConfig(url, old.token if req.token is None else req.token.strip(),
                            old.client_id if req.client_id is None else req.client_id.strip(),
                            old.client_secret if req.client_secret is None else req.client_secret.strip())
    if not new.configured:
        raise HTTPException(400, "enter an API key (Manyfold: your name → API keys) or OAuth app credentials")
    try:
        count = len(await asyncio.to_thread(mf.Manyfold(new).models, True))
    except FetchError as e:
        raise HTTPException(400, f"Manyfold: {e}")
    mf.save_config(settings, new)
    return {"configured": True, "url": url, "models": count}


@app.delete("/api/manyfold/config")
def manyfold_config_delete(acct: Account = Depends(auth)) -> dict[str, Any]:
    _manyfold_home(acct)
    mf.save_config(settings, None)
    return {"configured": mf.load_config(settings).configured}      # config.yaml / environment may still set it


@app.get("/api/manyfold/image/{model_id}/{file_id}")
async def manyfold_image(model_id: str, file_id: str, acct: Account = Depends(auth)) -> Response:
    _manyfold_home(acct)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", model_id) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", file_id):
        raise HTTPException(400, "invalid id")
    library = mf.client_for(settings)
    if library is None:
        raise HTTPException(404, "Manyfold is not set up")
    try:
        data, mime = await asyncio.to_thread(library.image, model_id, file_id)
    except FetchError as e:
        raise HTTPException(404, str(e))
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})


def _search_error(e: FetchError) -> HTTPException:
    msg = str(e)
    return HTTPException(404 if "not found" in msg else 502 if "API error" in msg else 400, msg)


@app.get("/api/sources")
def sources(acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    return _search().list_sources()


@app.get("/api/search")
async def search(q: str, source: str = "printables", page: int = 1, sort: str = "relevant", acct: Account = Depends(auth)) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_search().search, source, q, page, sort)
    except FetchError as e:
        raise _search_error(e)


@app.get("/api/models/{source}/{model_id}")
async def model_detail(source: str, model_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
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
    infill_pattern: str | None = None            # OrcaSlicer sparse_infill_pattern (see /options infill_patterns)
    walls: int | None = None
    filaments: list[str | None] | None = None   # multicolour: preset per filament of the model
    copies: int | None = None                    # plate: copies, OrcaSlicer arranges them (fewer if they don't fit)
    rotate_x: float | None = None                # plate: tilt in degrees before slicing
    rotate_y: float | None = None
    scale: int | None = None                     # plate: size in percent
    orient: bool | None = None                   # plate: lay flat automatically (None = printer setting)


class JobRequest(BaseModel):
    link: str
    printer: str | None = None
    file: str | None = None
    options: OptionsModel = Field(default_factory=OptionsModel)


def _validate_options(acct: "Account", printer: PrinterConfig, o: OptionsModel) -> JobOptions:
    opts = JobOptions(**o.model_dump())
    try:
        opts.process_overrides()
        opts.check_plate()
    except ValueError as e:
        raise HTTPException(400, str(e))
    if opts.bed_type and opts.bed_type not in PLATES:
        raise HTTPException(400, f"unknown plate {opts.bed_type!r}")
    s = printer.slicing

    def fits(kind: str, name: str) -> bool:        # only looked up for presets other than the configured ones
        lib = _library()
        return name in _own_presets(acct, printer, kind, lib) or name in lib.compatible(kind, s.machine)
    for f in [opts.filament, *(opts.filaments or [])]:
        if f and f != s.filament and not fits("filament", f):
            raise HTTPException(400, f"material {f!r} does not fit {printer.name or printer.id}")
    if opts.filaments and len(opts.filaments) > 16:
        raise HTTPException(400, "at most 16 filaments")
    if opts.process and opts.process != s.process and not fits("process", opts.process):
        raise HTTPException(400, f"quality {opts.process!r} does not fit {printer.name or printer.id}")
    return opts


@app.post("/api/jobs")
async def create_job(req: JobRequest, acct: Account = Depends(auth)) -> dict[str, Any]:
    source = _resolve_link(acct, req.link)
    printer = _printer(acct, req.printer)
    opts = await asyncio.to_thread(_validate_options, acct, printer, req.options)
    if acct.cloud:
        # free service: one slicing job at a time per account and a daily limit (docs/CLOUD.md)
        if any(j.get("owner") == acct.id and j["state"] == "slicing" for j in JOBS.values()):
            raise HTTPException(429, "another model of yours is being sliced - please wait until it is done")
        try:
            ACCOUNTS.count_slice(acct.id, settings.limit_slices_per_day)
        except accounts.AccountError as e:
            raise HTTPException(e.status, str(e))
    job = _new_job("prepare", "slicing", req.model_dump(), owner=acct.id)
    job["printer"] = printer.id

    async def worker() -> None:
        try:
            res = await prepare_job(acct.settings, source, printer.id, req.file, opts, out_name=job["id"],
                                    progress=lambda m: job["log"].append(m))
            job.update(state="sliced", result=res.as_dict())
        except Exception as e:  # noqa: BLE001 - report every failure to the phone
            job.update(state="error", error=str(e))

    _spawn(worker())
    return {"job": job["id"]}


@app.get("/api/jobs")
def list_jobs(acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    jobs = sorted((j for j in JOBS.values() if j.get("owner", "local") == acct.id), key=lambda j: j["created"], reverse=True)
    return [{k: j.get(k) for k in ("id", "kind", "state", "error", "created", "printer")}
            | {"link": j["request"].get("link"),
               "file": (j["result"] or {}).get("source_file"),
               "print_time": (j["result"] or {}).get("print_time"),
               "filament_g": (j["result"] or {}).get("filament_g")}
            for j in jobs]


@app.get("/api/jobs/{job_id}")
def job(job_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    return _own_job(acct, job_id)


class SendRequest(BaseModel):
    start: bool = True
    confirm: bool = False
    leveling: bool | None = None  # bed leveling before the print; None = printer default
    # lane selection (issue #6): {"<model filament, 1-based>": <printer tool of the lane>}
    lanes: dict[str, int] | None = None
    # Spoolman (0.16.0): spool that the printer's Moonraker books this print on (status "spoolman" not null)
    spool_id: int | None = Field(None, ge=1)


@app.post("/api/jobs/{job_id}/send")
async def send(job_id: str, req: SendRequest, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    job = _own_job(acct, job_id)
    if req.start and not req.confirm:
        raise HTTPException(400, "starting a print needs confirm=true")  # NF-05
    if job["state"] not in ("sliced", "uploaded"):
        raise HTTPException(409, f"job is {job['state']}, not ready to send")
    result = JobResult(**job["result"])
    if req.spool_id is not None and _printer(acct, result.printer).type != "moonraker":
        raise HTTPException(400, "spool_id only for Klipper printers with Moonraker's Spoolman link")
    try:
        tools = lane_map.parse_mapping(req.lanes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if tools:
        # the chosen lanes must exist and hold filament (DR-03)
        try:
            lanes = (await get_adapter(_printer(acct, result.printer)).status()).get("lanes") or []
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
            state = (await get_adapter(_printer(acct, result.printer)).status()).get("state")
        except Exception:  # noqa: BLE001
            state = None
        if printer_kind(state) in ("active", "paused"):
            raise HTTPException(409, "printer is busy - wait until the current print has finished")
    job.update(state="sending", error=None)

    async def worker() -> None:
        try:
            await send_job(acct.settings, result, req.start, progress=lambda m: job["log"].append(m),
                           leveling=req.leveling, tools=tools, spool_id=req.spool_id)
            job["leveling"] = req.leveling
            job.update(state="started" if req.start else "uploaded", result=result.as_dict())
        except Exception as e:  # noqa: BLE001
            # the sliced G-code is still valid: allow another attempt
            job.update(state="sliced", error=f"Sending failed: {e}")

    _spawn(worker())
    return {"job": job_id}


def _own_job(acct: Account, job_id: str) -> dict[str, Any]:
    """A job of this account (other accounts' jobs don't exist for it)."""
    job = JOBS.get(job_id)
    if job is None or job.get("owner", "local") != acct.id:
        raise HTTPException(404, "unknown job")
    return job


def _job_gcode(acct: "Account", job_id: str) -> tuple[dict[str, Any], Path]:
    job = _own_job(acct, job_id)
    gcode = Path((job.get("result") or {}).get("gcode") or "")
    if not gcode.name or not gcode.is_file():
        raise HTTPException(404, "no G-code for this job (yet)")
    return job, gcode


def _bed(acct: "Account", printer_id: str) -> tuple[float, float] | None:
    try:
        s = acct.settings.printer(printer_id).slicing
        area = (load_user_preset(Path(s.machine_file), None, _library(), "machine") if s.machine_file
                else _library().resolve("machine", s.machine)).get("printable_area")
        return gcode_preview.bed_size(area)
    except Exception:  # noqa: BLE001 - the preview works without the bed outline
        return None


@app.get("/api/jobs/{job_id}/preview")
async def preview(job_id: str, format: int = 1, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Layer data for the G-code viewer (SL-06/07). Apps ask for the format they understand
    (?format=2 adds the filament per line); without it, app builds from before 0.6.0 keep working."""
    job, gcode = _job_gcode(acct, job_id)
    bed = await asyncio.to_thread(_bed, acct, job["result"]["printer"])
    data = await asyncio.to_thread(gcode_preview.build, gcode, bed)
    return gcode_preview.as_version(data, format)


@app.get("/api/jobs/{job_id}/gcode")
async def download_gcode(job_id: str, lanes: str | None = None, acct: Account = Depends(auth)) -> FileResponse:
    """The sliced G-code itself (SL-10). `lanes` = the slot mapping as JSON ({"1": 3, …}, like /send): the
    tool numbers are rewritten on a copy - in the cloud the app sends this file to the printer itself."""
    job, gcode = _job_gcode(acct, job_id)
    name = Path((job.get("result") or {}).get("source_file") or gcode.stem).stem + ".gcode"
    if lanes:
        try:
            tools = lane_map.parse_mapping(json.loads(lanes))
        except (ValueError, TypeError, AttributeError) as e:
            raise HTTPException(400, f"lanes: {e}")
        if tools:
            out = Path(acct.settings.work_dir) / "lanes" / job_id / uuid.uuid4().hex[:8]
            gcode = await asyncio.to_thread(lane_map.remap_tools, gcode, tools, out)
            _spawn(_remove_later(out.parent, 600))
    return FileResponse(gcode, media_type="text/x.gcode", filename=name)


async def _remove_later(path: Path, delay_s: float) -> None:
    await asyncio.sleep(delay_s)
    shutil.rmtree(path, ignore_errors=True)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    job = _own_job(acct, job_id)
    if job["state"] in ("slicing", "sending", "running"):
        raise HTTPException(409, "job is still running")
    JOBS.pop(job_id)
    if job.get("kind") == "prepare" and job.get("printer"):
        shutil.rmtree(Path(acct.settings.gcode_dir) / job["printer"] / job_id, ignore_errors=True)
    return {"deleted": job_id}


# ---------- one-shot (kept for the CLI docs and iOS Shortcuts) ----------
class PrintRequest(BaseModel):
    link: str
    printer: str | None = None
    file: str | None = None
    start: bool = True


@app.post("/api/print")
async def print_(req: PrintRequest, acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    source = _resolve_link(acct, req.link)
    job = _new_job("oneshot", "running", req.model_dump(), owner=acct.id)

    async def worker() -> None:
        try:
            res = await run_job(acct.settings, source, req.printer, req.file, send=True, start=req.start,
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
