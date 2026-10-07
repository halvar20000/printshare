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
  GET|PUT|DELETE /api/failure-detection/config · /api/printers/{id}/watch/frame|mute   AI failure detection (0.23.0, own servers)
  POST /api/bridge/pair/start|poll · POST /api/bridges/pair · GET|PATCH|DELETE /api/bridges · WS /api/bridge/ws   bridges (0.24.0, cloud)
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
import base64
import contextlib
import dataclasses
import html as htmllib
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .cloud import accounts
from .cloud.spools import Spools
from .cloud.bridges import Bridges
from .cloud.bookings import Bookings
from .cloud.upload_keys import UploadKeys
from . import gcode_info
from . import filament as filament_mod
from . import spooltags as spooltags_mod
from . import spool_source
from .jobstore import JobStore, job_dir
from . import jobtrack
from .timelapse import FILE_NAME as TIMELAPSE_FILE, TimelapseRecorder
from .cloud.hub import BridgeError, BridgeHub
from .bridge.client import BridgeClient, default_name as bridge_default_name
from .bridge.dispatch import dispatch as bridge_dispatch
from . import orca_cloud
from . import filament_db
from . import manyfold as mf
from . import failure_watch as fw
from .cloud.mail import BrevoMailer, LogMailer, Mailer, MailError
from .config import BRIM_TYPES, INFILL_PATTERNS, SUPPORT_TYPES, JobOptions, PrinterConfig, Settings, load_settings, printer_from_config
from . import camera as cam
from . import gcode_preview
from .fetch import SLICEABLE, FetchError, Fetcher
from .pipeline import JobResult, fetch_model, inspect_model, prepare_job, run_job, send_job
from .printers import CONTROL_ACTIONS, LEVELING_TYPES, NEEDS_MACHINE, PRINTER_TYPES, get_adapter
from . import lanes as lane_map
from . import power as plug
from . import user_profiles
from .profiles import ProfileError, ProfileLibrary, load_user_preset
from .search import Search

WEB = Path(__file__).parent / "web"
PLATES = ["Textured PEI Plate", "High Temp Plate", "Cool Plate", "Engineering Plate", "Supertack Plate"]
MAX_JOBS = 50                 # per account (cloud) / per server (home)
JOB_MAX_AGE_DAYS = 14         # older jobs and their G-code are deleted (BE-05)
JOB_SYNC_S = 2
MAX_UPLOAD = 300 * 1024 * 1024
UPLOAD_PREFIX = "upload:"

settings = load_settings()
@contextlib.asynccontextmanager
async def _lifespan(_app):
    if not settings.cloud:
        WATCHER.start()            # AI failure detection (0.23.0); idles until it is set up
        BRIDGE_CLIENT.start()      # bridge mode (0.25.0); idles until it is switched on
        TIMELAPSE.start_loop()     # time-lapse recordings (0.32.0)
        _spawn(_jobs_track_loop()) # started jobs → finished / cancelled (0.33.0)
    else:
        _spawn(_bookings_loop())   # spool bookings of bridge printers (0.29.0), checked by the cloud itself
    _spawn(_jobs_loop())           # jobs survive restarts (0.30.0)
    yield
    await BRIDGE_CLIENT.stop()
    await asyncio.to_thread(JOB_STORE.sync, JOBS)


app = FastAPI(title="PocketPrint3D", version="0.41.0", lifespan=_lifespan)
BRIDGE_CLIENT = BridgeClient(lambda: settings, bridge_dispatch, app.version)
app.add_middleware(GZipMiddleware, minimum_size=2000)  # layer previews are large but compress well
app.mount("/static", StaticFiles(directory=WEB), name="static")
JOBS: dict[str, dict[str, Any]] = {}
# jobs survive restarts (every cloud update restarts the server): mirrored into SQLite next to the account database
# (cloud) or in the work folder (home server)
JOB_STORE = JobStore(Path(settings.cloud_db).parent / "jobs.db" if settings.cloud else Path(settings.work_dir) / "jobs.db",
                     keep_per_owner=MAX_JOBS, max_age_days=JOB_MAX_AGE_DAYS)
JOBS.update(JOB_STORE.load())
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
BRIDGES: Bridges | None = None
BOOKINGS: Bookings | None = None
UPLOAD_KEYS: UploadKeys | None = None
HUB = BridgeHub()


def _cloud_setup() -> None:
    global ACCOUNTS, MAILER, SPOOLS, BRIDGES, BOOKINGS, UPLOAD_KEYS
    if not settings.cloud:
        ACCOUNTS = MAILER = SPOOLS = BRIDGES = BOOKINGS = UPLOAD_KEYS = None
        return
    ACCOUNTS = accounts.Accounts(settings.cloud_db)
    SPOOLS = Spools(ACCOUNTS)
    BRIDGES = Bridges(ACCOUNTS)
    BOOKINGS = Bookings(ACCOUNTS, SPOOLS)
    UPLOAD_KEYS = UploadKeys(ACCOUNTS)
    HUB.on_seen = BRIDGES.seen
    HUB.on_printers = lambda *a: _sync_bridge_printers(*a)       # defined further down
    HUB.listeners[:] = [lambda *a: _bridge_event(*a)]
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


SESSION_COOKIE = "pp3d_session"
SESSION_COOKIE_DAYS = 180
CSRF_HEADER = ("x-requested-with", "pocketprint3d")


def _token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header.removeprefix("Bearer ").strip() or request.query_params.get("token", "")


def auth(request: Request) -> Account:
    token = _token(request)
    if not token and settings.cloud:
        # the web app (docs/WEB.md): session in an HttpOnly cookie that page scripts can't read. SameSite=Strict keeps
        # other sites from using it; changes additionally need a header that a plain form or link can't send.
        token = request.cookies.get(SESSION_COOKIE, "")
        if token and request.method not in ("GET", "HEAD", "OPTIONS") \
                and request.headers.get(CSRF_HEADER[0]) != CSRF_HEADER[1]:
            raise HTTPException(403, "request not allowed from this page")
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


def _via_bridge(acct: "Account", printer_id: str) -> tuple[str, str] | None:
    """Cloud: (bridge id, printer id on the bridge) when the printer sits behind one of the account's bridges."""
    if not acct.cloud:
        return None
    p = _printer(acct, printer_id)
    return (p.bridge, p.remote or p.id) if p.bridge else None


async def _forward(acct: "Account", printer_id: str, method: str, **params: Any) -> Any:
    bridge_id, remote = _via_bridge(acct, printer_id)
    return await bridge_call(acct, bridge_id, method, {"printer": remote, **params})


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
    # at most MAX_JOBS per account and none older than JOB_MAX_AGE_DAYS - with their G-code (BE-05)
    JOB_STORE.prune(JOBS)
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
    cookie: bool = False            # web app: keep the session in an HttpOnly cookie instead of returning it


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_COOKIE_DAYS * 86400, path="/", secure=True,
                        httponly=True, samesite="strict")


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
async def auth_login(req: LoginRequest, response: Response) -> dict[str, Any]:
    """Step 2: the code from the e-mail -> a session token for this device (send it as `Authorization: Bearer`).
    With `cookie: true` (web app) the session goes into an HttpOnly cookie and `token` is null."""
    db = _cloud_only()
    try:
        user, token = await asyncio.to_thread(db.verify_code, req.email, req.code, req.device)
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e))
    if req.cookie:
        _set_session_cookie(response, token)
        return {"token": None, "user": {"id": user.id, "email": user.email}}
    return {"token": token, "user": {"id": user.id, "email": user.email}}


