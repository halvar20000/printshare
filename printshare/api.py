"""Small HTTP API + phone-friendly web page (port 8484).

Endpoints (all except / need `Authorization: Bearer <api_token>` or `?token=`):
  GET  /api/printers
  GET  /api/files?link=...
  POST /api/print   {"link": "...", "printer": "cc-thomas", "file": 1, "start": true}
  GET  /api/jobs/{id}
  GET  /api/printers/{id}/status
"""
from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .config import load_settings
from .fetch import FetchError, Fetcher
from .pipeline import run_job
from .printers import get_adapter

settings = load_settings()
app = FastAPI(title="PrintShare", version="0.1")
JOBS: dict[str, dict[str, Any]] = {}
_TASKS: set[asyncio.Task] = set()  # keep references so tasks are not garbage-collected


def auth(request: Request) -> None:
    if not settings.api_token:
        return  # no token configured (only acceptable on a trusted LAN)
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip() or request.query_params.get("token", "")
    if not secrets.compare_digest(token, settings.api_token):
        raise HTTPException(401, "invalid token")


class PrintRequest(BaseModel):
    link: str
    printer: str | None = None
    file: str | None = None
    start: bool = True


@app.get("/api/printers", dependencies=[Depends(auth)])
def printers() -> list[dict[str, Any]]:
    return [{"id": p.id, "name": p.name or p.id, "type": p.type, "machine": p.slicing.machine}
            for p in settings.printers]


@app.get("/api/files", dependencies=[Depends(auth)])
async def files(link: str) -> list[dict[str, Any]]:
    try:
        listed = await asyncio.to_thread(Fetcher(settings.thingiverse_token).list_files, link)
        fl = [f for f in listed if f.sliceable]
    except FetchError as e:
        raise HTTPException(400, str(e))
    return [{"index": i, "name": f.name, "size": f.size} for i, f in enumerate(fl, 1)]


@app.post("/api/print", dependencies=[Depends(auth)])
async def print_(req: PrintRequest) -> dict[str, Any]:
    if not req.link.startswith(("http://", "https://")):
        raise HTTPException(400, "link must be an http(s) URL")
    job_id = uuid.uuid4().hex[:10]
    job: dict[str, Any] = {"id": job_id, "state": "running", "log": [], "result": None,
                           "created": time.time(), "request": req.model_dump()}
    JOBS[job_id] = job

    async def worker() -> None:
        try:
            res = await run_job(settings, req.link, req.printer, req.file, send=True, start=req.start,
                                progress=lambda m: job["log"].append(m))
            job.update(state="done", result=res.as_dict())
        except Exception as e:  # noqa: BLE001 - report every failure to the phone
            job.update(state="error", error=str(e))

    task = asyncio.create_task(worker())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"job": job_id}


@app.get("/api/jobs/{job_id}", dependencies=[Depends(auth)])
def job(job_id: str) -> dict[str, Any]:
    if job_id not in JOBS:
        raise HTTPException(404, "unknown job")
    return JOBS[job_id]


@app.get("/api/printers/{printer_id}/status", dependencies=[Depends(auth)])
async def status(printer_id: str) -> dict[str, Any]:
    try:
        return await get_adapter(settings.printer(printer_id)).status()
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"printer not reachable: {e}")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
