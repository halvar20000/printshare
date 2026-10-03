"""Time-lapse videos of prints (own servers and bridges - they can reach the camera; the cloud can't).

While a print runs, the recorder takes one camera picture per layer (printers that report the layer: Centauri Carbon,
Klipper) or every INTERVAL_S seconds (PrusaLink, OctoPrint), and when the print is over it renders an MP4 with ffmpeg
(the static binary from the `imageio-ffmpeg` package, so it works the same in every image). The video is stored in the
job's own folder (deleted with the job). On a bridge, the finished video is uploaded to the cloud job it belongs to.
Recordings are kept in `<work_dir>/timelapse/active.json`, so a restart of the server doesn't lose them.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

POLL_S = 4
INTERVAL_S = 30            # printers without layer information: one picture every 30 s
MAX_FRAMES = 3000
FRAME_WIDTH = 1280
TARGET_SECONDS = 15        # aim for a ~15 s video
FILE_NAME = "timelapse.mp4"


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - not installed: fall back to the system's ffmpeg
        return shutil.which("ffmpeg")


def render(frames: Path, out: Path, timeout_s: int = 600) -> Path:
    """MP4 (H.264, yuv420p, fast start) from frames/00001.jpg …; the last picture is held for a second."""
    count = len(list(frames.glob("*.jpg")))
    if count < 2:
        raise RuntimeError("too few pictures for a time-lapse")
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg is not available")
    fps = max(8, min(30, round(count / TARGET_SECONDS)))
    tmp = out.with_suffix(".tmp.mp4")
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps), "-i", str(frames / "%05d.jpg"),
           "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,tpad=stop_mode=clone:stop_duration=1",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if r.returncode != 0 or not tmp.is_file():
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[-300:]}")
    tmp.replace(out)
    return out


@dataclass
class Recording:
    printer: str
    job: str                       # local job id
    file: str                      # the print's file name on the printer (to see when it ends or changes)
    out: str                       # where the video goes (the job's folder)
    frames_dir: str
    cloud_job: str | None = None   # bridge: the cloud job the video is uploaded to
    frames: int = 0
    last_layer: int | None = None
    last_frame: float = 0.0
    seen_active: bool = False
    started: float = field(default_factory=time.time)
    state: str = "recording"       # recording | rendering | ready | failed
    error: str | None = None


def _same_file(a: str | None, b: str) -> bool:
    import re
    norm = lambda s: re.sub(r"[^a-z0-9]", "", re.sub(r"\.[^.]+$", "", s.split("/")[-1]).lower())  # noqa: E731
    return bool(a) and norm(a) == norm(b)


class TimelapseRecorder:
    """One per home server. `status(printer)` and `snapshot(printer)` come from the API (adapters, camera); `on_state`
    is told about every change (job field, bridge event); `upload` sends a finished video to the cloud (bridge)."""

    def __init__(self, work_dir: Callable[[], str], status: Callable[[str], Awaitable[dict[str, Any] | None]],
                 snapshot: Callable[[str], Awaitable[bytes]], kind_of: Callable[[str | None], str],
                 on_state: Callable[[Recording], Awaitable[None]] | None = None,
                 upload: Callable[[Recording], Awaitable[None]] | None = None) -> None:
        self.work_dir = work_dir
        self.status = status
        self.snapshot = snapshot
        self.kind_of = kind_of
        self.on_state = on_state
        self.upload = upload
        self.active: dict[str, Recording] = {}         # printer id → recording
        self._task: asyncio.Task | None = None
        self._load()

    # ---------- persistence ----------
    def _file(self) -> Path:
        return Path(self.work_dir()) / "timelapse" / "active.json"

    def _load(self) -> None:
        try:
            data = json.loads(self._file().read_text(encoding="utf-8"))
            self.active = {r["printer"]: Recording(**r) for r in data if isinstance(r, dict)}
        except (OSError, ValueError, TypeError):
            self.active = {}

    def _save(self) -> None:
        p = self._file()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(r) for r in self.active.values()]), encoding="utf-8")
        tmp.replace(p)

    # ---------- control ----------
    def start(self, printer: str, job: str, file: str, out_dir: Path, cloud_job: str | None = None) -> Recording:
        """Record the print that was just started (replaces an older recording on the same printer)."""
        frames = Path(self.work_dir()) / "timelapse" / f"{printer}-{job}"
        shutil.rmtree(frames, ignore_errors=True)
        frames.mkdir(parents=True, exist_ok=True)
        rec = Recording(printer=printer, job=job, file=file, out=str(out_dir / FILE_NAME), frames_dir=str(frames),
                        cloud_job=cloud_job)
        self.active[printer] = rec
        self._save()
        return rec

    def get(self, job: str) -> Recording | None:
        return next((r for r in self.active.values() if r.job == job), None)

    async def _changed(self, rec: Recording) -> None:
        self._save()
        if self.on_state:
            try:
                await self.on_state(rec)
            except Exception:  # noqa: BLE001
                log.exception("time-lapse state")

    # ---------- the loop ----------
    async def check(self, rec: Recording, now: float | None = None) -> None:
        now = now or time.time()
        try:
            st = await self.status(rec.printer)
        except Exception:  # noqa: BLE001 - printer off for a moment
            st = None
        kind = self.kind_of(st.get("state")) if st else None
        same = bool(st) and _same_file(st.get("file"), rec.file)
        if st and same and kind in ("active", "paused"):
            rec.seen_active = True
            if kind == "paused":
                return
            layer = st.get("layer")
            due = (isinstance(layer, int) and layer != rec.last_layer) if isinstance(layer, int) else now - rec.last_frame >= INTERVAL_S
            if due and rec.frames < MAX_FRAMES:
                try:
                    jpeg = await self.snapshot(rec.printer)
                except Exception as e:  # noqa: BLE001 - one missed picture is fine
                    log.debug("time-lapse picture: %s", e)
                    return
                rec.frames += 1
                (Path(rec.frames_dir) / f"{rec.frames:05d}.jpg").write_bytes(jpeg)
                rec.last_layer = layer if isinstance(layer, int) else rec.last_layer
                rec.last_frame = now
                if rec.frames == 1 or rec.frames % 5 == 0:
                    await self._changed(rec)     # saves too; tells the job / the cloud only now and then
                else:
                    self._save()                 # every picture, so a restart continues at the right number
            return
        # over: finished, stopped, or another print on the printer (unreachable: wait - it may come back)
        if st is None and now - max(rec.last_frame, rec.started) < 6 * 3600:
            return
        if not rec.seen_active and now - rec.started < 20 * 60:
            return                       # heating / leveling before the file shows as printing
        await self.finish(rec)

    async def finish(self, rec: Recording) -> None:
        self.active.pop(rec.printer, None)
        rec.state = "rendering"
        await self._changed(rec)
        try:
            out = Path(rec.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(render, Path(rec.frames_dir), out)
            rec.state = "ready"
            if self.upload is not None and rec.cloud_job:
                await self.upload(rec)
        except Exception as e:  # noqa: BLE001
            rec.state, rec.error = "failed", str(e)[:200]
        finally:
            shutil.rmtree(rec.frames_dir, ignore_errors=True)
        await self._changed(rec)

    async def tick(self) -> None:
        for rec in list(self.active.values()):
            await self.check(rec)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(POLL_S)
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - never stop
                log.exception("time-lapse")

    def start_loop(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())