@app.get("/api/auth/me")
def auth_me(acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud:
        raise HTTPException(404, "not logged in with an account")
    return {"id": acct.user.id, "email": acct.user.email, "printers": len(acct.settings.printers),
            "limits": {"slices_per_day": settings.limit_slices_per_day,
                       "slices_today": ACCOUNTS.usage_today(acct.id), "upload_mb": settings.limit_upload_mb}}


@app.post("/api/auth/logout")
def auth_logout(response: Response, acct: Account = Depends(auth)) -> dict[str, Any]:
    if acct.cloud:
        ACCOUNTS.logout(acct.token)
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return {"ok": True}


@app.delete("/api/auth/account")
async def auth_delete_account(response: Response, confirm: bool = False, acct: Account = Depends(auth)) -> dict[str, Any]:
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
    bridge_ids = [b["id"] for b in BRIDGES.list(acct.id)]
    ACCOUNTS.delete_user(acct.id)
    _tags().forget_owner(acct.id)
    for bid in bridge_ids:
        await HUB.disconnect(bid, "the account was deleted")
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return {"deleted": True}


@app.get("/api/admin/stats")
def admin_stats(acct: Account = Depends(auth)) -> dict[str, Any]:
    if acct.id != "admin":
        raise HTTPException(403, "operator only")
    return {**ACCOUNTS.stats(), "spools": SPOOLS.count(), "bridges": BRIDGES.count(), "bridges_online": HUB.count(),
            "jobs": len(JOBS),
            "slicing_now": sum(1 for j in JOBS.values() if j["state"] == "slicing")}


# ---------- bridge mode: this server as a bridge for PocketPrint3D Cloud (docs/BRIDGE.md, 0.25.0) ----------
class BridgeSwitch(BaseModel):
    enabled: bool


def _bridge_home(acct: Account) -> None:
    if settings.cloud or acct.cloud or acct.id == "admin":
        raise HTTPException(404, "bridge mode is for home servers")


@app.get("/api/bridge")
def bridge_state(acct: Account = Depends(auth)) -> dict[str, Any]:
    """Bridge mode of this home server: on/off, pairing code to enter in the app, connection, paired account."""
    _bridge_home(acct)
    return BRIDGE_CLIENT.public()


@app.post("/api/bridge")
def bridge_switch(req: BridgeSwitch, acct: Account = Depends(auth)) -> dict[str, Any]:
    _bridge_home(acct)
    BRIDGE_CLIENT.set_enabled(req.enabled)
    return BRIDGE_CLIENT.public()


@app.post("/api/bridge/reset")
def bridge_reset(acct: Account = Depends(auth)) -> dict[str, Any]:
    """Forget the pairing (e.g. to connect another account): a new code is shown."""
    _bridge_home(acct)
    BRIDGE_CLIENT.forget()
    return BRIDGE_CLIENT.public()


# ---------- ready-made bridge (Raspberry Pi image, bridge container): found and paired from the app on the Wi-Fi ----------
def _mask_email(email: str | None) -> str | None:
    """"thomas@example.org" → "t***@example.org": enough to recognise one's own account, not to read someone else's."""
    if not email or "@" not in email:
        return None
    user, domain = email.split("@", 1)
    return f"{user[:1]}***@{domain}"


def _local_pairing(request: Request) -> bool:
    """The pairing code is handed out without a token only by a bridge-only install, only to the home network, and only
    when the page was opened by the bridge's own address - an IP address, localhost, <name>.local or its host name. That
    keeps out other websites (DNS rebinding: evil.example pointing at the bridge) and anyone behind a reverse proxy."""
    if settings.cloud or not settings.bridge_only:
        return False
    if any(h in request.headers for h in ("x-forwarded-for", "forwarded", "x-real-ip")):
        return False
    try:
        peer = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError:
        return False
    if not (peer.is_private or peer.is_loopback or peer.is_link_local):
        return False
    host = urlsplit("//" + request.headers.get("host", "")).hostname or ""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    host = host.lower().rstrip(".")
    own = socket.gethostname().lower()
    return host in ("localhost", own) or host.endswith(".local")


def _pairable() -> bool:
    st = BRIDGE_CLIENT.public()
    return bool(st["enabled"] and st["state"] == "pairing" and st["code"] and not st["paired"])


@app.get("/api/bridge/hello")
def bridge_hello() -> dict[str, Any]:
    """No token: lets the app recognise a PocketPrint3D bridge on the Wi-Fi (and whether it still needs an account)."""
    if settings.cloud:
        raise HTTPException(404, "not a bridge")
    st = BRIDGE_CLIENT.public()
    return {"pocketprint3d": "bridge" if st["enabled"] else "server", "version": app.version,
            "name": bridge_default_name(), "bridge_id": st["bridge_id"], "state": st["state"],
            "paired": st["paired"], "account": _mask_email(st["account"]), "bridge_only": settings.bridge_only,
            "pairable": settings.bridge_only and _pairable()}


@app.get("/api/bridge/local-code")
def bridge_local_code(request: Request) -> dict[str, Any]:
    """The pairing code for the app on the same Wi-Fi ("Connect" on a found bridge) - see _local_pairing."""
    if not _local_pairing(request):
        raise HTTPException(403, "only from the home network, on a PocketPrint3D bridge")
    if not _pairable():
        raise HTTPException(409, "the bridge is not waiting for an account")
    st = BRIDGE_CLIENT.public()
    return {"code": st["code"], "expires_in": st["code_expires_in"], "name": bridge_default_name()}


_BRIDGE_TEXT = {
    "de": {"title": "PocketPrint3D-Brücke", "connected": "Verbunden mit dem Konto {account}. Alles fertig.",
           "pair": "Öffne die PocketPrint3D-App im selben WLAN: Einstellungen → Erweitert → Unterwegs drucken. "
                   "Die Brücke erscheint unter „Im WLAN gefunden“ - tippe auf „Verbinden“. Oder gib diesen Code ein:",
           "valid": "Gültig für {min} Minuten - danach erscheint hier ein neuer.",
           "wait": "Die Brücke startet ({state}) … diese Seite lädt sich selbst neu.",
           "remote": "Den Kopplungscode zeigt diese Seite nur im Heimnetz, wenn sie über die Adresse der Brücke "
                     "geöffnet wurde (z. B. http://pocketprint3d.local).",
           "off": "Die Verbindung zu PocketPrint3D Cloud ist ausgeschaltet.",
           "foot": "Diese Seite ist nur in deinem Heimnetz erreichbar. Die Brücke baut nur ausgehende Verbindungen auf."},
    "en": {"title": "PocketPrint3D bridge", "connected": "Connected to the account {account}. All set.",
           "pair": "Open the PocketPrint3D app on the same Wi-Fi: Settings → Advanced → Print from anywhere. The bridge "
                   "shows up under “Found on your Wi-Fi” - tap “Connect”. Or enter this code:",
           "valid": "Valid for {min} minutes - a new one appears here afterwards.",
           "wait": "The bridge is starting ({state}) … this page reloads by itself.",
           "remote": "This page shows the pairing code only on the home network, opened by the bridge's address "
                     "(e.g. http://pocketprint3d.local).",
           "off": "The connection to PocketPrint3D Cloud is switched off.",
           "foot": "This page is only reachable on your home network. The bridge only makes outgoing connections."},
}


@app.get("/bridge", response_class=HTMLResponse)
def bridge_page(request: Request) -> HTMLResponse:
    """Status page of a bridge (the Raspberry Pi image shows it at http://pocketprint3d.local): connected, or the code."""
    if settings.cloud:
        raise HTTPException(404, "not a bridge")
    lang = "de" if request.headers.get("accept-language", "").lower().startswith("de") else "en"
    tx = _BRIDGE_TEXT[lang]
    st = BRIDGE_CLIENT.public()
    esc = htmllib.escape
    if not st["enabled"]:
        body = f"<p>{esc(tx['off'])}</p>"
    elif st["state"] == "connected":
        body = f'<p class="ok">✓ {esc(tx["connected"].format(account=_mask_email(st["account"]) or "?"))}</p>'
    elif _pairable() and _local_pairing(request):
        minutes = max(1, round((st["code_expires_in"] or 0) / 60))
        body = (f"<p>{esc(tx['pair'])}</p><p class=\"code\">{esc(st['code'])}</p>"
                f"<p class=\"sub\">{esc(tx['valid'].format(min=minutes))}</p>")
    elif _pairable():
        body = f"<p>{esc(tx['remote'])}</p>"
    else:
        body = f"<p>{esc(tx['wait'].format(state=st['state']))}</p>"
        if st["error"]:
            body += f'<p class="sub">{esc(str(st["error"]))}</p>'
    page = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="10">
<title>{esc(tx['title'])}</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--text:#16181d;--sub:#5b6270;--accent:#ff6a13;--ok:#1a7f37}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111318;--card:#1b1e25;--text:#eceef2;--sub:#9aa1ad;--ok:#3fb950}}}}
body{{margin:0;background:var(--bg);color:var(--text);font:17px/1.5 system-ui,-apple-system,sans-serif}}
main{{max-width:560px;margin:40px auto;padding:0 16px}} .card{{background:var(--card);border-radius:16px;padding:24px}}
h1{{font-size:22px;margin:0 0 4px}} .name{{color:var(--sub);margin:0 0 16px}} .sub{{color:var(--sub);font-size:15px}}
.code{{font-size:40px;font-weight:700;letter-spacing:6px;text-align:center;color:var(--accent);margin:20px 0 8px}}
.ok{{color:var(--ok);font-weight:600}} footer{{color:var(--sub);font-size:13px;margin-top:16px}}
</style></head><body><main><div class="card"><h1>{esc(tx['title'])}</h1>
<p class="name">{esc(bridge_default_name())} · {esc(app.version)}</p>{body}</div>
<footer>{esc(tx['foot'])}</footer></main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                                       "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


# ---------- cloud: spool bookings in the account (docs/WEB.md step 2, 0.29.0) ----------
BOOKINGS_CHECK_S = 60


def _bookings() -> Bookings:
    if not settings.cloud or BOOKINGS is None:
        raise HTTPException(404, "bookings exist only in PocketPrint3D Cloud")
    return BOOKINGS


def _bookings_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e))


class BookingUse(BaseModel):
    spool: int
    grams: float
    label: str | None = None


class BookingCreate(BaseModel):
    printer: str
    file: str                          # the file name on the printer (compared with what the printer reports)
    uses: list[BookingUse]
    printer_name: str | None = None
    job: str | None = None


class BookingObserve(BaseModel):
    statuses: dict[str, dict[str, Any] | None]    # printer id → its status (as from /status), null = not reachable


class BookingResolve(BaseModel):
    part: float = Field(ge=0, le=1)


@app.get("/api/bookings")
def bookings_list(acct: Account = Depends(auth)) -> dict[str, Any]:
    """Spool bookings of the account: waiting (print not finished), open (the user decides), booked (recently)."""
    if not acct.cloud:
        raise HTTPException(404, "bookings exist only in PocketPrint3D Cloud")
    return _bookings().list(acct.id)


@app.post("/api/bookings")
def bookings_create(req: BookingCreate, acct: Account = Depends(auth)) -> dict[str, Any]:
    """A print started with spools of the account: book them when it is finished."""
    if not acct.cloud:
        raise HTTPException(404, "bookings exist only in PocketPrint3D Cloud")
    _printer(acct, req.printer)
    b = _bookings_call(_bookings().create, acct.id, req.printer, req.file, [u.model_dump() for u in req.uses],
                       req.printer_name, req.job)
    return {"booking": b}


