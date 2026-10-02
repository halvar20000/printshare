"""AI print-failure detection with the Obico ML API (own servers only).

The user runs Obico's ML API as a separate container (https://github.com/TheSpaghettiDetective/obico-server, only the
`ml_api` service, AGPL - it is called over HTTP, not linked). While a printer prints, this server takes a camera image
every `interval` seconds, offers it under a one-time address (/api/detect/frame/<random>.jpg, 60 s, no key in any log)
and asks the ML API `GET <ml>/p/?img=<that address>` → {"detections": [[label, confidence, [x, y, w, h]], ...]}.
The confidences of the failure detections are smoothed over the frames (exponential moving average), ignored during a
warm-up at the start of every print, and compared with a threshold for the chosen sensitivity. On an alert the
printer is optionally paused; the app shows the alert with the frame, "false alarm" mutes it for the rest of the print.
Works for every printer with a camera (also the Centauri Carbon with stock firmware, which Obico itself doesn't support).
Not in the cloud: the cloud has no camera access.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

CONFIG_FILE = "failure_detection.yaml"
SENSITIVITY = {"low": 0.75, "medium": 0.55, "high": 0.38}     # smoothed score that raises an alert
ALPHA = 2 / 13                                                 # smoothing: ~ the last dozen frames count
WARMUP_FRAMES = 12                                             # first layers (and the nozzle wipe) look odd
FRAME_TTL_S = 60
FAILURE_LABELS = ("failure", "spaghetti")


@dataclass
class WatchConfig:
    ml_url: str = ""
    ml_token: str = ""
    server_url: str = ""          # how the ML API container reaches this server (it fetches the frames)
    interval: int = 15
    sensitivity: str = "medium"
    action: str = "notify"        # "notify" | "pause"

    @property
    def configured(self) -> bool:
        return bool(self.ml_url and self.server_url)


def load_config(settings) -> WatchConfig:
    import yaml
    cfg = WatchConfig(os.environ.get("ML_API_URL", ""), os.environ.get("ML_API_TOKEN", ""))
    if not cfg.server_url:
        try:
            from .bootstrap import server_url
            cfg.server_url = server_url()
        except Exception:  # noqa: BLE001
            cfg.server_url = ""
    path = Path(settings.config_dir or ".") / CONFIG_FILE
    if settings.config_dir and path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for k in ("ml_url", "ml_token", "server_url", "sensitivity", "action"):
            if data.get(k) is not None:
                setattr(cfg, k, str(data[k]))
        if data.get("interval"):
            cfg.interval = int(data["interval"])
    cfg.ml_url, cfg.server_url = cfg.ml_url.rstrip("/"), cfg.server_url.rstrip("/")
    return cfg


def save_config(settings, cfg: WatchConfig | None) -> None:
    import yaml
    path = Path(settings.config_dir) / CONFIG_FILE
    if cfg is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(asdict(cfg)), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def frame_score(detections: Any) -> float:
    """Sum of the confidences of failure detections in one frame (several spots = more certain)."""
    total = 0.0
    for d in detections if isinstance(detections, list) else []:
        if isinstance(d, (list, tuple)) and len(d) >= 2 and str(d[0]).lower() in FAILURE_LABELS:
            try:
                total += max(0.0, min(1.0, float(d[1])))
            except (TypeError, ValueError):
                continue
    return min(total, 1.5)


@dataclass
class PrinterWatch:
    print_key: str | None = None
    frames: int = 0
    score: float = 0.0              # smoothed
    last_score: float | None = None  # last single frame
    last_check: float | None = None
    alerted_at: float | None = None
    muted: bool = False
    paused: bool = False
    error: str | None = None
    frame: bytes | None = field(default=None, repr=False)

    def reset(self, key: str | None) -> None:
        self.__init__(print_key=key)

    def public(self, cfg: WatchConfig) -> dict[str, Any]:
        state = ("alert" if self.alerted_at and not self.muted else "muted" if self.muted
                 else "warming" if self.print_key and self.frames <= WARMUP_FRAMES else "watching" if self.print_key else "idle")
        return {"state": state, "score": round(self.score, 3), "threshold": SENSITIVITY.get(cfg.sensitivity, 0.55),
                "frames": self.frames, "last_check": self.last_check, "alerted_at": self.alerted_at, "paused": self.paused,
                "action": cfg.action, "error": self.error, "frame": self.frame is not None}


class FailureWatcher:
    """One per server; `printers()` gives the current printer configs, `adapter_for(printer)` their adapters."""

    def __init__(self, settings_getter: Callable[[], Any], adapter_for: Callable[[Any], Any],
                 kind_of: Callable[[str | None], str], http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings_getter
        self.adapter_for = adapter_for
        self.kind_of = kind_of            # api.printer_kind (idle/active/paused/…)
        self.http = http
        self.watches: dict[str, PrinterWatch] = {}
        self.frames: dict[str, tuple[bytes, float]] = {}
        self._task: asyncio.Task | None = None

    # ---------- one-time frame addresses ----------
    def offer(self, jpeg: bytes) -> str:
        now = time.time()
        for k in [k for k, (_, exp) in self.frames.items() if exp < now]:
            del self.frames[k]
        token = secrets.token_urlsafe(18)
        self.frames[token] = (jpeg, now + FRAME_TTL_S)
        return token

    def frame(self, token: str) -> bytes | None:
        hit = self.frames.get(token)
        return hit[0] if hit and hit[1] >= time.time() else None

    # ---------- ML API ----------
    async def detect(self, cfg: WatchConfig, jpeg: bytes) -> list[Any]:
        token = self.offer(jpeg)
        img = f"{cfg.server_url}/api/detect/frame/{token}.jpg"
        client = self.http or httpx.AsyncClient(timeout=60)
        try:
            r = await client.get(f"{cfg.ml_url}/p/?img={quote(img, safe='')}",
                                 headers={"Authorization": f"Bearer {cfg.ml_token}"} if cfg.ml_token else {})
        except httpx.HTTPError as e:
            raise RuntimeError(f"ML API not reachable ({e.__class__.__name__})") from e
        finally:
            if self.http is None:
                await client.aclose()
            self.frames.pop(token, None)
        if r.status_code != 200:
            raise RuntimeError(f"ML API answered HTTP {r.status_code} - can it reach {cfg.server_url}?")
        try:
            return r.json().get("detections") or []
        except (ValueError, AttributeError) as e:
            raise RuntimeError("ML API sent no detections") from e

    # ---------- watching ----------
    async def check(self, printer, cfg: WatchConfig) -> None:
        from . import camera as cam
        w = self.watches.setdefault(printer.id, PrinterWatch())
        adapter = self.adapter_for(printer)
        try:
            st = await adapter.status()
        except Exception:  # noqa: BLE001 - printer off: nothing to watch
            return
        kind = self.kind_of(st.get("state"))
        key = st.get("file") or None
        if kind != "active":
            if kind != "paused":
                w.reset(None)
            return
        if key != w.print_key:
            w.reset(key)                      # a new print: start over
        if w.muted or w.alerted_at:
            return
        try:
            source = await adapter.camera() if hasattr(adapter, "camera") else None
            if source is None:
                w.error = "no camera"
                return
            jpeg = await cam.snapshot(source)
            jpeg = await asyncio.to_thread(cam.scale, jpeg, 640)
            detections = await self.detect(cfg, jpeg)
        except Exception as e:  # noqa: BLE001 - camera or ML API: report, never touch the print
            w.error = str(e)[:200]
            return
        w.error = None
        s = frame_score(detections)
        w.last_score, w.last_check, w.frame = s, time.time(), jpeg
        w.frames += 1
        w.score = s if w.frames == 1 else ALPHA * s + (1 - ALPHA) * w.score
        if w.frames > WARMUP_FRAMES and w.score >= SENSITIVITY.get(cfg.sensitivity, 0.55):
            w.alerted_at = time.time()
            log.warning("possible print failure on %s (score %.2f)", printer.id, w.score)
            if cfg.action == "pause":
                try:
                    await adapter.control("pause")
                    w.paused = True
                except Exception as e:  # noqa: BLE001
                    w.error = f"pause failed: {e}"[:200]

    async def tick(self) -> None:
        settings = self.settings()
        cfg = load_config(settings)
        if not cfg.configured or getattr(settings, "cloud", False):
            return
        await asyncio.gather(*(self.check(p, cfg) for p in settings.printers), return_exceptions=True)

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
                interval = load_config(self.settings()).interval
            except Exception:  # noqa: BLE001
                log.exception("failure watch")
                interval = 30
            await asyncio.sleep(max(5, interval))

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    def mute(self, printer_id: str) -> None:
        w = self.watches.setdefault(printer_id, PrinterWatch())
        w.muted = True

    def state(self, printer_id: str, cfg: WatchConfig) -> dict[str, Any]:
        return self.watches.get(printer_id, PrinterWatch()).public(cfg)
