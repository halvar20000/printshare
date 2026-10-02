"""SpoolmanDB filament presets for adding spools (0.19.0)."""
from __future__ import annotations

import json
import os
import time

import httpx
import pytest

from printshare import filament_db

ENTRIES = [
    {"id": "elegoo_pla_black_1000_175", "manufacturer": "ELEGOO", "name": "Black", "material": "PLA", "density": 1.24,
     "weight": 1000.0, "spool_weight": 160, "diameter": 1.75, "color_hex": "000000", "color_hexes": None,
     "extruder_temp": 210, "bed_temp": 60, "finish": None, "translucent": False, "glow": False},
    {"id": "elegoo_pla_black_250_175", "manufacturer": "ELEGOO", "name": "Black", "material": "PLA", "density": 1.24,
     "weight": 250.0, "spool_weight": 80, "diameter": 1.75, "color_hex": "000000", "color_hexes": None},
    {"id": "elegoo_pla_black_1000_285", "manufacturer": "ELEGOO", "name": "Black", "material": "PLA", "density": 1.24,
     "weight": 1000.0, "spool_weight": 160, "diameter": 2.85, "color_hex": "000000"},
    {"id": "elegoo_petg_silk_1000_285", "manufacturer": "ELEGOO", "name": "Silk Gold", "material": "PETG",
     "weight": 1000.0, "diameter": 2.85, "color_hex": "FFD700"},
    {"id": "esun_pla+_red", "manufacturer": "eSun", "name": "Red", "material": "PLA+", "weight": 1000.0,
     "diameter": 1.75, "color_hex": "FF0000"},
    {"bad": True},
]


def db(tmp_path, answer):
    calls = []

    def handler(request):
        calls.append(request.url)
        return answer(request)
    return filament_db.FilamentDb(tmp_path, httpx.Client(transport=httpx.MockTransport(handler))), calls


def test_condense_and_query(tmp_path):
    d, calls = db(tmp_path, lambda r: httpx.Response(200, json=ENTRIES))
    assert d.brand_list() == [{"name": "ELEGOO", "count": 2}, {"name": "eSun", "count": 1}]
    fil = d.filaments("ELEGOO")
    assert len(fil) == 1 and fil[0]["name"] == "Black" and fil[0]["diameter"] == 1.75
    assert fil[0]["weights"] == [{"weight": 1000.0, "spool_weight": 160}, {"weight": 250.0, "spool_weight": 80}]
    assert [f["name"] for f in d.filaments("ELEGOO", 2.85)] == ["Silk Gold", "Black"]   # by material: PETG, PLA
    with pytest.raises(filament_db.FilamentDbError, match="unknown brand"):
        d.filaments("Nope")
    assert len(calls) == 1                      # downloaded once, then memory


def test_cache_and_offline(tmp_path):
    d, calls = db(tmp_path, lambda r: httpx.Response(200, json=ENTRIES))
    d.brand_list()
    # a new process: the fresh disk copy is used, no download
    d2, calls2 = db(tmp_path, lambda r: httpx.Response(500))
    assert d2.brand_list()[0]["name"] == "ELEGOO" and not calls2
    # an old disk copy + GitHub down: the old copy is still used
    old = time.time() - filament_db.TTL_S - 10
    os.utime(d.cache, (old, old))
    d3, calls3 = db(tmp_path, lambda r: httpx.Response(503))
    assert d3.brand_list()[0]["name"] == "ELEGOO" and len(calls3) == 1
    # nothing at all
    d4, _ = db(tmp_path / "empty", lambda r: httpx.Response(503))
    with pytest.raises(filament_db.FilamentDbError, match="not available"):
        d4.brand_list()


def test_api(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"api_token: t\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    api = importlib.reload(importlib.import_module("printshare.api"))
    d, _ = db(tmp_path / "w" / "cache", lambda r: httpx.Response(200, content=json.dumps(ENTRIES)))
    monkeypatch.setattr(api, "_FILAMENT_DB", d)
    with TestClient(api.app) as c:
        h = {"Authorization": "Bearer t"}
        assert c.get("/api/filament-db/brands", headers=h).json()[1] == {"name": "eSun", "count": 1}
        assert c.get("/api/filament-db/filaments?brand=eSun", headers=h).json()[0]["material"] == "PLA+"
        assert c.get("/api/filament-db/filaments?brand=Nope", headers=h).status_code == 404
        assert c.get("/api/filament-db/brands").status_code == 401