@app.post("/api/bookings/observe")
def bookings_observe(req: BookingObserve, acct: Account = Depends(auth)) -> dict[str, Any]:
    """The app reports printer statuses it saw (printers on its Wi-Fi); finished prints are booked. Answers the list."""
    if not acct.cloud:
        raise HTTPException(404, "bookings exist only in PocketPrint3D Cloud")
    db = _bookings()
    known = {p.id for p in acct.settings.printers}
    booked = []
    for pid, st in list(req.statuses.items())[:50]:
        if pid in known:
            st = st if isinstance(st, dict) else None
            booked += _bookings_call(db.observe, acct.id, pid, st)
            _track_jobs(acct.id, pid, st)
    return {**db.list(acct.id), "booked_now": booked}


@app.post("/api/observe")
def observe(req: BookingObserve, acct: Account = Depends(auth)) -> dict[str, Any]:
    """The app reports the statuses of printers it reaches on its Wi-Fi (cloud): started jobs learn that they finished,
    spool bookings in the account are settled. Same as /api/bookings/observe."""
    return bookings_observe(req, acct)


@app.post("/api/bookings/{booking_id}/resolve")
def bookings_resolve(booking_id: str, req: BookingResolve, acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud:
        raise HTTPException(404, "bookings exist only in PocketPrint3D Cloud")
    return {"booking": _bookings_call(_bookings().resolve, acct.id, booking_id, req.part)}


@app.delete("/api/bookings/{booking_id}")
def bookings_delete(booking_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud or not _bookings().delete(acct.id, booking_id):
        raise HTTPException(404, "unknown booking")
    return {"deleted": booking_id}


def _track_jobs(owner: str, printer_id: str, status: dict[str, Any] | None) -> None:
    """Started jobs of this printer learn from its status that they finished or were cancelled (0.33.0); a print
    started elsewhere (OrcaSlicer straight to the printer …) becomes a job of its own (0.40.0)."""
    kind = printer_kind(status.get("state")) if status else None
    mine = [j for j in list(JOBS.values()) if j.get("owner", "local") == owner
            and (j.get("printer") or (j.get("result") or {}).get("printer")) == printer_id]
    for job in mine:
        if job.get("state") in jobtrack.TRACKED:
            jobtrack.track(job, status, kind)
    ext = jobtrack.external(mine, printer_id, status, kind)
    if ext is not None:
        job = _new_job(jobtrack.EXTERNAL, "started", ext.pop("request"), owner=owner)
        job.update(ext)
        job["log"].append("Started on the printer, not through PocketPrint3D")
        if not settings.cloud and owner == "local" and _timelapse_wanted(None):
            _spawn(_external_timelapse(job))


async def _external_timelapse(job: dict[str, Any]) -> None:
    """Time-lapse of a print started elsewhere ("always" setting) - only where the printer has a camera."""
    printer_id = job["printer"]
    if TIMELAPSE.active.get(printer_id) is not None:
        return
    try:
        await _camera(Account("local", settings), printer_id)
    except HTTPException:
        return
    out = Path(settings.gcode_dir) / printer_id / job["id"]
    rec = TIMELAPSE.start(printer_id, job["id"], job["printer_file"], out)
    rec.seen_active = True
    job["timelapse"] = {"state": rec.state, "frames": 0}


def _bridge_printers() -> set[tuple[str, str]]:
    """Every printer behind a bridge that is online now (prints started elsewhere show up as jobs, 0.40.0)."""
    if ACCOUNTS is None:
        return set()
    out = set()
    for conn in list(HUB.conns.values()):
        for row in ACCOUNTS.printers(conn.user_id):
            if row.get("bridge") == conn.bridge_id and row.get("id"):
                out.add((conn.user_id, row["id"]))
    return out


def _started_printers() -> set[tuple[str, str]]:
    return {(j.get("owner", "local"), j.get("printer") or (j.get("result") or {}).get("printer"))
            for j in list(JOBS.values()) if j.get("state") in jobtrack.TRACKED}


async def _check_bridge_bookings() -> None:
    """Printers behind a bridge with waiting bookings or started jobs: ask the bridge for the status (nobody has to have
    the app open)."""
    if BOOKINGS is None:
        return
    for user_id, printer_id in sorted(set(BOOKINGS.waiting_printers()) | _started_printers() | _bridge_printers()):
        row = next((p for p in ACCOUNTS.printers(user_id) if p.get("id") == printer_id), None)
        if not row or not row.get("bridge"):
            continue                       # reached by the phone: it reports the status itself
        if not HUB.online(row["bridge"]):
            status = None                   # judged as "not reachable" (only matters after 3 days)
        else:
            try:
                st = await HUB.call(row["bridge"], user_id, "printer.status", {"printer": row.get("remote") or printer_id})
                status = st if isinstance(st, dict) else None
            except BridgeError as e:
                if e.code not in ("offline", "bridge_offline", "unknown_printer"):
                    continue                # busy / timeout: try again next round
                status = None
        _track_jobs(user_id, printer_id, status)
        try:
            await asyncio.to_thread(BOOKINGS.observe, user_id, printer_id, status)
        except accounts.AccountError:
            continue


async def _bookings_loop() -> None:
    while True:
        await asyncio.sleep(BOOKINGS_CHECK_S)
        try:
            await _check_bridge_bookings()
        except Exception:  # noqa: BLE001 - never stop checking
            import logging
            logging.getLogger(__name__).exception("bookings check")


# ---------- cloud: send from OrcaSlicer (docs/WEB.md step 3, 0.31.0) ----------
# OrcaSlicer's physical printer "Octo/Klipper" → https://api.pocketprint3d.com/octoprint with X-Api-Key = the printer's key.
# The G-code becomes a job of the account ("ready to print": spools, slots, confirmation in the app). "Upload and Print"
# starts it right away on printers behind a bridge (the user confirmed in OrcaSlicer) and books the spool used last.
OCTO_VERSION = {"api": "0.1", "server": "1.10.0", "text": "OctoPrint 1.10.0 (PocketPrint3D)"}
GCODE_SUFFIXES = (".gcode", ".gco", ".g")


def _upload_keys() -> UploadKeys:
    if not settings.cloud or UPLOAD_KEYS is None:
        raise HTTPException(404, "sending from OrcaSlicer works with PocketPrint3D Cloud")
    return UPLOAD_KEYS


def _public_url(request: Request) -> str:
    from . import bootstrap
    return (bootstrap.server_url() or str(request.base_url)).rstrip("/")


@app.get("/api/printers/{printer_id}/orca-upload")
def orca_upload_state(printer_id: str, request: Request, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Is sending from OrcaSlicer set up for this printer? (The key itself is only shown when it is created.)"""
    if not acct.cloud:
        raise HTTPException(404, "sending from OrcaSlicer works with PocketPrint3D Cloud")
    _printer(acct, printer_id)
    info = _upload_keys().info(acct.id, printer_id)
    return {"enabled": info is not None, "url": _public_url(request) + "/octoprint", **(info or {})}


@app.post("/api/printers/{printer_id}/orca-upload")
def orca_upload_create(printer_id: str, request: Request, acct: Account = Depends(auth)) -> dict[str, Any]:
    """A new key for OrcaSlicer (shown once; an older key of this printer stops working)."""
    if not acct.cloud:
        raise HTTPException(404, "sending from OrcaSlicer works with PocketPrint3D Cloud")
    _printer(acct, printer_id)
    key = _upload_keys().create(acct.id, printer_id)
    return {"enabled": True, "url": _public_url(request) + "/octoprint", "key": key}


@app.delete("/api/printers/{printer_id}/orca-upload")
def orca_upload_delete(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud:
        raise HTTPException(404, "sending from OrcaSlicer works with PocketPrint3D Cloud")
    return {"deleted": _upload_keys().delete(acct.id, printer_id)}


def _octo_auth(request: Request) -> tuple[Account, PrinterConfig]:
    key = request.headers.get("x-api-key") or request.query_params.get("apikey") or ""
    found = _upload_keys().resolve(key) if key else None
    user = ACCOUNTS.user(found[0]) if found else None
    if user is None:
        raise HTTPException(403, "Invalid API key - create one in the PocketPrint3D app (printer → Send from OrcaSlicer)")
    acct = _user_account(user, "")
    try:
        return acct, acct.settings.printer(found[1])
    except KeyError:
        raise HTTPException(403, "this key's printer no longer exists - create a new key in the app")


@app.get("/octoprint/api/version")
def octoprint_version(request: Request) -> dict[str, Any]:
    """OrcaSlicer's "Test" button."""
    _octo_auth(request)
    return OCTO_VERSION


def _gcode_result(printer: PrinterConfig, name: str, path: Path) -> JobResult:
    from .slicer import _parse_estimates, filament_grams
    print_time, grams, meters, layers = _parse_estimates(path)
    info = gcode_info.orca_settings(path)
    per = filament_grams(path)
    fils = info.get("filaments") or []
    colours = info.get("colours") or []
    filaments = [{"index": i + 1, "color": colours[i] if i < len(colours) else None, "preset": fils[i] if i < len(fils) else "",
                  "grams": per[i] if i < len(per) else None} for i in range(max(len(per), len(fils)))] if len(per) > 1 else []
    profiles = {"machine": info.get("printer") or "OrcaSlicer", "process": info.get("process") or "",
                "filament": fils[0] if fils else "", "bed_type": ""}
    return JobResult(printer.id, name, str(path), print_time, grams, meters, layers, profiles, {}, filaments=filaments)


async def _orca_print(acct: Account, job: dict[str, Any]) -> None:
    """"Upload and Print" on a printer behind a bridge: send and start, then book the spool used last on it."""
    try:
        await send(job["id"], SendRequest(start=True, confirm=True), acct)
    except HTTPException as e:
        job["log"].append(f"Not started: {e.detail}")
        return
    for _ in range(15 * 60):
        if job["state"] != "sending":
            break
        await asyncio.sleep(1)
    if job["state"] != "started" or BOOKINGS is None:
        return
    grams = [f["grams"] for f in (job["result"].get("filaments") or [])] or [job["result"].get("filament_g")]
    last = BOOKINGS.last_spool(acct.id, job["printer"])
    if last is None or len(grams) != 1 or not grams[0]:
        job["log"].append("No spool booked - choose it in the app next time (single colour, cloud spools)")
        return
    try:
        BOOKINGS.create(acct.id, job["printer"], job.get("printer_file") or Path(job["result"]["gcode"]).name,
                        [{"spool": last["spool"], "grams": grams[0], "label": last.get("label") or ""}],
                        printer_name=_printer(acct, job["printer"]).name, job=job["id"])
        job["log"].append(f"Spool booked when finished: {last.get('label') or '#' + str(last['spool'])}")
    except accounts.AccountError as e:
        job["log"].append(f"No spool booked: {e}")


@app.post("/octoprint/api/files/local", status_code=201)
async def octoprint_upload(request: Request) -> dict[str, Any]:
    """OrcaSlicer "Upload" / "Upload and Print": multipart `file` (+ `print`, `select`, `path`)."""
    acct, printer = _octo_auth(request)
    limit = settings.limit_upload_mb * 1024 * 1024
    if int(request.headers.get("content-length") or 0) > limit + 1_000_000:
        raise HTTPException(413, f"the G-code is larger than {settings.limit_upload_mb} MB")
    form = await request.form(max_files=1, max_fields=10)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(400, "no file in the upload")
    name = re.sub(r"[^\w.\- ()]+", "_", Path(upload.filename or "print.gcode").name).strip(" .")[:120] or "print.gcode"
    if not name.lower().endswith(GCODE_SUFFIXES):
        raise HTTPException(415, "only G-code (.gcode) can be sent - binary G-code (.bgcode) and 3MF are not supported")
    start = str(form.get("print") or "").lower() == "true"
    job = _new_job("prepare", "uploading", {"link": f"orcaslicer:{name}", "printer": printer.id, "file": None,
                                            "source": "orcaslicer"}, owner=acct.id)
    job["printer"] = printer.id
    dest = Path(acct.settings.gcode_dir) / printer.id / job["id"] / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with dest.open("wb") as fh:
            while chunk := await upload.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"the G-code is larger than {settings.limit_upload_mb} MB")
                fh.write(chunk)
        result = await asyncio.to_thread(_gcode_result, printer, name, dest)
    except HTTPException:
        JOBS.pop(job["id"], None)
        shutil.rmtree(dest.parent, ignore_errors=True)
        raise
    job.update(state="sliced", result=result.as_dict())
    job["log"].append("Received from OrcaSlicer")
    sliced_for = result.profiles.get("machine")
    if printer.slicing.machine and sliced_for not in ("OrcaSlicer", printer.slicing.machine):
        job["log"].append(f"Sliced for {sliced_for}, this printer is set to {printer.slicing.machine}")
    started = bool(start and printer.bridge)
    if start and not printer.bridge:
        job["log"].append("Start it in the app (this printer is reached by your phone on the Wi-Fi)")
    if started:
        _spawn(_orca_print(acct, job))
    return {"done": True, "effectiveSelect": False, "effectivePrint": started,
            "files": {"local": {"name": name, "path": name, "origin": "local",
                                "refs": {"resource": f"{_public_url(request)}/api/jobs/{job['id']}"}}}}


# ---------- cloud mode: bridges at home (docs/BRIDGE.md) ----------
def _bridges() -> Bridges:
    if not settings.cloud or BRIDGES is None:
        raise HTTPException(404, "bridges exist only in PocketPrint3D Cloud")
    return BRIDGES


def _bridge_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e))


