"""Jobs survive restarts (0.30.0): the job store, cleanup with G-code, and a real restart of the cloud server."""
from __future__ import annotations

import importlib
import time

from fastapi.testclient import TestClient

from printshare.jobstore import JobStore, job_dir

from .test_cloud import cloud, fake_slicing, login, wait  # noqa: F401 - fixture


def job(jid, owner="u1", state="sliced", created=None, gcode=None):
    return {"id": jid, "owner": owner, "state": state, "created": created or time.time(), "log": [], "error": None,
            "kind": "prepare", "request": {"link": "x"}, "result": {"gcode": gcode} if gcode else None}


def test_store_roundtrip_and_interrupted(tmp_path):
    st = JobStore(tmp_path / "jobs.db")
    jobs = {"a": job("a"), "b": job("b", state="slicing"), "c": job("c", state="sending", gcode="/x/c/c.gcode"),
            "d": job("d", state="sending")}
    assert st.sync(jobs) == 4 and st.sync(jobs) == 0            # unchanged: nothing written
    jobs["a"]["log"].append("Sliced")
    assert st.sync(jobs) == 1
    del jobs["d"]
    st.sync(jobs)
    again = JobStore(tmp_path / "jobs.db").load()
    assert set(again) == {"a", "b", "c"} and again["a"]["log"] == ["Sliced"]
    assert again["b"]["state"] == "error" and "server update" in again["b"]["error"]
    assert again["c"]["state"] == "sliced" and "send again" in again["c"]["error"], "sliced G-code stays sendable"


def test_prune_by_count_and_age_with_gcode(tmp_path):
    st = JobStore(tmp_path / "jobs.db", keep_per_owner=2, max_age_days=14)
    now = time.time()
    jobs = {}
    for i in range(4):
        d = tmp_path / "gcode" / "cc" / f"j{i}"
        d.mkdir(parents=True)
        (d / "x.gcode").write_text("G1")
        jobs[f"j{i}"] = job(f"j{i}", created=now - 100 + i, gcode=str(d / "x.gcode"))
    jobs["old"] = job("old", owner="u2", created=now - 15 * 86400)
    jobs["run"] = job("run", owner="u2", state="slicing", created=now - 30 * 86400)
    jobs["other"] = job("other", owner="u2")
    assert job_dir(jobs["j0"]) == tmp_path / "gcode" / "cc" / "j0"
    dropped = st.prune(jobs, now)
    assert sorted(dropped) == ["j0", "j1", "old"]
    assert sorted(jobs) == ["j2", "j3", "other", "run"], "running jobs are never touched, other owners count apart"
    assert not (tmp_path / "gcode" / "cc" / "j0").exists() and (tmp_path / "gcode" / "cc" / "j3").exists()


def test_jobs_survive_a_restart(cloud, monkeypatch, tmp_path):  # noqa: F811
    api = cloud
    fake_slicing(api, monkeypatch, tmp_path)
    with TestClient(api.app) as c:
        h = login(api, c, "anna@example.com")
        assert c.post("/api/printers", json={"name": "CC", "type": "elegoo_sdcp"}, headers=h).status_code == 200
        jid = c.post("/api/jobs", json={"link": "https://www.printables.com/model/1-cube", "printer": "cc"}, headers=h).json()["job"]
        wait(c, h, jid, "sliced")
        time.sleep(api.JOB_SYNC_S + 1)                          # the background loop wrote it
    # "restart": the module is loaded again with the same configuration (the TestClient exit also synced)
    api2 = importlib.reload(api)
    assert jid in api2.JOBS
    with TestClient(api2.app) as c:
        h2 = {"Authorization": h["Authorization"]}
        j = c.get(f"/api/jobs/{jid}", headers=h2).json()
        assert j["state"] == "sliced" and j["result"]["print_time"] == "5m"
        assert [x["id"] for x in c.get("/api/jobs", headers=h2).json()] == [jid]
        assert c.get(f"/api/jobs/{jid}/gcode", headers=h2).status_code == 200
        other = login(api2, c, "ben@example.com")
        assert c.get(f"/api/jobs/{jid}", headers=other).status_code == 404
