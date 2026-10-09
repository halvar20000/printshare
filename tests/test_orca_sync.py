"""Own presets from an Orca Cloud account (issue #7, printshare/orca_sync.py): pairing, rotating tokens, sync."""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest
import yaml

from printshare import orca_sync, user_profiles

from .test_user_profiles import CC, lib  # noqa: F401 (fixture)


class FakeOrca:
    """Device flow + rotating refresh tokens + sync/pull as described in issue #7."""

    def __init__(self, client_id="app_test"):
        self.client_id = client_id
        self.approved = False
        self.polls = 0
        self.refresh = "oc_ext_rt_1"
        self.spent: set[str] = set()
        self.access = "oc_ext_1"
        self.presets = [
            {"id": "a", "name": "My CC", "content": {"name": "My CC", "type": "printer", "inherits": CC,
                                                      "machine_end_gcode": "PRINT_END"}},
            {"id": "b", "name": "My PLA", "content": '{"name": "My PLA", "type": "filament", '
                                                     '"inherits": "Elegoo PLA @ECC", "nozzle_temperature": ["205"]}'},
            {"id": "c", "name": "X1C", "content": {"name": "X1C", "type": "printer", "inherits": "Bambu Lab X1 Carbon"}}]
        self.seen_ua: set[str] = set()

    def handler(self, r: httpx.Request) -> httpx.Response:
        self.seen_ua.add(r.headers.get("user-agent", ""))
        form = dict(httpx.QueryParams(r.content.decode())) if r.method == "POST" else {}
        if r.url.path == "/oauth/device/code":
            if form.get("client_id") != self.client_id:
                return httpx.Response(400, json={"error": "invalid_client", "error_description": "unknown"})
            assert form["scope"] == "sync:read"
            return httpx.Response(200, json={"device_code": "dev1", "user_code": "ABCD-1234", "expires_in": 600,
                                             "interval": 1, "verification_uri": "https://cloud.orcaslicer.com/device"})
        if r.url.path == "/oauth/token":
            if form["grant_type"] == orca_sync.DEVICE_GRANT:
                self.polls += 1
                if not self.approved:
                    return httpx.Response(400, json={"error": "authorization_pending"})
                return httpx.Response(200, json={"access_token": self.access, "refresh_token": self.refresh,
                                                 "expires_in": 86400})
            if form["grant_type"] == "refresh_token":
                if form["refresh_token"] in self.spent or form["refresh_token"] != self.refresh:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.spent.add(self.refresh)
                n = len(self.spent) + 1
                self.refresh, self.access = f"oc_ext_rt_{n}", f"oc_ext_{n}"
                return httpx.Response(200, json={"access_token": self.access, "refresh_token": self.refresh,
                                                 "expires_in": 86400})
        if r.url.path == "/api/v1/external/sync/pull":
            if r.headers.get("authorization") != f"Bearer {self.access}":
                return httpx.Response(401, json={"error": {"code": "UNAUTHORIZED", "message": "token"}})
            return httpx.Response(200, json={"next_cursor": "c1", "upserts": self.presets, "deletes": []})
        return httpx.Response(404)


@pytest.fixture
def fake():
    return FakeOrca()


def sync_for(fake, lib):  # noqa: F811
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler),
                             headers={"User-Agent": orca_sync.user_agent("0.42.0")})
    return orca_sync.OrcaSync(lambda: lib, "0.42.0", http=http)


