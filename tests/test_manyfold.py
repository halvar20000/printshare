"""Own Manyfold library as a model source (0.21.0) - against a simulated Manyfold API v0 (its OpenAPI description)."""
from __future__ import annotations

import importlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from printshare import manyfold as mf
from printshare.fetch import FetchError, Fetcher, parse_source
from printshare.search import Search

BASE = "http://manyfold.local:3214"
PNG = b"\x89PNG\r\n\x1a\nfake"
MODELS = {f"m{i:03d}": f"Model {i:03d}" for i in range(1, 60)} | {"bnch": "3D Benchy", "clip": "Cable clip (Benchy edition)"}


class FakeManyfold:
    def __init__(self, token="key-1", client=("cid", "secret")):
        self.token, self.client, self.issued, self.calls = token, client, "oauth-token-1", []

    def handler(self, r: httpx.Request) -> httpx.Response:
        self.calls.append(r.url.path)
        if r.url.path == "/oauth/token":
            form = dict(x.split("=") for x in r.content.decode().split("&"))
            if (form.get("client_id"), form.get("client_secret")) != self.client:
                return httpx.Response(401, json={"error": "invalid_client"})
            return httpx.Response(200, json={"access_token": self.issued, "token_type": "Bearer", "expires_in": 7200})
        if r.headers.get("authorization") not in (f"Bearer {self.token}", f"Bearer {self.issued}"):
            return httpx.Response(401, text="Failed to Login")
        p = r.url.path
        if p == "/models":
            assert r.headers["accept"] == mf.ACCEPT
            page = int(r.url.params.get("page", 1))
            items = sorted(MODELS.items(), key=lambda x: x[1])
            chunk = items[(page - 1) * 25:page * 25]
            view = {"@id": f"{BASE}/models?page={page}", "first": "x", "last": "y"}
            if page * 25 < len(items):
                view["next"] = f"{BASE}/models?page={page + 1}"
            return httpx.Response(200, json={"@context": [], "@id": f"{BASE}/models", "@type": "hydra:Collection",
                                             "totalItems": len(items), "view": view,
                                             "member": [{"@id": f"{BASE}/models/{k}", "name": v} for k, v in chunk]})
        if p == "/models/bnch":
            return httpx.Response(200, json={
                "@id": f"{BASE}/models/bnch", "@type": "3DModel", "name": "3D Benchy", "caption": "The jolly torture test",
                "description": "<p>Print me &amp; enjoy</p>", "keywords": ["boat", "test"],
                "spdx:license": {"@type": "spdx:License", "licenseId": "CC-BY-ND-4.0"},
                "preview_file": {"@id": f"{BASE}/models/bnch/model_files/img2"},
                "hasPart": [{"@id": f"{BASE}/models/bnch/model_files/f1", "@type": "3DModel", "name": "benchy", "encodingFormat": "model/stl"},
                            {"@id": f"{BASE}/models/bnch/model_files/f2", "@type": "3DModel", "name": "benchy_multi", "encodingFormat": "model/3mf"},
                            {"@id": f"{BASE}/models/bnch/model_files/img1", "@type": "3DModel", "name": "side", "encodingFormat": "image/jpeg"},
                            {"@id": f"{BASE}/models/bnch/model_files/img2", "@type": "3DModel", "name": "cover", "encodingFormat": "image/png"},
                            {"@id": f"{BASE}/models/bnch/model_files/doc", "@type": "3DModel", "name": "readme", "encodingFormat": "application/pdf"}]})
        if p.startswith("/models/bnch/model_files/"):
            fid = p.rsplit("/", 1)[1]
            fmt = {"f1": "model/stl", "f2": "model/3mf", "img1": "image/jpeg", "img2": "image/png"}.get(fid)
            if not fmt:
                return httpx.Response(404)
            ext = {"model/stl": "stl", "model/3mf": "3mf", "image/jpeg": "jpg", "image/png": "png"}[fmt]
            return httpx.Response(200, json={"@id": f"{BASE}{p}", "encodingFormat": fmt, "filename": f"{fid}.{ext}",
                                             "contentUrl": f"{BASE}/models/bnch/raw/{fid}.{ext}"})
        if p.startswith("/models/bnch/raw/"):
            return httpx.Response(200, content=PNG if p.endswith(".png") else b"solid benchy\nendsolid\n")
        if p.startswith("/models/") and p.split("/")[2] in MODELS:
            mid = p.split("/")[2]
            return httpx.Response(200, json={"@id": f"{BASE}/models/{mid}", "name": MODELS[mid], "hasPart": []})
        return httpx.Response(404)


