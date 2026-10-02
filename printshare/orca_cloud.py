"""Import shared OrcaSlicer Cloud bundles (issue #7) - no account or token needed.

A bundle shared on cloud.orcaslicer.com (`https://cloud.orcaslicer.com/b/<sharing token>`) can be read by anyone:
`GET https://api.orcaslicer.com/api/v1/bundles/share/<token>` returns its presets as JSON (`shared_profiles[].content`,
the same keys as an OrcaSlicer user preset). Found in the web app's code and checked with the public COSMOS bundle
(2026-10-02). Only *public* bundles: private ones (and syncing a user's own presets) need an Orca login, i.e. a
registered app (client_id) - still blocked.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from . import user_profiles
from .fetch import UA
from .profiles import ProfileLibrary

API = "https://api.orcaslicer.com/api/v1/bundles/share/"
LINK = re.compile(r"cloud\.orcaslicer\.com/b/([A-Za-z0-9_-]{4,64})(?:[/?#]|$)")
MAX_BYTES = 5 * 1024 * 1024
MAX_PRESETS = 200
# Orca Cloud bundles are "Public" or "Private"; a private one only opens for whitelisted, logged-in Orca users (the web
# app: "Only whitelisted users can access this private bundle link") - there is no link-only mode.
PRIVATE = ("bundle not found or private - private Orca Cloud bundles only open for logged-in Orca users: make the bundle "
           "public, or export the presets in OrcaSlicer and upload the file")


class OrcaCloudError(Exception):
    pass


def sharing_token(link: str) -> str:
    m = LINK.search((link or "").strip())
    if not m:
        raise OrcaCloudError("not an Orca Cloud share link - it looks like https://cloud.orcaslicer.com/b/…")
    return m.group(1)


def fetch_bundle(token: str, http: httpx.Client | None = None) -> dict[str, Any]:
    client = http or httpx.Client(timeout=20, headers={"User-Agent": UA}, follow_redirects=False)
    try:
        with client.stream("GET", API + token, headers={"Accept": "application/json"}) as r:
            if r.status_code in (401, 403, 404):
                raise OrcaCloudError(PRIVATE)
            if r.status_code != 200:
                raise OrcaCloudError(f"Orca Cloud answered HTTP {r.status_code}")
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise OrcaCloudError("bundle too large")
    except httpx.HTTPError as e:
        raise OrcaCloudError(f"Orca Cloud not reachable ({e.__class__.__name__})") from e
    finally:
        if http is None:
            client.close()
    try:
        data = json.loads(body)
    except ValueError as e:
        raise OrcaCloudError("Orca Cloud sent no bundle") from e
    if not isinstance(data, dict) or not isinstance(data.get("shared_profiles"), list):
        raise OrcaCloudError("Orca Cloud sent no bundle")
    return data


def presets_of(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """The presets of a bundle; a preset that inherits another one *of the same bundle* gets merged with it, so every
    preset is based on an OrcaSlicer system preset (what the import checks)."""
    out = []
    for p in bundle["shared_profiles"][:MAX_PRESETS]:
        c = p.get("content") if isinstance(p, dict) else None
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except ValueError:
                c = None
        if isinstance(c, dict) and c.get("name"):
            out.append(dict(c))
    by_name = {c["name"]: c for c in out}
    for c in out:
        seen = {c["name"]}
        while c.get("inherits") in by_name and c["inherits"] not in seen:
            parent = by_name[c["inherits"]]
            seen.add(parent["name"])
            merged = {**parent, **{k: v for k, v in c.items() if k != "inherits"}}
            merged["inherits"] = parent.get("inherits", "")
            c.clear()
            c.update(merged)
    return out


def import_bundle(config_dir: str, link: str, lib: ProfileLibrary, http: httpx.Client | None = None) -> dict[str, Any]:
    """Fetch a shared bundle and store every usable preset; presets OrcaSlicer 2.4.2 can't use are skipped."""
    bundle = fetch_bundle(sharing_token(link), http)
    presets = presets_of(bundle)
    if not presets:
        raise OrcaCloudError("the bundle contains no presets")
    imported, skipped = [], []
    for preset in presets:
        try:
            imported += user_profiles.store_presets(config_dir, [preset], lib)
        except user_profiles.ProfileUploadError as e:
            skipped.append({"name": preset.get("name"), "error": str(e)})
    if not imported:
        raise OrcaCloudError("none of the presets can be used: " + "; ".join(s["error"] for s in skipped[:3]))
    return {"bundle": {"name": bundle.get("name"), "author": bundle.get("creator_display_name") or bundle.get("creator_username"),
                       "version": bundle.get("version"), "updated": bundle.get("updated_at")},
            "imported": imported, "skipped": skipped}