def _bridge_out(b: dict[str, Any]) -> dict[str, Any]:
    live = HUB.info(b["id"])
    return {**{k: b[k] for k in ("id", "name", "version", "public_key", "created", "last_seen")},
            "online": live["online"], "printers": live["printers"], "connected": live["connected"]}


class BridgePairStart(BaseModel):
    bridge_id: str
    public_key: str | None = None      # X25519, base64 - the apps seal printer secrets with it
    version: str | None = None
    name: str | None = None            # suggestion, e.g. the host name; the user can change it


class BridgePairPoll(BaseModel):
    bridge_id: str
    poll: str


class BridgePair(BaseModel):
    code: str
    name: str | None = None


class BridgeRename(BaseModel):
    name: str


@app.post("/api/bridge/pair/start")
def bridge_pair_start(req: BridgePairStart, request: Request) -> dict[str, Any]:
    """Bridge (no login yet): get a pairing code to show at home."""
    return _bridge_call(_bridges().start_pairing, req.bridge_id, req.public_key, req.version, req.name,
                        _client_ip(request))


@app.post("/api/bridge/pair/poll")
def bridge_pair_poll(req: BridgePairPoll) -> dict[str, Any]:
    """Bridge: {"status": "waiting"} until the user entered the code, then once {"status": "paired", "token"}."""
    return _bridge_call(_bridges().poll_pairing, req.bridge_id, req.poll)


@app.post("/api/bridges/pair")
def bridges_pair(req: BridgePair, acct: Account = Depends(auth)) -> dict[str, Any]:
    """App: the code shown by the bridge → the bridge belongs to this account."""
    if not acct.cloud:
        raise HTTPException(404, "bridges exist only in PocketPrint3D Cloud")
    b = _bridge_call(_bridges().confirm_pairing, acct.id, req.code, req.name)
    ACCOUNTS.delete_bridge_printers(b["id"], keep_user=acct.id)     # it may have belonged to another account
    return _bridge_out(b)