def client(fake, **cfg):
    return mf.Manyfold(mf.ManyfoldConfig(BASE, **cfg), http=httpx.Client(transport=httpx.MockTransport(fake.handler)))


def test_auth_paging_and_cache():
    fake = FakeManyfold()
    c = client(fake, token="key-1")
    models = c.models()
    assert len(models) == len(MODELS) and models[0] == {"id": "bnch", "name": "3D Benchy"}
    assert fake.calls.count("/models") == 3                    # 61 models, 25 per page
    c.models()
    assert fake.calls.count("/models") == 3                    # cached
    oauth = client(fake, client_id="cid", client_secret="secret")
    assert len(oauth.models()) == len(MODELS) and "/oauth/token" in fake.calls
    with pytest.raises(FetchError, match="refused the API key"):
        client(fake, token="wrong").models()
    with pytest.raises(FetchError, match="refused the app credentials"):
        client(fake, client_id="cid", client_secret="nope").models()
    with pytest.raises(FetchError, match="not set up"):
        mf.Manyfold(mf.ManyfoldConfig(BASE))


def test_search_and_detail():
    fake = FakeManyfold()
    s = Search(manyfold=client(fake, token="key-1"))
    assert "manyfold" in [x["id"] for x in s.list_sources()]
    r = s.search("manyfold", "benchy")
    assert [h["name"] for h in r["results"]] == ["3D Benchy", "Cable clip (Benchy edition)"] and r["total"] == 2
    assert r["results"][0]["thumbnail"] == "/api/manyfold/image/bnch/img2"          # the preview image first
    assert r["results"][0]["link"] == "manyfold:bnch" and r["results"][0]["url"] == f"{BASE}/models/bnch"
    assert s.search("manyfold", "model 059")["total"] == 1 and s.search("manyfold", "model 05")["total"] == 11
    d = s.detail("manyfold", "bnch")
    assert d["images"] == ["/api/manyfold/image/bnch/img2", "/api/manyfold/image/bnch/img1"]
    assert [f["name"] for f in d["files"]] == ["benchy.stl", "benchy_multi.3mf"] and all(f["sliceable"] for f in d["files"])
    assert d["license"] == "CC-BY-ND-4.0" and d["summary"] == "The jolly torture test" and d["category"] == "boat, test"
    assert d["description"] == "Print me & enjoy"
    assert "manyfold" not in [x["id"] for x in Search().list_sources()]


def test_files_and_download(tmp_path):
    fake = FakeManyfold()
    c = client(fake, token="key-1")
    assert parse_source("manyfold:bnch") == ("manyfold", "bnch")
    f = Fetcher(manyfold=c)
    files = f.list_files("manyfold:bnch")
    assert [(x.name, x.file_id) for x in files] == [("benchy.stl", "f1"), ("benchy_multi.3mf", "f2")]
    assert [x.name for x in f.list_files(f"{BASE}/models/bnch")] == ["benchy.stl", "benchy_multi.3mf"]   # its own web address
    p = f.download(files[0], tmp_path)
    assert p.name == "benchy.stl" and p.read_bytes().startswith(b"solid")
    assert c.image("bnch", "img2") == (PNG, "image/png")
    with pytest.raises(FetchError, match="not an image"):
        c.image("bnch", "f1")
    with pytest.raises(FetchError, match="not set up"):
        Fetcher().list_files("manyfold:bnch")


