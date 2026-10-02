"""Shared OrcaSlicer Cloud bundles (issue #7): import by share link, no account needed."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from printshare import orca_cloud, user_profiles

from .test_user_profiles import CC, lib  # noqa: F401 (fixture: a library with the Centauri 0.4 nozzle only)

BUNDLE = json.loads((Path(__file__).parent / "data" / "orca_cloud_cosmos_bundle.json").read_text())


def client(answer):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.orcaslicer.com"
        return answer(request)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_share_links():
    for link in ("https://cloud.orcaslicer.com/b/3fad3c38f25f", "cloud.orcaslicer.com/b/3fad3c38f25f?ref=x",
                 "Look: https://cloud.orcaslicer.com/b/3fad3c38f25f/"):
        assert orca_cloud.sharing_token(link) == "3fad3c38f25f"
    for bad in ("https://evil.example/b/3fad3c38f25f", "https://cloud.orcaslicer.com/u/abc", ""):
        with pytest.raises(orca_cloud.OrcaCloudError, match="not an Orca Cloud share link"):
            orca_cloud.sharing_token(bad)


def test_import_cosmos_bundle(tmp_path, lib):  # noqa: F811
    """The public COSMOS bundle (recorded 2026-10-02): 8 printer presets; with only the 0.4 nozzle known here, the
    0.4 ones are stored and the others are reported as skipped."""
    http = client(lambda r: httpx.Response(200, json=BUNDLE) if r.url.path.endswith("/3fad3c38f25f")
                  else httpx.Response(404, json={"error": "not_found"}))
    out = orca_cloud.import_bundle(tmp_path, "https://cloud.orcaslicer.com/b/3fad3c38f25f", lib, http)
    assert out["bundle"]["name"] == "COSMOS for Centauri Carbon 1"
    names = sorted(p["name"] for p in out["imported"])
    assert names == ["Elegoo Centauri Carbon 0.4 nozzle - Cosmos", "Elegoo Centauri Carbon 0.4 nozzle - Cosmos AFC"]
    assert all(p["kind"] == "machine" and p["inherits"] == CC and p["print_start"] for p in out["imported"])
    assert len(out["skipped"]) == 6 and "0.2 nozzle" in " ".join(s["name"] for s in out["skipped"])
    assert sorted(p["name"] for p in user_profiles.list_profiles(tmp_path, lib)) == names
    with pytest.raises(orca_cloud.OrcaCloudError, match="not found or private"):
        orca_cloud.import_bundle(tmp_path, "https://cloud.orcaslicer.com/b/missing1", lib, http)


def test_presets_inheriting_each_other(tmp_path, lib):  # noqa: F811
    """A user preset based on another preset of the same bundle is merged with it before the check."""
    bundle = {"name": "x", "shared_profiles": [
        {"content": {"name": "My CC", "type": "printer", "inherits": CC, "machine_end_gcode": "PRINT_END"}},
        {"content": {"name": "My CC fast", "type": "printer", "inherits": "My CC", "machine_pause_gcode": "PAUSE"}},
        {"content": json.dumps({"name": "My PLA", "type": "filament", "inherits": "Elegoo PLA @ECC",
                                "nozzle_temperature": ["205"]})},
        {"content": {"name": "Other brand", "type": "filament", "inherits": "Unknown PLA @Somewhere"}}]}
    out = orca_cloud.import_bundle(tmp_path, "https://cloud.orcaslicer.com/b/abcdef", lib,
                                   client(lambda r: httpx.Response(200, json=bundle)))
    assert sorted(p["name"] for p in out["imported"]) == ["My CC", "My CC fast", "My PLA"]
    assert [s["name"] for s in out["skipped"]] == ["Other brand"]
    fast = json.loads((tmp_path / "profiles" / next(p["file"] for p in out["imported"] if p["name"] == "My CC fast")).read_text())
    assert fast["inherits"] == CC and fast["machine_end_gcode"] == "PRINT_END" and fast["machine_pause_gcode"] == "PAUSE"


def test_errors(tmp_path, lib):  # noqa: F811
    for answer, msg in ((lambda r: httpx.Response(500), "HTTP 500"),
                        (lambda r: httpx.Response(200, text="<html>"), "no bundle"),
                        (lambda r: httpx.Response(200, json={"name": "empty", "shared_profiles": []}), "no presets"),
                        (lambda r: httpx.Response(200, content=b"x" * (orca_cloud.MAX_BYTES + 1)), "too large")):
        with pytest.raises(orca_cloud.OrcaCloudError, match=msg):
            orca_cloud.import_bundle(tmp_path, "https://cloud.orcaslicer.com/b/abcdef", lib, client(answer))
    only_unknown = {"name": "x", "shared_profiles": [{"content": {"name": "U", "type": "printer", "inherits": "Nope"}}]}
    with pytest.raises(orca_cloud.OrcaCloudError, match="none of the presets"):
        orca_cloud.import_bundle(tmp_path, "https://cloud.orcaslicer.com/b/abcdef", lib,
                                 client(lambda r: httpx.Response(200, json=only_unknown)))


def test_api_endpoint(tmp_path, monkeypatch):
    """POST /api/profiles/orca-cloud stores into the account's config dir (cloud accounts too)."""
    import importlib

    from fastapi.testclient import TestClient
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"api_token: t\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    api = importlib.reload(importlib.import_module("printshare.api"))
    seen = {}

    def fake_import(config_dir, link, lib):
        seen.update(config_dir=config_dir, link=link)
        if "bad" in link:
            raise orca_cloud.OrcaCloudError("not an Orca Cloud share link")
        return {"bundle": {"name": "b"}, "imported": [], "skipped": []}
    monkeypatch.setattr(api.orca_cloud, "import_bundle", fake_import)
    monkeypatch.setattr(api, "_library", lambda: None)
    with TestClient(api.app) as c:
        h = {"Authorization": "Bearer t"}
        r = c.post("/api/profiles/orca-cloud", headers=h, json={"link": "https://cloud.orcaslicer.com/b/abc123"})
        assert r.status_code == 200 and r.json()["bundle"]["name"] == "b" and seen["config_dir"] == str(tmp_path)
        r = c.post("/api/profiles/orca-cloud", headers=h, json={"link": "bad"})
        assert r.status_code == 400 and "share link" in r.json()["detail"]
        assert c.post("/api/profiles/orca-cloud", json={"link": "x"}).status_code == 401