@app.get("/api/bridges")
def bridges_list(acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    if not acct.cloud:
        return []
    return [_bridge_out(b) for b in _bridges().list(acct.id)]


@app.patch("/api/bridges/{bridge_id}")
def bridges_rename(bridge_id: str, req: BridgeRename, acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud:
        raise HTTPException(404, "unknown bridge")
    return _bridge_out(_bridge_call(_bridges().rename, acct.id, bridge_id, req.name))


@app.delete("/api/bridges/{bridge_id}")
async def bridges_delete(bridge_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Remove a bridge: its token stops working and its connection is closed."""
    if not acct.cloud or not _bridges().delete(acct.id, bridge_id):
        raise HTTPException(404, "unknown bridge")
    await HUB.disconnect(bridge_id)
    ACCOUNTS.delete_bridge_printers(bridge_id)
    return {"deleted": bridge_id}


def _bridge_from_request(token: str) -> dict[str, Any]:
    bridge = _bridges().for_token(token) if token else None
    if bridge is None:
        raise HTTPException(401, "unknown bridge token - pair the bridge again")
    return bridge


@app.websocket("/api/bridge/ws")
async def bridge_socket(ws: WebSocket) -> None:
    """The bridge's own connection (opened by the bridge; Authorization: Bearer <bridge token>)."""
    header = ws.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    bridge = BRIDGES.for_token(token) if (settings.cloud and BRIDGES is not None and token) else None
    await ws.accept()
    if bridge is None:           # accepted first, so the bridge sees the reason (4401 = pair again)
        await ws.close(4401, "unknown bridge token - pair the bridge again")
        return
    await HUB.serve(ws, bridge)


@app.get("/api/bridge/jobs/{job_id}/gcode")
async def bridge_gcode(job_id: str, request: Request, lanes: str | None = None) -> FileResponse:
    """A bridge fetches the G-code of a job of its own account (job.send)."""
    bridge = _bridge_from_request(_token(request))
    user = ACCOUNTS.user(bridge["user_id"])
    if user is None:
        raise HTTPException(401, "unknown bridge token - pair the bridge again")
    return await download_gcode(job_id, lanes, _user_account(user, ""))


def _sync_bridge_printers(bridge_id: str, user_id: str, printers: list[dict[str, Any]]) -> None:
    """The bridge's printers become printers of the account (kept while the bridge is offline, so jobs and profiles stay).
    Name, type and slicing model come from the bridge; a name the user changed in the app stays."""
    rows = ACCOUNTS.printers(user_id)
    mine = {r.get("remote"): r for r in rows if r.get("bridge") == bridge_id}
    taken = {r["id"] for r in rows if r.get("bridge") != bridge_id}
    seen = set()
    for p in printers[:50]:
        rid = p["id"]
        caps = p.get("capabilities") if isinstance(p.get("capabilities"), dict) else {}
        old = mine.get(rid) or {}
        pid = old.get("id")
        if not pid:
            base = re.sub(r"[^a-z0-9]+", "-", rid.lower()).strip("-")[:24] or "printer"
            pid = base if base not in taken else f"{base}-{bridge_id[:4].lower()}"
        taken.add(pid)
        seen.add(rid)
        sl = dict(old.get("slicing") or {})
        if p.get("machine"):
            sl["machine"] = p["machine"]
        if caps.get("cosmos"):
            sl["machine_preset"] = "cosmos"
        else:
            sl.pop("machine_preset", None)
        cfg = {"id": pid, "type": str(p.get("type") or old.get("type") or "moonraker"),
               "name": old["name"] if old.get("custom_name") else str(p.get("name") or rid)[:60],
               "auto_leveling": caps.get("leveling") if isinstance(caps.get("leveling"), bool) else old.get("auto_leveling", True),
               "slicing": sl, "bridge": bridge_id, "remote": rid, "custom_name": bool(old.get("custom_name"))}
        if cfg != old:
            ACCOUNTS.save_printer(user_id, cfg)
    for rid, old in mine.items():
        if rid not in seen:
            ACCOUNTS.delete_printer(user_id, old["id"])


def _bridge_event(bridge_id: str, user_id: str, event: str, data: dict[str, Any]) -> None:
    """Upload steps of job.send show up in the job's log, like on a home server."""
    if event == "timelapse.state":
        job = JOBS.get(str(data.get("job") or ""))
        if job is not None and job.get("owner") == user_id and data.get("state") in ("recording", "rendering", "failed"):
            job["timelapse"] = {"state": data["state"], "frames": int(data.get("frames") or 0),
                                "error": str(data.get("error") or "")[:200] or None}
        return
    if event == "job.progress":
        job = JOBS.get(str(data.get("job") or ""))
        if job is not None and job.get("owner") == user_id and isinstance(data.get("message"), str):
            job.setdefault("log", []).append(data["message"][:200])


class BridgePrinterAdd(BaseModel):
    printer: dict[str, Any]           # {"name", "type", "machine"?, "cosmos"?} - nothing secret
    sealed: str | None = None         # pp3d-seal-v1 blob of {"address", "password"?, "api_key"?} for this bridge


class BridgeDiscover(BaseModel):
    subnet: str | None = None          # the phone's Wi-Fi, e.g. "192.168.1.0/24" (when it is at home)


@app.post("/api/bridges/{bridge_id}/discover")
async def bridges_discover(bridge_id: str, req: BridgeDiscover | None = None,
                           acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    """Printers the bridge finds on its home network (to add them with one tap)."""
    if not acct.cloud:
        raise HTTPException(404, "unknown bridge")
    _bridge_call(_bridges().get, acct.id, bridge_id)
    from .bridge.discovery import subnet_hint
    hint = subnet_hint(req.subnet) if req and req.subnet else None
    return await bridge_call(acct, bridge_id, "discover", {"subnet": hint} if hint else {})


@app.post("/api/bridges/{bridge_id}/printers")
async def bridges_add_printer(bridge_id: str, req: BridgePrinterAdd, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Add a printer at home through the bridge; it becomes a printer of the account right away."""
    if not acct.cloud:
        raise HTTPException(404, "unknown bridge")
    _bridge_call(_bridges().get, acct.id, bridge_id)
    fields = {k: req.printer[k] for k in ("name", "type", "machine", "cosmos") if k in req.printer}
    added = await bridge_call(acct, bridge_id, "printer.add", {"printer": fields, "sealed": req.sealed})
    _sync_bridge_printers(bridge_id, acct.id, HUB.info(bridge_id)["printers"] or [added])
    row = next((p for p in ACCOUNTS.printers(acct.id) if p.get("bridge") == bridge_id and p.get("remote") == added.get("id")), None)
    if row is None:
        raise HTTPException(502, "the bridge added the printer but didn't report it")
    return _printer_json(_user_account(acct.user, acct.token), row["id"])


class BridgePrinterAccess(BaseModel):
    sealed: str                       # new address / password / key, sealed for the printer's bridge


@app.put("/api/printers/{printer_id}/bridge-access")
async def bridge_printer_access(printer_id: str, req: BridgePrinterAccess, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Change how the bridge reaches a printer it was given by the app (address, password, API key)."""
    if not _via_bridge(acct, printer_id):
        raise HTTPException(409, "this printer is not reached through a bridge")
    await _forward(acct, printer_id, "printer.update", sealed=req.sealed)
    return {"ok": True}


TIMELAPSE_MAX_MB = 300


@app.post("/api/bridge/jobs/{job_id}/timelapse")
async def bridge_timelapse_upload(job_id: str, request: Request) -> dict[str, Any]:
    """A bridge delivers the finished time-lapse of a job of its account."""
    bridge = _bridge_from_request(_token(request))
    job = JOBS.get(job_id)
    if job is None or job.get("owner") != bridge["user_id"]:
        raise HTTPException(404, "unknown job")
    d = job_dir(job)
    if d is None:
        raise HTTPException(409, "this job has no folder for a video")
    d.mkdir(parents=True, exist_ok=True)
    tmp, size = d / (TIMELAPSE_FILE + ".part"), 0
    with tmp.open("wb") as fh:
        async for chunk in request.stream():
            size += len(chunk)
            if size > TIMELAPSE_MAX_MB * 1024 * 1024:
                fh.close()
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, "time-lapse too large")
            fh.write(chunk)
    tmp.replace(d / TIMELAPSE_FILE)
    job["timelapse"] = {"state": "ready", "frames": (job.get("timelapse") or {}).get("frames", 0), "size": size}
    return {"ok": True, "size": size}


async def bridge_call(acct: Account, bridge_id: str, method: str, params: dict[str, Any] | None = None) -> Any:
    """A request to one of the account's bridges; errors become HTTP errors with a clear text."""
    try:
        return await HUB.call(bridge_id, acct.id, method, params)
    except BridgeError as e:
        raise HTTPException(e.status, str(e))


@app.get("/api/machines")
async def machines(acct: Account = Depends(auth)) -> list[dict[str, str]]:
    """OrcaSlicer printer models to choose from (cloud printers of type prusalink/octoprint need one)."""
    return await asyncio.to_thread(lambda: _library().machines())


# ---------- cloud mode: the account's printers (no addresses - the app reaches them at home) ----------
MAX_PRINTERS = 10


class PrinterSettings(BaseModel):
    name: str | None = None
    type: str | None = None             # elegoo_sdcp | moonraker | prusalink | octoprint | bambu_lan
    machine: str | None = None          # OrcaSlicer printer preset; required for Prusa/OctoPrint/Bambu
    cosmos: bool | None = None          # Centauri Carbon with OpenCentauri COSMOS (Klipper)
    auto_leveling: bool | None = None


def _printer_config(pid: str, req: PrinterSettings, old: dict[str, Any] | None = None) -> dict[str, Any]:
    old = old or {}
    name = (req.name if req.name is not None else old.get("name", "")).strip()
    ptype = old.get("type") if old.get("bridge") else (req.type or old.get("type"))
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
    if ptype in NEEDS_MACHINE and not sl.get("machine"):
        raise HTTPException(400, "choose the printer model (OrcaSlicer printer profile) for this printer")
    if sl.get("machine"):
        try:
            _library().resolve("machine", sl["machine"])
        except ProfileError as e:
            raise HTTPException(400, str(e))
    cfg = {"id": pid, "name": name, "type": ptype,
           "auto_leveling": req.auto_leveling if req.auto_leveling is not None else old.get("auto_leveling", True),
           "slicing": sl}
    if old.get("bridge"):                       # a bridge printer stays one (type and link come from the bridge)
        cfg.update(type=old["type"], bridge=old["bridge"], remote=old.get("remote"),
                   custom_name=bool(old.get("custom_name")) or (req.name is not None and req.name.strip() != old.get("name")))
    return cfg


@app.post("/api/printers")
def add_printer(req: PrinterSettings, acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud:
        raise HTTPException(409, "printers are set up in the server's configuration")
    if sum(1 for p in acct.settings.printers if not p.bridge) >= MAX_PRINTERS:
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
async def delete_printer(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    if not acct.cloud:
        raise HTTPException(409, "printers are set up in the server's configuration")
    if _via_bridge(acct, printer_id):
        # only printers added through the app can go; the bridge says so for the others
        await _forward(acct, printer_id, "printer.remove")
        ACCOUNTS.delete_printer(acct.id, printer_id)        # may already be gone through the bridge's printers.changed
        user_profiles.write_overlay(acct.settings.config_dir, printer_id, {})
        return {"deleted": printer_id}
    if not ACCOUNTS.delete_printer(acct.id, printer_id):
        raise HTTPException(404, f"Unknown printer {printer_id!r}")
    if UPLOAD_KEYS is not None:
        UPLOAD_KEYS.delete(acct.id, printer_id)
    _tags().forget_printer(acct.id, printer_id)
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
            "cosmos": p.slicing.machine_preset == "cosmos",
            # docs/BRIDGE.md: reached through a bridge at home (the app uses these endpoints instead of the Wi-Fi)
            "bridge": p.bridge}


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
    if _via_bridge(acct, printer_id):
        return await _forward(acct, printer_id, "printer.status")
    _local_only(acct)
    printer = _printer(acct, printer_id)
    try:
        st = await get_adapter(printer).status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"printer not reachable: {e}")
    _log_temperatures(printer_id, st)
    out = {**st, "kind": printer_kind(st.get("state"))}
    watch_cfg = fw.load_config(settings)
    if watch_cfg.configured:
        out["watch"] = WATCHER.state(printer_id, watch_cfg)     # AI failure detection (0.23.0)
    return out


def _log_temperatures(printer_id: str, st: dict[str, Any]) -> None:
    heaters = st.get("heaters") or {}
    if not heaters:
        return
    log = TEMP_LOG.setdefault(printer_id, deque(maxlen=TEMP_LOG_SECONDS // 4))
    now = time.time()
    if log and now - log[-1][0] < 4:
        return
    log.append((now, {h: (v.get("actual"), v.get("target")) for h, v in heaters.items() if v.get("actual") is not None}))


# ---------- time-lapse (0.32.0, own servers and bridges) ----------
async def _tl_status(printer_id: str) -> dict[str, Any] | None:
    try:
        return await get_adapter(settings.printer(printer_id)).status()
    except Exception:  # noqa: BLE001
        return None


async def _tl_snapshot(printer_id: str) -> bytes:
    source = await _camera(Account("local", settings), printer_id)
    jpeg = await cam.snapshot(source)
    return await asyncio.to_thread(cam.scale, jpeg, 1280, 82)


async def _tl_state(rec) -> None:
    job = JOBS.get(rec.job)
    if job is not None:
        job["timelapse"] = {"state": rec.state, "frames": rec.frames, "error": rec.error}
    if rec.cloud_job:
        await BRIDGE_CLIENT.event("timelapse.state", {"job": rec.cloud_job, "state": rec.state, "frames": rec.frames,
                                                      "error": rec.error})


async def _tl_upload(rec) -> None:
    await BRIDGE_CLIENT.upload_timelapse(rec.cloud_job, Path(rec.out))


TIMELAPSE = TimelapseRecorder(lambda: settings.work_dir, _tl_status, _tl_snapshot, lambda s: printer_kind(s),
                              on_state=_tl_state, upload=_tl_upload)


# ---------- AI failure detection with the Obico ML API (0.23.0, own servers only) ----------
WATCHER = fw.FailureWatcher(lambda: settings, get_adapter, printer_kind)


@app.get("/api/detect/frame/{token}.jpg")
def detect_frame(token: str) -> Response:
    """A camera frame for the ML API (one-time address, 60 s; the random token is the secret, no key in its logs)."""
    data = WATCHER.frame(token) if not settings.cloud and re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token) else None
    if data is None:
        raise HTTPException(404, "no such frame")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


class FailureDetectionSettings(BaseModel):
    ml_url: str = Field(..., max_length=300)
    ml_token: str | None = Field(None, max_length=300)        # None = keep
    server_url: str | None = Field(None, max_length=300)
    interval: int = Field(15, ge=5, le=300)
    sensitivity: str = Field("medium", pattern="^(low|medium|high)$")
    action: str = Field("notify", pattern="^(notify|pause)$")


def _watch_home(acct: Account) -> None:
    if acct.cloud or settings.cloud:
        raise HTTPException(409, "failure detection needs your own PocketPrint3D server with camera access")


@app.get("/api/failure-detection/config")
def failure_config(acct: Account = Depends(auth)) -> dict[str, Any]:
    _watch_home(acct)
    cfg = fw.load_config(settings)
    return {"configured": cfg.configured, "ml_url": cfg.ml_url or None, "token_set": bool(cfg.ml_token),
            "server_url": cfg.server_url or None, "interval": cfg.interval, "sensitivity": cfg.sensitivity,
            "action": cfg.action}


def _http_url(u: str) -> str:
    u = u.strip().rstrip("/")
    parts = urlsplit(u)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
        raise HTTPException(400, f"not an address: {u!r} (e.g. http://192.168.1.10:3333)")
    return u


@app.put("/api/failure-detection/config")
async def failure_config_set(req: FailureDetectionSettings, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Saves after a real test: the ML API has to fetch and check a test image from this server."""
    _watch_home(acct)
    old = fw.load_config(settings)
    cfg = fw.WatchConfig(_http_url(req.ml_url), old.ml_token if req.ml_token is None else req.ml_token.strip(),
                         _http_url(req.server_url) if req.server_url else old.server_url,
                         req.interval, req.sensitivity, req.action)
    if not cfg.server_url:
        raise HTTPException(400, "enter this server's address as the ML API container reaches it (e.g. http://192.168.1.10:8484)")
    from PIL import Image
    buf = __import__("io").BytesIO()
    Image.new("RGB", (320, 240), (90, 90, 90)).save(buf, "JPEG")
    try:
        detections = await WATCHER.detect(cfg, buf.getvalue())
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    fw.save_config(settings, cfg)
    return {**failure_config(acct), "test": {"detections": len(detections)}}


@app.delete("/api/failure-detection/config")
def failure_config_delete(acct: Account = Depends(auth)) -> dict[str, Any]:
    _watch_home(acct)
    fw.save_config(settings, None)
    return {"configured": fw.load_config(settings).configured}


@app.get("/api/printers/{printer_id}/watch/frame")
def watch_frame(printer_id: str, acct: Account = Depends(auth)) -> Response:
    _watch_home(acct)
    _printer(acct, printer_id)
    w = WATCHER.watches.get(printer_id)
    if w is None or w.frame is None:
        raise HTTPException(404, "no frame yet")
    return Response(w.frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/printers/{printer_id}/watch/mute")
async def watch_mute(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    """'False alarm': no more alerts for the rest of this print."""
    if _via_bridge(acct, printer_id):
        return await _forward(acct, printer_id, "watch.mute")
    _watch_home(acct)
    _printer(acct, printer_id)
    WATCHER.mute(printer_id)
    return WATCHER.state(printer_id, fw.load_config(settings))


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
    if _via_bridge(acct, printer_id):
        return await _forward(acct, printer_id, "printer.power")
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
    if _via_bridge(acct, printer_id):
        return await _forward(acct, printer_id, "printer.power", on=req.on)
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
    if _via_bridge(acct, printer_id):
        return await _forward(acct, printer_id, "printer.controls")
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
    if _via_bridge(acct, printer_id):
        return await _forward(acct, printer_id, "printer.adjust", kind=req.kind, id=req.id, value=req.value,
                              confirm=req.confirm)
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


# ---------- filament per slot: load / unload / what is in it (Bambu AMS first) ----------
class FilamentRequest(BaseModel):
    action: str                        # load | unload | set
    slot: int | None = None            # tool number of the slot (AMS tray 0-15, Bambu external spool 254)
    material: str | None = None        # set: one of /filament materials ("PLA", "PETG" …)
    color: str | None = None           # set: "#RRGGBB"
    temp: int | None = Field(default=None, ge=150, le=320)   # load/unload: nozzle °C (default: the slot's material)
    confirm: bool = False


@app.get("/api/printers/{printer_id}/filament")
async def filament_info(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    """What the app's filament menu can do for this printer, with its slots and the materials to choose from."""
    if _via_bridge(acct, printer_id):
        return await _forward(acct, printer_id, "printer.filament.info")
    _local_only(acct)
    adapter = get_adapter(_printer(acct, printer_id))
    caps = adapter.filament_caps() if hasattr(adapter, "filament_caps") else {}
    if not caps:
        return {"supported": False, "slots": [], "materials": [], "load": False, "unload": False, "set": False}
    try:
        st = await adapter.status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"printer not reachable: {e}")
    slots = list(st.get("lanes") or [])
    if caps.get("external") and st.get("external"):
        slots.append(st["external"])
    return {"supported": True, **caps, "slots": slots, "materials": filament_mod.materials_json(),
            "busy": printer_kind(st.get("state")) in ("active", "paused")}


@app.post("/api/printers/{printer_id}/filament")
async def filament_action(printer_id: str, req: FilamentRequest, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Load / unload filament or set what is in a slot. Loading and unloading heat the nozzle and move filament: never
    while a print runs, and only with confirm=true."""
    if _via_bridge(acct, printer_id):
        return await _forward(acct, printer_id, "printer.filament", **req.model_dump())
    _local_only(acct)
    if req.action not in filament_mod.ACTIONS:
        raise HTTPException(400, f"action must be one of {', '.join(filament_mod.ACTIONS)}")
    adapter = get_adapter(_printer(acct, printer_id))
    caps = adapter.filament_caps() if hasattr(adapter, "filament_caps") else {}
    if not caps.get(req.action):
        raise HTTPException(400, f"this printer can't {req.action} filament from PocketPrint3D")
    if req.action == "set":
        if filament_mod.material(req.material) is None:
            raise HTTPException(400, "choose a material from the list")
        if filament_mod.colour(req.color) is None:
            raise HTTPException(400, "color must be #RRGGBB")
    elif req.action == "load" and req.slot is None:
        raise HTTPException(400, "which slot to load?")
    try:
        st = await adapter.status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"printer not reachable: {e}")
    if req.action in ("load", "unload"):
        if printer_kind(st.get("state")) in ("active", "paused"):
            raise HTTPException(409, "a print is running - load or unload filament when it is over")
        if not req.confirm:
            raise HTTPException(409, "loading and unloading heat the nozzle - confirm (confirm=true)")
    if req.slot is not None:
        known = {x.get("tool") for x in (st.get("lanes") or []) + ([st["external"]] if st.get("external") else [])}
        if req.slot not in known:
            raise HTTPException(400, "unknown slot")
    try:
        return {"ok": True, **await adapter.filament(req.action, req.slot, req.material, req.color, req.temp)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"printer not reachable: {e}")


# ---------- spools by NFC chip and per slot, NFC readers at the printer (0.38.0, printshare/spooltags.py) ----------
_SPOOLTAGS: spooltags_mod.SpoolTags | None = None


def _tags() -> spooltags_mod.SpoolTags:
    """One store: next to the cloud database, or in the home server's config folder (owner "local")."""
    global _SPOOLTAGS
    if _SPOOLTAGS is None:
        base = Path(settings.cloud_db).parent if settings.cloud else Path(settings.config_dir or ".")
        _SPOOLTAGS = spooltags_mod.SpoolTags(base / "spooltags.db")
    return _SPOOLTAGS


def _tag_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except spooltags_mod.TagError as e:
        raise HTTPException(400, str(e))


class TagLink(BaseModel):
    spool: int = Field(ge=1)


class SlotSpool(BaseModel):
    spool: int | None = Field(default=None, ge=1)     # None = no spool in this slot


class ReaderScan(BaseModel):
    slot: int = Field(ge=0, le=255)       # tool number of the slot (Bambu external spool: 254)
    uid: str                              # the chip number, hex
    printer: str | None = None            # only with the server's own token (a reader key names its printer)


@app.get("/api/spool-tags")
def spool_tags_list(acct: Account = Depends(auth)) -> list[dict[str, Any]]:
    """All chips linked to a spool."""
    return _tags().links(acct.id)


@app.get("/api/spool-tags/{uid}")
def spool_tag(uid: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    """The spool of a chip - null if the chip isn't linked yet (the app then asks "which spool is this?")."""
    u = _tag_call(spooltags_mod.normalize_uid, uid)
    return {"uid": u, "spool": _tags().spool_for(acct.id, u)}


@app.put("/api/spool-tags/{uid}")
def spool_tag_link(uid: str, req: TagLink, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Link a chip to a spool (a reader that already saw the chip in a slot puts the spool there). The spool number is
    the one of the spool list the app uses: the cloud account's spools or the user's own Spoolman."""
    return _tag_call(_tags().link, acct.id, uid, req.spool)


@app.delete("/api/spool-tags/{uid}")
def spool_tag_unlink(uid: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    return {"deleted": _tag_call(_tags().unlink, acct.id, uid)}


def _cloud_spool(acct: Account, spool: int) -> dict[str, Any]:
    try:
        return SPOOLS.get(acct.id, spool)
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e))


@app.get("/api/printers/{printer_id}/slot-spools")
def slot_spools(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Spool per slot ({tool: {spool, source, updated}}) and what NFC readers saw last ({tool: {uid, spool, at}})."""
    _printer(acct, printer_id)
    return {"slots": _tags().slots(acct.id, printer_id), "scans": _tags().scans(acct.id, printer_id)}


@app.put("/api/printers/{printer_id}/slot-spools/{tool}")
async def slot_spool_set(printer_id: str, tool: int, req: SlotSpool, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Put a spool into a slot (or none). With cloud spools the printer's slot gets the spool's material and colour."""
    _printer(acct, printer_id)
    if not 0 <= tool <= 255:
        raise HTTPException(400, "slot must be 0-255")
    _tags().set_slot(acct.id, printer_id, tool, req.spool, "app")
    synced = await _sync_slot(acct, printer_id, tool, req.spool) if req.spool else False
    return {"slots": _tags().slots(acct.id, printer_id), "printer_set": synced}


def _spool_source(acct: Account) -> str:
    """"cloud" or "spoolman" - what spool numbers of this account mean (a home server has only Spoolman)."""
    chosen = spool_source.load(acct.settings.config_dir).get("source")
    if not acct.cloud:
        return "spoolman"
    return chosen if chosen in spool_source.SOURCES else "cloud"


async def _sync_slot(acct: Account, printer_id: str, tool: int, spool: int) -> bool:
    """Tell the printer what is in the slot (Bambu: ams_filament_setting): material and colour from the cloud spools,
    or from the user's Spoolman - read by this home server / bridge, or asked of the bridge the printer sits behind
    (the cloud can't reach a Spoolman at home). Never fails the caller."""
    try:
        if acct.cloud and _spool_source(acct) == "spoolman":
            if not _via_bridge(acct, printer_id):
                return False                                  # printer on the phone's Wi-Fi: the app tells it
            r = await _forward(acct, printer_id, "printer.slot.sync", tool=tool, spool=spool)
            return bool((r or {}).get("printer_set"))
        if acct.cloud:
            if SPOOLS is None:
                return False
            f = _cloud_spool(acct, spool).get("filament") or {}
            material, colour = f.get("material"), f.get("color_hex")
        else:
            url = spool_source.spoolman_url(acct.settings.config_dir)
            if not url:
                return False
            info = await spool_source.fetch_spool(url, spool)
            material, colour = info["material"], info["color"]
        m, col = filament_mod.material(material), filament_mod.colour(colour)
        if m is None or col is None:
            return False
        await filament_action(printer_id, FilamentRequest(action="set", slot=tool, material=m.name, color="#" + col), acct)
        return True
    except Exception:  # noqa: BLE001 - the assignment stands even if the printer can't be told
        return False


class SpoolSourceRequest(BaseModel):
    source: str                          # cloud | spoolman
    spoolman_url: str | None = None      # the user's own Spoolman (home server: stored; cloud: passed to the bridges)


@app.get("/api/spool-source")
def spool_source_get(acct: Account = Depends(auth)) -> dict[str, Any]:
    """Where this account keeps its spools, and whether this server reaches a Spoolman itself (home server / bridge)."""
    url = None if acct.cloud else spool_source.spoolman_url(acct.settings.config_dir)
    return {"source": _spool_source(acct), "spoolman_url": url, "server_reaches_spoolman": bool(url)}


@app.put("/api/spool-source")
async def spool_source_set(req: SpoolSourceRequest, acct: Account = Depends(auth)) -> dict[str, Any]:
    """The app's choice (Settings → Spoolman). A home server stores its Spoolman address; a cloud account passes it to
    its online bridges, so they can tell printers what is in a slot when an NFC reader reports a spool."""
    if req.source not in spool_source.SOURCES:
        raise HTTPException(400, "source must be cloud or spoolman")
    if not acct.cloud and req.source != "spoolman":
        raise HTTPException(400, "a home server keeps spools in Spoolman")
    url = None
    if req.spoolman_url:
        try:
            url = spool_source.check_url(req.spoolman_url)
        except ValueError as e:
            raise HTTPException(400, str(e))
    bridges_set = 0
    if acct.cloud:
        spool_source.save(acct.settings.config_dir, source=req.source)
        if url and BRIDGES is not None:
            for b in BRIDGES.list(acct.id):
                if not HUB.online(b["id"]):
                    continue
                try:
                    await bridge_call(acct, b["id"], "spoolman.config", {"url": url})
                    bridges_set += 1
                except HTTPException:
                    continue                                   # offline or an older bridge
    else:
        spool_source.save(acct.settings.config_dir, source="spoolman", spoolman_url=url)
    return {**spool_source_get(acct), "bridges_set": bridges_set}


@app.post("/api/spool-source/test")
async def spool_source_test(req: SpoolSourceRequest, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Can this server reach that Spoolman? (Web page of an own server; the app tests from the phone.)"""
    if acct.cloud:
        raise HTTPException(409, "the cloud can't reach a Spoolman at home - the app or a bridge tests it")
    try:
        return await spool_source.check(spool_source.check_url(req.spoolman_url or ""))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/printers/{printer_id}/reader-key")
def reader_key_state(printer_id: str, request: Request, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Is an NFC reader set up for this printer? (The key itself is shown only when it is created.)"""
    _printer(acct, printer_id)
    info = _tags().key_info(acct.id, printer_id)
    return {"enabled": info is not None, "url": _public_url(request) + "/api/reader/scan", **(info or {})}


@app.post("/api/printers/{printer_id}/reader-key")
def reader_key_create(printer_id: str, request: Request, acct: Account = Depends(auth)) -> dict[str, Any]:
    """A key for an NFC reader at this printer (ESP32 + PN5180): shown once, an older key stops working."""
    _printer(acct, printer_id)
    return {"enabled": True, "url": _public_url(request) + "/api/reader/scan",
            "key": _tags().create_key(acct.id, printer_id)}


@app.delete("/api/printers/{printer_id}/reader-key")
def reader_key_delete(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    return {"deleted": _tags().delete_key(acct.id, printer_id)}


@app.post("/api/reader/scan")
async def reader_scan(req: ReaderScan, request: Request) -> dict[str, Any]:
    """An NFC reader at the printer saw a chip in a slot. Auth: the printer's reader key (Bearer or X-Api-Key), or on a
    home server its token with `printer`. Known chip → the spool now sits in that slot (and the printer is told);
    unknown chip → remembered, the app offers to link it."""
    key = _token(request) or request.headers.get("x-api-key") or ""
    found = _tags().resolve_key(key)
    if found:
        owner, printer_id = found
        if settings.cloud:
            user = ACCOUNTS.user(owner) if ACCOUNTS is not None else None
            if user is None:
                raise HTTPException(403, "invalid reader key")
            acct = _user_account(user, "")
        else:
            acct = Account("local", settings)
    else:
        acct = auth(request)                                # home server token (or a logged-in session)
        if not req.printer:
            raise HTTPException(400, "printer is missing")
        printer_id = req.printer
    _printer(acct, printer_id)
    spool = _tag_call(_tags().scan, acct.id, printer_id, req.slot, req.uid)
    synced = await _sync_slot(acct, printer_id, req.slot, spool) if spool else False
    return {"known": spool is not None, "spool": spool, "printer_set": synced}


@app.get("/api/printers/{printer_id}/temperatures")
async def temperatures(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Temperature history: from the printer where it keeps one (Moonraker, OctoPrint), else what
    PocketPrint3D saw in the last 30 minutes of status queries."""
    if _via_bridge(acct, printer_id):
        return await _forward(acct, printer_id, "printer.temperatures")
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
        source = await cam.source_for(printer, adapter)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"camera not reachable: {e}")
    if source is None:
        raise HTTPException(404, "this printer has no camera")
    return source


@app.get("/api/printers/{printer_id}/camera")
async def camera_info(printer_id: str, acct: Account = Depends(auth)) -> dict[str, Any]:
    if _via_bridge(acct, printer_id):
        info = await _forward(acct, printer_id, "printer.camera")
        return {**info, "stream": False}            # through a bridge: still images only (BRIDGE.md section 11)
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
    if _via_bridge(acct, printer_id):
        shot = await _forward(acct, printer_id, "printer.camera.snapshot", **({"w": w} if w else {}))
        try:
            jpeg = base64.b64decode(shot["jpeg"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(502, "the bridge sent no picture")
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
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
    if _via_bridge(acct, printer_id):
        return await _forward(acct, printer_id, "printer.control", action=req.action, confirm=req.confirm)
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


JOB_TRACK_S = 30


async def _track_printer(owner: str, printer_id: str) -> None:
    try:
        st = await asyncio.wait_for(get_adapter(settings.printer(printer_id)).status(), JOB_TRACK_S / 2)
    except Exception:  # noqa: BLE001 - unknown printer or off: nothing learned
        return
    _track_jobs(owner, printer_id, st)


async def _jobs_track_loop() -> None:
    """Home server: started jobs follow their printer until the print is over (0.33.0); every printer is looked at, so
    prints started elsewhere show up as jobs too (0.40.0)."""
    while True:
        await asyncio.sleep(JOB_TRACK_S)
        pairs = _started_printers() | {("local", p.id) for p in settings.printers}
        await asyncio.gather(*(_track_printer(o, p) for o, p in sorted(pairs)), return_exceptions=True)


async def _jobs_loop() -> None:
    """Mirror the jobs into the job store every few seconds; clean up old ones once an hour."""
    last_prune = 0.0
    while True:
        await asyncio.sleep(JOB_SYNC_S)
        try:
            if time.time() - last_prune > 3600:
                last_prune = time.time()
                await asyncio.to_thread(JOB_STORE.prune, JOBS)
            await asyncio.to_thread(JOB_STORE.sync, JOBS)
        except Exception:  # noqa: BLE001 - never stop saving
            import logging
            logging.getLogger(__name__).exception("job store")


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
               "file": (j["result"] or {}).get("source_file") or j.get("printer_file"),
               "progress": j.get("progress"),
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
    # time-lapse video of this print (0.32.0): own servers and printers behind a bridge, needs a camera;
    # None = the server's "always" setting (0.40.0)
    timelapse: bool | None = None


@app.post("/api/jobs/{job_id}/send")
async def send(job_id: str, req: SendRequest, acct: Account = Depends(auth)) -> dict[str, Any]:
    job = _own_job(acct, job_id)
    printer_id = (job.get("result") or {}).get("printer")
    if not (printer_id and _via_bridge(acct, printer_id)):
        _local_only(acct)
    if req.start and not req.confirm:
        raise HTTPException(400, "starting a print needs confirm=true")  # NF-05
    if job["state"] not in ("sliced", "uploaded", "finished", "cancelled"):     # printed before: print it again
        raise HTTPException(409, f"job is {job['state']}, not ready to send")
    if not job.get("result"):
        raise HTTPException(409, "this print was started on the printer - there is no G-code to send")
    result = JobResult(**job["result"])
    via = _via_bridge(acct, result.printer)
    if via:
        # the bridge checks the rest itself (busy printer, lanes, spool) - with the same code as a home server
        job.update(state="sending", error=None)
        params = {"printer": via[1], "job": job_id, "start": req.start, "confirm": req.confirm,
                  "leveling": req.leveling, "lanes": req.lanes, "spool_id": req.spool_id, "timelapse": req.timelapse}

        async def forward() -> None:
            try:
                r = await HUB.call(via[0], acct.id, "job.send", params)
                job["leveling"] = req.leveling
                # the name the file has on the printer (the bridge names it after the model) - spool bookings match on it
                job["printer_file"] = (r or {}).get("file")
                if req.start and req.timelapse:
                    job["timelapse"] = {"state": "recording", "frames": 0}
                if req.start:
                    job.update(started_at=time.time(), seen_printing=False, progress=None, finished_at=None)
                job.update(state=(r or {}).get("state") or ("started" if req.start else "uploaded"))
            except BridgeError as e:
                job.update(state="sliced", error=f"Sending failed: {e}")

        _spawn(forward())
        return {"job": job_id}
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
            if req.start and _timelapse_wanted(req.timelapse) and not settings.cloud:
                # registered before the job says "started", so whoever sees "started" also sees the recording
                out = job_dir(job) or Path(acct.settings.gcode_dir) / result.printer / job_id
                rec = TIMELAPSE.start(result.printer, job_id, Path(result.gcode).name, out,
                                      cloud_job=(job.get("request") or {}).get("cloud_job"))
                job["timelapse"] = {"state": rec.state, "frames": 0}
            if req.start:
                job.update(started_at=time.time(), seen_printing=False, progress=None, finished_at=None)
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


class RelayedRequest(BaseModel):
    start: bool
    file: str                     # the file's name on the printer


@app.post("/api/jobs/{job_id}/relayed")
def job_relayed(job_id: str, req: RelayedRequest, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Cloud: the app sent the G-code to the printer itself (home Wi-Fi) - the job says so and follows the print."""
    job = _own_job(acct, job_id)
    if job["state"] not in ("sliced", "uploaded", "finished", "cancelled") or not job.get("result"):
        raise HTTPException(409, f"job is {job['state']}")
    job["printer_file"] = Path(req.file).name[:200]
    if req.start:
        job.update(state="started", started_at=time.time(), seen_printing=False, progress=None, finished_at=None)
    else:
        job.update(state="uploaded")
    return {"state": job["state"]}


# "always make a time-lapse" (0.40.0, own servers and bridges): prints sent without a choice and prints started elsewhere
TIMELAPSE_CONFIG = "timelapse.yaml"


def _timelapse_always() -> bool:
    if settings.cloud or not settings.config_dir:
        return False
    try:
        import yaml
        data = yaml.safe_load((Path(settings.config_dir) / TIMELAPSE_CONFIG).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("always") is True


def _timelapse_wanted(choice: bool | None) -> bool:
    """The app's choice for this print, else the server's setting."""
    return choice if choice is not None else _timelapse_always()


class TimelapseConfig(BaseModel):
    always: bool


@app.get("/api/timelapse/config")
def timelapse_config(acct: Account = Depends(auth)) -> dict[str, Any]:
    _local_only(acct)
    return {"always": _timelapse_always()}


@app.put("/api/timelapse/config")
def timelapse_config_set(req: TimelapseConfig, acct: Account = Depends(auth)) -> dict[str, Any]:
    """Own servers: record every print where the printer has a camera, also prints started elsewhere."""
    _local_only(acct)
    if not settings.config_dir:
        raise HTTPException(409, "this server has no config folder")
    import yaml
    p = Path(settings.config_dir) / TIMELAPSE_CONFIG
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("# Set from the PocketPrint3D app.\n" + yaml.safe_dump({"always": req.always}), encoding="utf-8")
    tmp.replace(p)
    return {"always": _timelapse_always()}


@app.get("/api/jobs/{job_id}/timelapse")
def job_timelapse(job_id: str, acct: Account = Depends(auth)) -> FileResponse:
    """The time-lapse video of a print (MP4), once it is ready."""
    job = _own_job(acct, job_id)
    d = job_dir(job)
    video = d / TIMELAPSE_FILE if d else None
    if video is None or not video.is_file():
        raise HTTPException(404, "no time-lapse for this job (yet)")
    name = Path((job.get("result") or {}).get("source_file") or job_id).stem + "-timelapse.mp4"
    return FileResponse(video, media_type="video/mp4", filename=name, content_disposition_type="inline")


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
# Cloud: the Expo web build (the same app as on the phone, docs/WEB.md). Home servers: the classic web page (printshare/web).
WEBAPP_CSP = ("default-src 'self'; "
              # the 3D viewers run in srcdoc iframes (inline module script, three.js from jsdelivr)
              "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
              "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; font-src 'self' data:; "
              "connect-src 'self' blob: data: https://cdn.jsdelivr.net; frame-src 'self' blob: about:; worker-src 'self' blob:; "
              "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
WEBAPP_HEADERS = {"Content-Security-Policy": WEBAPP_CSP, "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
                  "Referrer-Policy": "strict-origin-when-cross-origin",
                  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), usb=(), serial=()"}


def _webapp() -> Path | None:
    d = Path(settings.webapp_dir)
    return d if settings.cloud and (d / "index.html").is_file() else None


def _webapp_index(d: Path) -> HTMLResponse:
    return HTMLResponse((d / "index.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-cache", **WEBAPP_HEADERS})


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if settings.bridge_only and not settings.cloud:
        return bridge_page(request)
    d = _webapp()
    if d is not None:
        return _webapp_index(d)
    return HTMLResponse((WEB / "index.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(WEB / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    # served from the root so its scope covers the whole app
    return FileResponse(WEB / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})



# Web app (cloud): its files, and index.html for the app's own routes (/printers, /job/…). Answered only where no route
# matched (404), so every API route - also ones added later - wins. Hashed bundles may be cached for long; index.html never.
def _webapp_response(path: str) -> Response | None:
    d = _webapp()
    if d is None or path.startswith(("api/", "static/", "spoolman/")):
        return None
    target = (d / path).resolve()
    if path and target.is_file() and target.is_relative_to(d.resolve()):
        cache = "public, max-age=31536000, immutable" if path.startswith("_expo/static/") else "public, max-age=3600"
        return FileResponse(target, headers={"Cache-Control": cache, **WEBAPP_HEADERS})
    if "." in path.rsplit("/", 1)[-1]:
        return None                                      # a missing file, not an app route
    return _webapp_index(d)


@app.exception_handler(StarletteHTTPException)
async def _http_errors(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code == 404 and request.method in ("GET", "HEAD") and exc.detail == "Not Found":
        page = _webapp_response(request.url.path.lstrip("/"))
        if page is not None:
            return page
    return await http_exception_handler(request, exc)
