"""Cloud mode (docs/CLOUD.md): e-mail login, accounts kept apart, printers without addresses, limits."""
from __future__ import annotations

import asyncio
import importlib
import json
import re
import time

import pytest
from fastapi.testclient import TestClient

from printshare.cloud import accounts
from printshare.pipeline import JobResult

CC = "Elegoo Centauri Carbon 0.4 nozzle"
ADMIN = {"Authorization": "Bearer operator-token"}


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    root = tmp_path / "orca" / "Elegoo"
    for kind, presets in {
        "machine": [{"name": CC, "printable_area": ["0x0", "256x0", "256x256", "0x256"]},
                    {"name": "Prusa MK4S 0.4 nozzle", "default_print_profile": "0.20mm Standard @Elegoo CC 0.4 nozzle",
                     "default_filament_profile": "Elegoo PLA @ECC"}],
        "process": [{"name": "0.20mm Standard @Elegoo CC 0.4 nozzle", "compatible_printers": [CC]}],
        "filament": [{"name": "Elegoo PLA @ECC", "compatible_printers": [CC]}],
    }.items():
        (root / kind).mkdir(parents=True)
        for p in presets:
            (root / kind / f"{p['name']}.json").write_text(json.dumps(p))
    cfg = tmp_path / "config" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text(f"api_token: operator-token\ncloud: true\ncloud_db: {tmp_path / 'data' / 'cloud.db'}\n"
                   f"work_dir: {tmp_path / 'work'}\ngcode_dir: {tmp_path / 'gcode'}\n"
                   f"orca_profiles_dir: {tmp_path / 'orca'}\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    api = importlib.reload(importlib.import_module("printshare.api"))
    yield api
    monkeypatch.delenv("PRINTSHARE_CONFIG")


def login(api, c, email, device="test phone"):
    assert c.post("/api/auth/code", json={"email": email, "lang": "de"}).status_code == 200
    subject = api.MAILER.sent[-1][1]
    code = re.search(r"\d{6}", subject).group()
    r = c.post("/api/auth/login", json={"email": email, "code": code, "device": device})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def fake_slicing(api, monkeypatch, tmp_path, delay=0.0):
    async def fake_prepare(settings, link, printer_id, file_choice, options, out_name=None, progress=None):
        await asyncio.sleep(delay)
        g = tmp_path / f"{out_name}.gcode"
        g.write_text("G1 X1\n")
        return JobResult(printer_id, "cube.stl", str(g), "5m", 2.0, 0.7, 50, {}, {})
    monkeypatch.setattr(api, "prepare_job", fake_prepare)


def wait(c, h, job, *states):
    for _ in range(200):
        j = c.get(f"/api/jobs/{job}", headers=h).json()
        if j["state"] in states:
            return j
        time.sleep(0.02)
    raise AssertionError(j)


def test_server_info_and_login(cloud):
    api = cloud
    with TestClient(api.app) as c:
        assert c.get("/api/server").json() == {"name": "PrintShare", "version": api.app.version, "cloud": True,
                                               "login": "email"}
        assert c.get("/api/printers").status_code == 401
        assert c.get("/api/printers", headers={"Authorization": "Bearer pp3d_nope"}).status_code == 401
        # code by mail (German), wrong code, then the right one
        assert c.post("/api/auth/code", json={"email": "not-an-address"}).status_code == 400
        r = c.post("/api/auth/code", json={"email": "  Anna@Example.COM ", "lang": "de-DE"})
        assert r.json() == {"sent": True, "email": "anna@example.com"}
        to, subject, body = api.MAILER.sent[-1]
        code = re.search(r"\d{6}", subject).group()
        assert to == "anna@example.com" and "Dein PocketPrint3D-Code" in subject and code in body
        assert c.post("/api/auth/login", json={"email": "anna@example.com", "code": "000000"}).status_code == 401 \
            or code == "000000"
        r = c.post("/api/auth/login", json={"email": "ANNA@example.com", "code": code, "device": "Pixel"})
        tok = r.json()["token"]
        assert tok.startswith("pp3d_") and r.json()["user"]["email"] == "anna@example.com"
        h = {"Authorization": f"Bearer {tok}"}
        me = c.get("/api/auth/me", headers=h).json()
        assert me["email"] == "anna@example.com" and me["printers"] == 0 and me["limits"]["slices_today"] == 0
        assert c.get("/api/info", headers=h).json()["cloud"] is True
        # a code works only once
        assert c.post("/api/auth/login", json={"email": "anna@example.com", "code": code}).status_code == 401
        # logout ends this session
        c.post("/api/auth/logout", headers=h)
        assert c.get("/api/auth/me", headers=h).status_code == 401


def test_code_limits(cloud):
    api = cloud
    db = api.ACCOUNTS
    now = time.time()
    for _ in range(accounts.CODES_PER_EMAIL):
        db.request_code("bob@example.com", "1.2.3.4", now)
    with pytest.raises(accounts.AccountError) as e:
        db.request_code("bob@example.com", "1.2.3.4", now)
    assert e.value.status == 429
    assert db.request_code("bob@example.com", None, now + 901)          # 15 minutes later again
    code = db.request_code("carl@example.com", None, now)
    for _ in range(accounts.CODE_ATTEMPTS):
        with pytest.raises(accounts.AccountError, match="wrong code"):
            db.verify_code("carl@example.com", "999999" if code != "999999" else "111111", now=now)
    with pytest.raises(accounts.AccountError, match="expired"):              # too many attempts
        db.verify_code("carl@example.com", code, now=now)
    code = db.request_code("dora@example.com", None, now)
    with pytest.raises(accounts.AccountError, match="expired"):
        db.verify_code("dora@example.com", code, now=now + accounts.CODE_TTL_S + 1)
    # nothing readable is stored
    rows = db.db.execute("SELECT code_hash FROM login_codes").fetchall() + db.db.execute("SELECT token_hash FROM sessions").fetchall()
    assert all(len(r[0]) == 64 for r in rows)


def test_printers_per_account(cloud):
    api = cloud
    with TestClient(api.app) as c:
        a, b = login(api, c, "a@example.com"), login(api, c, "b@example.com")
        r = c.post("/api/printers", headers=a, json={"name": "Werkstatt CC", "type": "elegoo_sdcp"})
        assert r.status_code == 200, r.text
        cc = r.json()
        assert (cc["id"], cc["type"], cc["machine"], cc["leveling"], cc["cosmos"]) == \
            ("werkstatt-cc", "elegoo_sdcp", CC, True, False)
        r = c.post("/api/printers", headers=a, json={"name": "COSMOS", "type": "moonraker", "cosmos": True})
        assert r.json()["cosmos"] is True
        assert c.post("/api/printers", headers=a, json={"name": "MK4", "type": "prusalink"}).status_code == 400
        assert c.post("/api/printers", headers=a, json={"name": "X", "type": "prusalink", "machine": "Nope"}).status_code == 400
        assert c.post("/api/printers", headers=a, json={"name": "", "type": "moonraker"}).status_code == 400
        assert c.post("/api/printers", headers=a, json={"name": "Y", "type": "bambu"}).status_code == 400
        mk4 = c.post("/api/printers", headers=a, json={"name": "MK4", "type": "prusalink", "machine": "Prusa MK4S 0.4 nozzle"})
        assert mk4.status_code == 200 and mk4.json()["machine"] == "Prusa MK4S 0.4 nozzle"
        assert [p["id"] for p in c.get("/api/printers", headers=a).json()] == ["werkstatt-cc", "cosmos", "mk4"]
        # b sees none of them
        assert c.get("/api/printers", headers=b).json() == []
        assert c.get("/api/printers/werkstatt-cc/options", headers=b).status_code == 404
        assert c.patch("/api/printers/werkstatt-cc", headers=b, json={"name": "mine"}).status_code == 404
        # options work for a's printer; rename keeps the rest
        assert c.get("/api/printers/werkstatt-cc/options", headers=a).json()["defaults"]["filament"] == "Elegoo PLA @ECC"
        r = c.patch("/api/printers/werkstatt-cc", headers=a, json={"name": "Keller", "auto_leveling": False})
        assert (r.json()["name"], r.json()["leveling"], r.json()["type"]) == ("Keller", False, "elegoo_sdcp")
        # the printer itself is only reachable through the app at home
        for method, path in (("get", "/api/printers/werkstatt-cc/status"), ("get", "/api/printers/werkstatt-cc/camera"),
                             ("post", "/api/printers/werkstatt-cc/adjust"), ("get", "/api/printers/werkstatt-cc/power")):
            kw = {"json": {"kind": "fan", "id": "part", "value": 0}} if method == "post" else {}
            r = getattr(c, method)(path, headers=a, **kw)
            assert r.status_code == 409 and "through the app" in r.json()["detail"], (path, r.text)
        assert c.delete("/api/printers/mk4", headers=a).json() == {"deleted": "mk4"}
        assert c.delete("/api/printers/mk4", headers=a).status_code == 404
        # the operator token only sees statistics
        assert c.get("/api/printers", headers=ADMIN).json() == []
        stats = c.get("/api/admin/stats", headers=ADMIN).json()
        assert (stats["users"], stats["printers"]) == (2, 2)
        assert c.get("/api/admin/stats", headers=a).status_code == 403


def test_jobs_uploads_and_limits(cloud, monkeypatch, tmp_path):
    api = cloud
    fake_slicing(api, monkeypatch, tmp_path, delay=0.3)
    with TestClient(api.app) as c:
        a, b = login(api, c, "a@example.com"), login(api, c, "b@example.com")
        for h in (a, b):
            c.post("/api/printers", headers=h, json={"name": "CC", "type": "elegoo_sdcp"})
        up = c.post("/api/uploads", headers=a, params={"name": "cube.stl"}, content=b"solid x\nendsolid x\n").json()
        assert c.get("/api/files", headers=b, params={"link": up["link"]}).status_code == 404   # a's upload
        job = c.post("/api/jobs", headers=a, json={"link": up["link"], "printer": "cc"}).json()["job"]
        # one slicing job at a time per account
        r = c.post("/api/jobs", headers=a, json={"link": up["link"], "printer": "cc"})
        assert r.status_code == 429 and "being sliced" in r.json()["detail"]
        assert wait(c, a, job, "sliced", "error")["state"] == "sliced"
        assert c.get(f"/api/jobs/{job}", headers=b).status_code == 404
        assert c.get("/api/jobs", headers=b).json() == []
        assert c.get(f"/api/jobs/{job}/gcode", headers=a).text == "G1 X1\n"
        assert c.get(f"/api/jobs/{job}/gcode", headers=b).status_code == 404
        # sending happens in the app on the home network
        r = c.post(f"/api/jobs/{job}/send", headers=a, json={"start": False})
        assert r.status_code == 409
        # daily limit
        monkeypatch.setattr(api.settings, "limit_slices_per_day", 2)
        job2 = c.post("/api/jobs", headers=a, json={"link": up["link"], "printer": "cc"}).json()["job"]
        wait(c, a, job2, "sliced", "error")
        r = c.post("/api/jobs", headers=a, json={"link": up["link"], "printer": "cc"})
        assert r.status_code == 429 and "daily limit" in r.json()["detail"]
        assert c.get("/api/auth/me", headers=a).json()["limits"]["slices_today"] == 2
        # upload size limit of the free service
        monkeypatch.setattr(api.settings, "limit_upload_mb", 0)
        assert c.post("/api/uploads", headers=b, params={"name": "x.stl"}, content=b"solid").status_code == 413


def test_delete_account(cloud, monkeypatch, tmp_path):
    api = cloud
    fake_slicing(api, monkeypatch, tmp_path)
    with TestClient(api.app) as c:
        a = login(api, c, "gone@example.com")
        c.post("/api/printers", headers=a, json={"name": "CC", "type": "elegoo_sdcp"})
        up = c.post("/api/uploads", headers=a, params={"name": "cube.stl"}, content=b"solid x\n").json()
        job = c.post("/api/jobs", headers=a, json={"link": up["link"], "printer": "cc"}).json()["job"]
        wait(c, a, job, "sliced")
        me = c.get("/api/auth/me", headers=a).json()
        user_dirs = [tmp_path / d / "users" / me["id"] for d in ("work", "gcode", "config")]
        assert user_dirs[0].exists()
        assert c.delete("/api/auth/account", headers=a).status_code == 400          # needs confirm
        assert c.delete("/api/auth/account", headers=a, params={"confirm": "true"}).json() == {"deleted": True}
        assert c.get("/api/auth/me", headers=a).status_code == 401
        assert not any(d.exists() for d in user_dirs) and job not in api.JOBS
        # the same address later starts a fresh, empty account
        again = login(api, c, "gone@example.com")
        assert c.get("/api/auth/me", headers=again).json()["id"] != me["id"]
        assert c.get("/api/printers", headers=again).json() == []


def test_local_server_has_no_accounts(api_local):
    api = api_local
    with TestClient(api.app) as c:
        assert c.get("/api/server").json()["cloud"] is False
        assert c.post("/api/auth/code", json={"email": "a@example.com"}).status_code == 404
        assert c.post("/api/printers", headers={"Authorization": "Bearer test-token"},
                      json={"name": "x", "type": "moonraker"}).status_code == 409


@pytest.fixture
def api_local(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"api_token: test-token\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    return importlib.reload(importlib.import_module("printshare.api"))


def test_gcode_with_slots_for_the_app(cloud, monkeypatch, tmp_path):
    """In the cloud the app sends the G-code itself: the server rewrites the tools for the chosen AFC slots."""
    api = cloud

    async def fake_prepare(settings, link, printer_id, file_choice, options, out_name=None, progress=None):
        g = tmp_path / "two.gcode"
        g.write_text("PRINT_START EXTRUDER=210 TOOL=0\nT0\nG1 X1\nT1 PURGE_LENGTH=60\nG1 X2\n; T1 in a comment\n")
        return JobResult(printer_id, "two.3mf", str(g), "5m", 2.0, 0.7, 50, {}, {})
    monkeypatch.setattr(api, "prepare_job", fake_prepare)
    with TestClient(api.app) as c:
        a = login(api, c, "a@example.com")
        c.post("/api/printers", headers=a, json={"name": "COSMOS", "type": "moonraker", "cosmos": True})
        up = c.post("/api/uploads", headers=a, params={"name": "two.3mf"}, content=b"x").json()
        job = c.post("/api/jobs", headers=a, json={"link": up["link"], "printer": "cosmos"}).json()["job"]
        wait(c, a, job, "sliced")
        plain = c.get(f"/api/jobs/{job}/gcode", headers=a)
        assert "T1 PURGE_LENGTH" in plain.text and 'filename="two.gcode"' in plain.headers["content-disposition"]
        r = c.get(f"/api/jobs/{job}/gcode", headers=a, params={"lanes": json.dumps({"1": 3, "2": 1})})
        assert r.status_code == 200
        assert r.text.splitlines()[:4] == ["PRINT_START EXTRUDER=210 TOOL=3", "T3", "G1 X1", "T1 PURGE_LENGTH=60"]
        assert "; T1 in a comment" in r.text
        assert c.get(f"/api/jobs/{job}/gcode", headers=a, params={"lanes": '{"1": 99}'}).status_code == 400
        assert c.get(f"/api/jobs/{job}/gcode", headers=a, params={"lanes": "nope"}).status_code == 400


def test_machine_models_and_prusa_printer(cloud):
    """Model list for the app's picker; a cloud Prusa printer slices with that model's own defaults."""
    api = cloud
    with TestClient(api.app) as c:
        a = login(api, c, "prusa@example.com")
        models = c.get("/api/machines", headers=a).json()
        assert {"name": "Prusa MK4S 0.4 nozzle", "vendor": "Elegoo"} in models and {"name": CC, "vendor": "Elegoo"} in models
        r = c.post("/api/printers", headers=a, json={"name": "MK4S", "type": "prusalink", "machine": "Prusa MK4S 0.4 nozzle"})
        assert r.status_code == 200 and r.json()["machine"] == "Prusa MK4S 0.4 nozzle" and r.json()["leveling"] is None
        r = c.post("/api/printers", headers=a, json={"name": "Ender", "type": "octoprint", "machine": CC})
        assert r.status_code == 200 and r.json()["type"] == "octoprint"
        d = c.get("/api/printers/mk4s/options", headers=a).json()["defaults"]
        assert d["filament"] == "Elegoo PLA @ECC" and d["process"] == "0.20mm Standard @Elegoo CC 0.4 nozzle"
