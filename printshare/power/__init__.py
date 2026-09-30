"""Power for printers (issue #9): switch a printer's smart plug on and off from outside the printer.

Moonraker's own [power] can't do it on COSMOS or the stock Centauri - when the printer is off, so is its
Moonraker - so the always-on PocketPrint3D server switches the plug. Settings are made on the web page and
stored per printer in <config dir>/printers.d/<id>.yaml under `power:` (kept in the "managed" mode).

Adapters follow the printer adapters (NF-08); today only Home Assistant, later e.g. Shelly/Tasmota URLs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import user_profiles

POWER_TYPES = ("homeassistant",)
SUPERVISOR_URL = "http://supervisor/core"


class PowerError(Exception):
    """Plug or Home Assistant not usable; the message is shown to the user."""


@dataclass
class PowerConfig:
    type: str = "homeassistant"
    url: str = ""            # Home Assistant, e.g. http://192.168.1.5:8123 (empty inside the HA add-on)
    token: str = ""          # long-lived access token (empty inside the HA add-on)
    entity: str = ""         # switch.printer_plug, light.…, input_boolean.…

    def public(self) -> dict[str, Any]:
        """What the app / browser may see: never the token itself."""
        return {"type": self.type, "url": self.url, "entity": self.entity, "token_set": bool(self.token),
                "supervisor": self.supervisor}

    @property
    def supervisor(self) -> bool:
        """Running as Home Assistant add-on without an own URL: talk to HA through the supervisor."""
        return not self.url and bool(os.environ.get("SUPERVISOR_TOKEN"))


def load(config_dir: str | Path, printer_id: str) -> PowerConfig | None:
    data = user_profiles.read_overlay(config_dir, printer_id).get("power")
    if not isinstance(data, dict) or not data.get("entity"):
        return None
    return PowerConfig(**{k: str(v) for k, v in data.items() if k in PowerConfig.__dataclass_fields__})


def save(config_dir: str | Path, printer_id: str, cfg: PowerConfig | None) -> None:
    overlay = user_profiles.read_overlay(config_dir, printer_id)
    if cfg is None:
        overlay.pop("power", None)
    else:
        overlay["power"] = {"type": cfg.type, "url": cfg.url, "token": cfg.token, "entity": cfg.entity}
    user_profiles.write_overlay(config_dir, printer_id, overlay)


def get_power(cfg: PowerConfig):
    if cfg.type == "homeassistant":
        from .homeassistant import HomeAssistantPower
        return HomeAssistantPower(cfg)
    raise PowerError(f"unknown power type {cfg.type!r} (use {', '.join(POWER_TYPES)})")
