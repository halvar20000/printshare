"""Web app of the cloud (docs/WEB.md): HttpOnly session cookie, request check, the Expo web build at /."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from .test_cloud import cloud  # noqa: F401 - fixture

APP_HDR = {"X-Requested-With": "pocketprint3d"}


def _code(api, c, email):
    assert c.post("/api/auth/code", json={"email": email}).status_code == 200
    return re.search(r"\d{6}", api.MAILER.sent[-1][1]).group()


def test_session_cookie(cloud):  # noqa: F811
    api = cloud
    with TestClient(api.app, base_url="https://testserver") as c:
        r = c.post("/api/auth/login", json={"email": "web@example.com", "code": _code(api, c, "web@example.com"),
                                             "device": "Firefox", "cookie": True})
        assert r.status_code == 200 and r.json()["token"] is None and r.json()["user"]["email"] == "web@example.com"
        sc = r.headers["set-cookie"].lower()
        for part in ("pp3d_session=pp3d_", "httponly", "secure", "samesite=strict", "path=/"):
            assert part in sc, sc
        # reading works with the cookie alone
        assert c.get("/api/auth/me").json()["email"] == "web@example.com"
        # changes need the app's header (a form or link from another page can't send it)
        r = c.post("/api/printers", json={"name": "CC", "type": "elegoo_sdcp"})
        assert r.status_code == 403
        assert c.post("/api/printers", json={"name": "CC", "type": "elegoo_sdcp"}, headers=APP_HDR).status_code == 200
        # logout ends the session and clears the cookie
        r = c.post("/api/auth/logout", headers=APP_HDR)
        assert r.status_code == 200 and "pp3d_session=" in r.headers["set-cookie"] and "max-age=0" in r.headers["set-cookie"].lower()
        assert c.get("/api/auth/me").status_code == 401
        # the phone app's way (token in the answer, Authorization header) is unchanged
        r = c.post("/api/auth/login", json={"email": "web@example.com", "code": _code(api, c, "web@example.com")})
        assert r.json()["token"].startswith("pp3d_") and "set-cookie" not in r.headers
        assert c.post("/api/printers", json={"name": "P2", "type": "elegoo_sdcp"},
                      headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 200


def test_webapp_served_at_root(cloud, tmp_path):  # noqa: F811
    api = cloud
    web = tmp_path / "webapp"
    (web / "_expo" / "static" / "js" / "web").mkdir(parents=True)
    (web / "index.html").write_text("<!DOCTYPE html><title>PocketPrint3D</title><div id=root></div>")
    (web / "_expo" / "static" / "js" / "web" / "entry-abc.js").write_text("console.log(1)")
    (web / "favicon.ico").write_bytes(b"\0")
    (tmp_path / "secret.txt").write_text("no")
    api.settings.webapp_dir = str(web)
    with TestClient(api.app) as c:
        for path in ("/", "/printers", "/job/abc123", "/settings"):
            r = c.get(path)
            assert r.status_code == 200 and "<div id=root>" in r.text, path
            assert "frame-ancestors 'none'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"
            assert r.headers["cache-control"] == "no-cache"
        r = c.get("/_expo/static/js/web/entry-abc.js")
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        assert c.get("/favicon.ico").status_code == 200
        assert c.get("/_expo/static/js/web/missing.js").status_code == 404
        assert c.get("/../secret.txt").status_code == 404 and c.get("/%2e%2e/secret.txt").status_code == 404
        assert c.get("/api/nothing-here").status_code == 404           # API paths never get the app
        assert c.get("/api/server").json()["cloud"] is True             # API routes still win
    api.settings.webapp_dir = str(tmp_path / "missing")
    with TestClient(api.app) as c:
        assert c.get("/printers").status_code == 404                    # no web build: nothing served