def test_pair_sync_refresh_and_disconnect(tmp_path, fake, lib, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ORCA_CLOUD_CLIENT_ID", raising=False)
    cfg = str(tmp_path)
    s = sync_for(fake, lib)

    async def run():
        with pytest.raises(orca_sync.OrcaSyncError, match="app ID first"):
            await s.start(cfg)
        orca_sync.update(cfg, client_id="wrong")
        with pytest.raises(orca_sync.OrcaSyncError, match="doesn't know this app ID"):
            await s.start(cfg)
        orca_sync.update(cfg, client_id="app_test")
        p = await s.start(cfg)
        assert p["user_code"] == "ABCD-1234" and p["verification_uri"].startswith("https://cloud.orcaslicer.com")
        await asyncio.sleep(2.3)                       # still waiting for the user
        assert fake.polls >= 1 and not orca_sync.status(cfg)["connected"]
        fake.approved = True
        for _ in range(40):
            await asyncio.sleep(0.1)
            if orca_sync.status(cfg)["count"]:
                break
        st = orca_sync.status(cfg)
        assert st["connected"] and st["pending"] is None and st["count"] == 2
        assert [x["name"] for x in st["skipped"]] == ["X1C"]          # base preset unknown to Orca 2.4.2
        names = sorted(p["name"] for p in user_profiles.list_profiles(cfg, lib))
        assert names == ["My CC", "My PLA"]
        assert (tmp_path / orca_sync.FILE).stat().st_mode & 0o777 == 0o600
        # the access token expires → one refresh, the new pair is stored; a spent refresh token is never sent again
        orca_sync.update(cfg, access_expires=time.time() - 1)
        fake.presets = fake.presets[1:]                               # "My CC" deleted in Orca Cloud
        out = await s.sync(cfg)
        assert out["removed"] == [n for n in out["removed"] if "My CC" in n] and len(out["removed"]) == 1
        assert orca_sync.load(cfg)["refresh_token"] == "oc_ext_rt_2" and fake.spent == {"oc_ext_rt_1"}
        await s.sync(cfg)                                             # access token still valid: no refresh
        assert fake.spent == {"oc_ext_rt_1"}
        # pairing revoked on Orca's side → "connect again", tokens forgotten
        orca_sync.update(cfg, access_expires=time.time() - 1)
        fake.refresh = "other"
        with pytest.raises(orca_sync.OrcaSyncError, match="connect again"):
            await s.sync(cfg)
        assert not orca_sync.status(cfg)["connected"]
        assert all(ua.startswith("PocketPrint3D/") for ua in fake.seen_ua)

    asyncio.run(run())
    assert orca_sync.disconnect(cfg, remove_presets=True)["removed"]
    assert orca_sync.load(cfg) == {"client_id": "app_test"}


def test_presets_in_use_are_kept(tmp_path, fake, lib):  # noqa: F811
    cfg = str(tmp_path)
    s = sync_for(fake, lib)
    orca_sync.update(cfg, client_id="app_test", access_token="oc_ext_1", access_expires=time.time() + 999,
                     refresh_token="oc_ext_rt_1")
    out = asyncio.run(s.sync(cfg))
    machine = next(f for f in out["files"] if f.startswith("machine-"))
    user_profiles.write_overlay(cfg, "cc", {"slicing": {"machine_file": machine, "machine": CC}})
    fake.presets = []
    assert asyncio.run(s.sync(cfg))["removed"] == [f for f in out["files"] if f != machine]
    assert (tmp_path / "profiles" / machine).is_file()


def test_client_id_from_server_and_api(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"api_token: t\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\nprinters: []\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    api = importlib.reload(importlib.import_module("printshare.api"))
    c = TestClient(api.app)
    h = {"Authorization": "Bearer t"}
    monkeypatch.delenv("ORCA_CLOUD_CLIENT_ID", raising=False)
    assert c.get("/api/orca-cloud", headers=h).json()["client_id"] is None
    assert c.put("/api/orca-cloud", headers=h, json={"client_id": "has space"}).status_code == 400
    assert c.put("/api/orca-cloud", headers=h, json={"client_id": " app_mine "}).json()["client_id"] == "app_mine"
    assert c.post("/api/orca-cloud/sync", headers=h).status_code == 409                  # not connected
    st = yaml.safe_load((tmp_path / orca_sync.FILE).read_text())
    assert st == {"client_id": "app_mine"}
    monkeypatch.setenv("ORCA_CLOUD_CLIENT_ID", "oc_app_server_wide_1234")
    r = c.get("/api/orca-cloud", headers=h).json()
    assert r["client_id_from"] == "server" and r["client_id"] == "oc_app_…1234"           # masked
    assert c.put("/api/orca-cloud", headers=h, json={"client_id": ""}).json()["client_id_from"] == "server"
    assert "client_id" not in (yaml.safe_load((tmp_path / orca_sync.FILE).read_text()) or {}) \
        if (tmp_path / orca_sync.FILE).exists() else True


def test_quality_presets_of_type_print_are_kept(tmp_path, lib):  # noqa: F811
    # Orca Cloud sends quality presets as "type": "print"; a preset with only its changes has no other hint of its kind
    up = [{"id": "q", "name": "My Quality", "content": {"name": "My Quality", "type": "print", "from": "User",
                                                         "inherits": "0.20mm Standard @Elegoo CC 0.4 nozzle"}}]
    out = orca_sync.store(tmp_path, up, lib)
    assert out["skipped"] == [] and len(out["files"]) == 1 and out["files"][0].startswith("process-")
    assert [p["name"] for p in user_profiles.list_profiles(tmp_path, lib)] == ["My Quality"]


def test_filament_presets_with_a_printer_string_are_offered(tmp_path, lib):  # noqa: F811
    # Orca Cloud sends compatible_printers as Orca's serialised string ('"A";"B"'), not as a JSON list
    up = [{"id": f"f{i}", "name": n, "content": {"name": n, "type": "filament", "from": "User",
                                                  "inherits": "Elegoo PLA @ECC", "compatible_printers": cp}}
          for i, (n, cp) in enumerate([("CC PLA", '"Elegoo Centauri Carbon 0.4 nozzle"'),
                                       ("Two PLA", '"Other Printer";"Elegoo Centauri Carbon 0.4 nozzle"'),
                                       ("Other PLA", '"Other Printer"')])]
    assert orca_sync.store(tmp_path, up, lib)["skipped"] == []
    cc = "Elegoo Centauri Carbon 0.4 nozzle"
    assert user_profiles.compatible_user_presets(lib, tmp_path, "filament", [cc]) == ["CC PLA", "Two PLA"]
    assert user_profiles.resolve_preset(lib, tmp_path, "filament", "Two PLA")["compatible_printers"] == [
        "Other Printer", cc]
    assert user_profiles.printer_list("A;B") == ["A", "B"] and user_profiles.printer_list("") == []


def test_schedule_and_sync_before_preparing(tmp_path, fake, lib, monkeypatch):  # noqa: F811
    cfg = str(tmp_path)
    orca_sync.update(cfg, client_id="app_test", access_token="oc_ext_1", access_expires=time.time() + 3600,
                     refresh_token="oc_ext_rt_1")
    st = orca_sync.status(cfg)
    assert (st["interval_h"], st["on_prepare"], st["intervals"]) == (6, True, [0, 1, 6, 24])   # defaults
    assert orca_sync.due(cfg)                                                 # never synced
    with pytest.raises(orca_sync.OrcaSyncError, match="interval_h"):
        orca_sync.set_schedule(cfg, interval_h=3)
    orca_sync.set_schedule(cfg, interval_h=0)
    assert not orca_sync.due(cfg)                                             # only by hand
    orca_sync.set_schedule(cfg, interval_h=1)
    orca_sync.update(cfg, last_sync=time.time() - 1800)
    assert not orca_sync.due(cfg) and orca_sync.due(cfg, time.time() + 1801)
    s = sync_for(fake, lib)
    pulls = []
    real_pull = s.pull

    async def counting_pull(d):
        pulls.append(d)
        await asyncio.sleep(0.05)
        return await real_pull(d)
    monkeypatch.setattr(s, "pull", counting_pull)

    async def run():
        assert await s.before_prepare(cfg)                                    # last sync 30 min ago → pulled
        assert len(pulls) == 1 and orca_sync.status(cfg)["count"] == 2
        assert not await s.before_prepare(cfg)                                # fresh: not again
        orca_sync.update(cfg, last_sync=time.time() - 3600)
        assert not await s.before_prepare(cfg)                                # tried < 10 min ago
        s._tried.clear()
        orca_sync.set_schedule(cfg, on_prepare=False)
        assert not await s.before_prepare(cfg) and len(pulls) == 1            # switched off
        # the loop and a manual sync at the same time share one pull
        await asyncio.gather(s.sync_once(cfg), s.sync_once(cfg))
        assert len(pulls) == 2

    asyncio.run(run())
    orca_sync.disconnect(cfg)
    assert orca_sync.load(cfg) == {"client_id": "app_test", "interval_h": 1, "on_prepare": False}   # kept


def test_schedule_api(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"api_token: t\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\nprinters: []\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    api = importlib.reload(importlib.import_module("printshare.api"))
    c = TestClient(api.app)
    h = {"Authorization": "Bearer t"}
    assert c.put("/api/orca-cloud/schedule", headers=h, json={"interval_h": 5}).status_code == 400
    r = c.put("/api/orca-cloud/schedule", headers=h, json={"interval_h": 24}).json()
    assert (r["interval_h"], r["on_prepare"]) == (24, True)
    r = c.put("/api/orca-cloud/schedule", headers=h, json={"on_prepare": False}).json()
    assert (r["interval_h"], r["on_prepare"]) == (24, False)
