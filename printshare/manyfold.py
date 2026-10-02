"""Manyfold (https://manyfold.app) - the user's own self-hosted 3D model library as a model source.

API v0 (OpenAPI at <instance>/api/v0/openapi.json, JSON-LD with `Accept: application/vnd.manyfold.v0+json`):
  GET /models?page=&order=name|recent|updated  -> {"totalItems", "member": [{"@id": ".../models/<id>", "name"}], "view": {"next"}}
  GET /models/<id>      -> name, caption, description, keywords, spdx:license, creator, hasPart (files), preview_file
  GET /models/<id>/model_files/<file id>  -> filename, encodingFormat, contentUrl, contentSize
Every call needs authentication, even for public data: a long-lived API key (Manyfold >= 0.132, bearer token) or OAuth2
client credentials (POST /oauth/token, scopes "public read"). The JSON API has no search, so the model list (ids and
names) is cached for a few minutes and searched here. Only for the user's own server: the hosted cloud would have to
reach into home networks for this (and must not fetch arbitrary addresses).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .fetch import UA, FetchError

ACCEPT = "application/vnd.manyfold.v0+json"
LIST_TTL_S = 300
MAX_PAGES = 400
# file formats OrcaSlicer can slice (Manyfold reports MIME types)
SLICEABLE_TYPES = ("model/stl", "model/3mf", "model/obj", "model/step", "application/sla", "model/x.stl-binary",
                   "model/x.stl-ascii", "application/vnd.ms-package.3dmanufacturing-3dmodel+xml", "application/step")
SLICEABLE_EXT = (".stl", ".3mf", ".obj", ".step", ".stp")


@dataclass
class ManyfoldConfig:
    url: str = ""
    token: str = ""            # API key (bearer token)
    client_id: str = ""        # or OAuth application credentials
    client_secret: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.url and (self.token or (self.client_id and self.client_secret)))


def model_id(ref: str) -> str:
    """'https://host/models/abc123' or '/models/abc123' -> 'abc123'."""
    parts = [p for p in urlsplit(ref).path.split("/") if p]
    return parts[parts.index("models") + 1] if "models" in parts and parts.index("models") + 1 < len(parts) else parts[-1]


class Manyfold:
    def __init__(self, cfg: ManyfoldConfig, http: httpx.Client | None = None) -> None:
        if not cfg.configured:
            raise FetchError("Manyfold is not set up (address and API key)")
        self.cfg = cfg
        self.base = cfg.url.rstrip("/")
        self.http = http or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA})
        self.lock = threading.Lock()
        self._token: tuple[str, float] | None = None
        self._list: tuple[list[dict[str, str]], float] | None = None

    # ---------- auth + requests ----------
    def _bearer(self) -> str:
        if self.cfg.token:
            return self.cfg.token
        with self.lock:
            if self._token and self._token[1] > time.time() + 30:
                return self._token[0]
            try:
                r = self.http.post(f"{self.base}/oauth/token", data={
                    "grant_type": "client_credentials", "client_id": self.cfg.client_id,
                    "client_secret": self.cfg.client_secret, "scope": "public read"})
            except httpx.HTTPError as e:
                raise FetchError(f"Manyfold not reachable ({e.__class__.__name__})") from e
            if r.status_code != 200:
                raise FetchError(f"Manyfold refused the app credentials (HTTP {r.status_code})")
            body = r.json()
            self._token = (body["access_token"], time.time() + float(body.get("expires_in") or 3600))
            return self._token[0]

    def _get(self, path_or_url: str, params: dict[str, Any] | None = None, accept: str = ACCEPT) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base}{path_or_url}"
        if not url.startswith(self.base + "/"):
            raise FetchError("Manyfold answered with an address of another server")     # never follow elsewhere
        try:
            r = self.http.get(url, params=params, headers={"Accept": accept, "Authorization": f"Bearer {self._bearer()}"})
        except httpx.HTTPError as e:
            raise FetchError(f"Manyfold not reachable ({e.__class__.__name__})") from e
        if r.status_code in (401, 403):
            raise FetchError("Manyfold refused the API key - check it in the settings")
        if r.status_code == 404:
            raise FetchError("Manyfold model not found")
        if r.status_code != 200:
            raise FetchError(f"Manyfold API error {r.status_code}")
        return r

    def _json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            data = self._get(path, params).json()
        except ValueError as e:
            raise FetchError("Manyfold sent no JSON - is the address right?") from e
        if not isinstance(data, dict):
            raise FetchError("unexpected answer from Manyfold")
        return data

    # ---------- library ----------
    def models(self, refresh: bool = False) -> list[dict[str, str]]:
        """All models [{"id", "name"}] of the library (cached LIST_TTL_S)."""
        if not refresh and self._list and time.time() - self._list[1] < LIST_TTL_S:
            return self._list[0]
        out: list[dict[str, str]] = []
        page = 1
        while page <= MAX_PAGES:
            data = self._json("/models", {"page": page, "order": "name"})
            for m in data.get("member") or []:
                if isinstance(m, dict) and m.get("@id"):
                    out.append({"id": model_id(m["@id"]), "name": str(m.get("name") or "")})
            if not (data.get("view") or {}).get("next"):
                break
            page += 1
        self._list = (out, time.time())
        return out

    def model(self, mid: str) -> dict[str, Any]:
        return self._json(f"/models/{mid}")

    def file(self, mid: str, fid: str) -> dict[str, Any]:
        return self._json(f"/models/{mid}/model_files/{fid}")

    def download(self, mid: str, fid: str, target: Path) -> Path:
        f = self.file(mid, fid)
        url = f.get("contentUrl") or f"/models/{mid}/raw/{f.get('filename')}"
        r_url = url if url.startswith("http") else f"{self.base}{url}"
        if not r_url.startswith(self.base + "/"):
            raise FetchError("Manyfold answered with an address of another server")
        try:
            with self.http.stream("GET", r_url, headers={"Authorization": f"Bearer {self._bearer()}"}) as r:
                if r.status_code != 200:
                    raise FetchError(f"Manyfold download failed ({r.status_code})")
                with target.open("wb") as fh:
                    for chunk in r.iter_bytes(1 << 16):
                        fh.write(chunk)
        except httpx.HTTPError as e:
            raise FetchError(f"Manyfold not reachable ({e.__class__.__name__})") from e
        return target

    def image(self, mid: str, fid: str) -> tuple[bytes, str]:
        """An image file of a model (preview pictures for the app; the app can't log in to Manyfold itself)."""
        f = self.file(mid, fid)
        fmt = str(f.get("encodingFormat") or "")
        if not fmt.startswith("image/") or fmt == "image/svg+xml":
            raise FetchError("not an image")
        r = self._get(f.get("contentUrl") or f"/models/{mid}/raw/{f.get('filename')}", accept="image/*")
        if len(r.content) > 15 * 1024 * 1024:
            raise FetchError("image too large")
        return r.content, fmt


def is_sliceable(part: dict[str, Any]) -> bool:
    fmt = str(part.get("encodingFormat") or "").lower()
    name = str(part.get("name") or part.get("filename") or "").lower()
    return fmt in SLICEABLE_TYPES or name.endswith(SLICEABLE_EXT)


def file_id(ref: str) -> str:
    return [p for p in urlsplit(ref).path.split("/") if p][-1].split(".")[0]


EXT_BY_TYPE = {"model/stl": ".stl", "model/x.stl-binary": ".stl", "model/x.stl-ascii": ".stl", "application/sla": ".stl",
               "model/3mf": ".3mf", "application/vnd.ms-package.3dmanufacturing-3dmodel+xml": ".3mf",
               "model/obj": ".obj", "model/step": ".step", "application/step": ".step"}


def file_name(part: dict[str, Any]) -> str:
    """Manyfold shows names like "Benchy": give the file its extension from the MIME type (Orca needs it)."""
    name = str(part.get("filename") or part.get("name") or "model").strip() or "model"
    if name.lower().endswith(SLICEABLE_EXT):
        return name
    return name + EXT_BY_TYPE.get(str(part.get("encodingFormat") or "").lower(), ".stl")


# ---------- configuration: config.yaml / environment, or set in the app (<config dir>/manyfold.yaml) ----------
OVERLAY = "manyfold.yaml"
_CLIENTS: dict[tuple, Manyfold] = {}


def load_config(settings) -> ManyfoldConfig:
    cfg = ManyfoldConfig(settings.manyfold_url, settings.manyfold_token, settings.manyfold_client_id,
                         settings.manyfold_client_secret)
    path = Path(settings.config_dir or ".") / OVERLAY
    if settings.config_dir and path.is_file():
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for k in ("url", "token", "client_id", "client_secret"):
            if data.get(k) is not None:
                setattr(cfg, k, str(data[k]))
    return cfg


def save_config(settings, cfg: ManyfoldConfig | None) -> None:
    """Store what was set in the app (0600, like the other secrets); None removes it."""
    import os

    import yaml
    path = Path(settings.config_dir) / OVERLAY
    if cfg is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(yaml.safe_dump({"url": cfg.url, "token": cfg.token, "client_id": cfg.client_id,
                                       "client_secret": cfg.client_secret}), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    _CLIENTS.clear()


def client_for(settings) -> Manyfold | None:
    """The library client for this server - never in the hosted cloud (it can't and mustn't reach home networks)."""
    if getattr(settings, "cloud", False):
        return None
    cfg = load_config(settings)
    if not cfg.configured:
        return None
    key = (cfg.url, cfg.token, cfg.client_id, cfg.client_secret)
    if key not in _CLIENTS:
        _CLIENTS.clear()
        _CLIENTS[key] = Manyfold(cfg)
    return _CLIENTS[key]
