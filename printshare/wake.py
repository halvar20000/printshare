"""Switch a printer on for a print and wait until it is ready (0.46.0).

OrcaSlicer's "Upload and Print" goes to PocketPrint3D instead of the printer. When the printer is off and its smart
plug has `auto_on` set (printshare/power), the server keeps the G-code, switches the plug on, waits until the printer
answers in a resting state and only then uploads and starts. Moonraker's own [power] / [job_queue] can't do this on
COSMOS or the stock Centauri: Moonraker runs on the printer and is off with it.

Safety (NF-05): only for an explicit start ("Upload and Print"), only with `auto_on` (off by default), never longer
than WAKE_TIMEOUT_S, and a server restart while waiting never starts the print (the job is "sending", which the job
store turns back into "sliced").
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

WAKE_TIMEOUT_S = 10 * 60       # boot time of a Klipper printer is 1-3 min; the cloud waits 15 min for job.send
POLL_S = 5.0
STATUS_TIMEOUT_S = 20.0
# after the first answer: AFC (CANVAS) and Bambu's AMS report their lanes a little later than the printer itself
SETTLE_S = 20.0
RESTING = ("idle", "done", "stopped")


class WakeError(Exception):
    """The printer could not be switched on or did not come up in time; the message is shown to the user."""


async def printer_state(status: Callable[[], Awaitable[dict[str, Any]]], kind: Callable[[str | None], str],
                        timeout: float | None = None) -> str | None:
    """The printer's normalised state, None while it doesn't answer (off, booting, Klippy not ready yet)."""
    try:
        st = await asyncio.wait_for(status(), STATUS_TIMEOUT_S if timeout is None else timeout)
    except Exception:  # noqa: BLE001 - every error means "not there yet"
        return None
    k = kind(st.get("state"))
    return None if k in ("unknown", "error") else k


async def wake(status: Callable[[], Awaitable[dict[str, Any]]], kind: Callable[[str | None], str],
               switch_on: Callable[[], Awaitable[Any]], say: Callable[[str], None],
               timeout: float | None = None, poll: float | None = None, settle: float | None = None,
               clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
               ) -> bool:
    """Make sure the printer is on and ready. Returns True when it had to be switched on (False: it was on already).
    A busy printer counts as "on": the normal start checks refuse it afterwards."""
    timeout = WAKE_TIMEOUT_S if timeout is None else timeout
    poll = POLL_S if poll is None else poll
    settle = SETTLE_S if settle is None else settle
    if await printer_state(status, kind) is not None:
        return False
    say("The printer is off - switching it on")
    try:
        await switch_on()
    except Exception as e:  # noqa: BLE001
        raise WakeError(f"the printer could not be switched on: {e}") from None
    deadline = clock() + timeout
    while clock() < deadline:
        await sleep(poll)
        state = await printer_state(status, kind)
        if state is None:
            continue
        say("The printer is on - waiting a moment for its filament system")
        await sleep(settle)
        return True
    raise WakeError(f"the printer was switched on but did not answer within {int(timeout // 60)} minutes - "
                    "start the print again when it is ready")