def test_never_follows_other_hosts():
    fake = FakeManyfold()
    c = client(fake, token="key-1")
    with pytest.raises(FetchError, match="another server"):
        c._get("http://169.254.169.254/latest/meta-data")


@pytest.fixture
def home_api(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"api_token: t\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    for k in ("URL", "TOKEN", "CLIENT_ID", "CLIENT_SECRET"):
        monkeypatch.delenv(f"MANYFOLD_{k}", raising=False)
    api = importlib.reload(importlib.import_module("printshare.api"))
    fake = FakeManyfold()
    real = mf.Manyfold.__init__

    def init(self, cfg, http=None):                       # every client of the app talks to the fake
        real(self, cfg, http=httpx.Client(transport=httpx.MockTransport(fake.handler)))
    monkeypatch.setattr(mf.Manyfold, "__init__", init)
    mf._CLIENTS.clear()
    return api, tmp_path


def test_config_api_and_image_proxy(home_api):
    api, tmp = home_api
    h = {"Authorization": "Bearer t"}
    with TestClient(api.app) as c:
        assert c.get("/api/manyfold/config", headers=h).json()["configured"] is False
        assert "manyfold" not in [x["id"] for x in c.get("/api/sources", headers=h).json()]
        r = c.put("/api/manyfold/config", headers=h, json={"url": BASE, "token": "wrong"})
        assert r.status_code == 400 and "API key" in r.json()["detail"]
        assert c.put("/api/manyfold/config", headers=h, json={"url": "ftp://x"}).status_code == 400
        r = c.put("/api/manyfold/config", headers=h, json={"url": BASE + "/", "token": "key-1"})
        assert r.json() == {"configured": True, "url": BASE, "models": len(MODELS)}
        assert oct((tmp / "manyfold.yaml").stat().st_mode & 0o777) == "0o600"
        assert c.get("/api/manyfold/config", headers=h).json() == {"configured": True, "url": BASE, "token_set": True, "client_set": False}
        assert "manyfold" in [x["id"] for x in c.get("/api/sources", headers=h).json()]
        res = c.get("/api/search?source=manyfold&q=benchy", headers=h).json()
        assert res["results"][0]["id"] == "bnch"
        img = c.get("/api/manyfold/image/bnch/img2?token=t")
        assert img.status_code == 200 and img.content == PNG and img.headers["content-type"] == "image/png"
        assert c.get("/api/manyfold/image/bnch/f1", headers=h).status_code == 404
        assert c.get("/api/models/manyfold/bnch", headers=h).json()["link"] == "manyfold:bnch"
        files = c.get("/api/files?link=manyfold:bnch", headers=h).json()
        assert [f["name"] for f in files] == ["benchy.stl", "benchy_multi.3mf"]
        assert c.delete("/api/manyfold/config", headers=h).json() == {"configured": False}
        assert "manyfold" not in [x["id"] for x in c.get("/api/sources", headers=h).json()]


def test_not_in_the_cloud(tmp_path, monkeypatch):
    from .test_cloud import login
    cfg = tmp_path / "config" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text(f"api_token: op\ncloud: true\ncloud_db: {tmp_path / 'c.db'}\nwork_dir: {tmp_path / 'w'}\n"
                   f"gcode_dir: {tmp_path / 'g'}\nmanyfold_url: {BASE}\nmanyfold_token: key-1\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    api = importlib.reload(importlib.import_module("printshare.api"))
    with TestClient(api.app) as c:
        a = login(api, c, "mf@example.com")
        assert c.put("/api/manyfold/config", headers=a, json={"url": BASE, "token": "x"}).status_code == 409
        assert "manyfold" not in [x["id"] for x in c.get("/api/sources", headers=a).json()]
        assert c.get("/api/files?link=manyfold:bnch", headers=a).status_code in (400, 404, 502)
