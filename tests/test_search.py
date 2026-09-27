"""Model search (MQ-05/06) against mocked Printables / Thingiverse responses."""
from __future__ import annotations

import json

import httpx
import pytest

from printshare.fetch import FetchError
from printshare.search import PAGE_SIZE, Search, printables_image, text_from_html

HIT = {"id": "3161", "name": "3D BENCHY", "slug": "3d-benchy", "likesCount": 5, "downloadCount": 9,
       "makesCount": 2, "premium": False, "price": None,
       "image": {"filePath": "media/prints/3161/images/1_ab/benchy.png"},
       "user": {"publicUsername": "Prusa"}, "license": {"name": "CC0"}}
PAID = {**HIT, "id": "9", "price": "4.99"}
PREMIUM = {**HIT, "id": "10", "premium": True}


def printables(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if "searchPrints2" in body["query"]:
        assert body["variables"]["order"] == "popular" and body["variables"]["limit"] == PAGE_SIZE
        return httpx.Response(200, json={"data": {"searchPrints2": {"totalCount": 30, "items": [HIT, PAID, PREMIUM]}}})
    if body["variables"]["id"] == "404":
        return httpx.Response(200, json={"data": {"print": None}})
    return httpx.Response(200, json={"data": {"print": {
        **HIT, "summary": " Test boat ", "description": "<p>Hello &amp; welcome</p><ul><li>one</li></ul>",
        "images": [{"filePath": "media/prints/3161/images/1_ab/benchy.png"}], "category": {"name": "Test"},
        "nozzleDiameters": ["0.40"], "layerHeights": ["0.20"], "materials": [{"name": "PLA"}],
        "weight": "29.00", "printDuration": "2.46",
        "stls": [{"id": "1", "name": "benchy.stl", "fileSize": 100}, {"id": "2", "name": "readme.pdf", "fileSize": 1}]}}})


def thingiverse(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer tv-token"
    path = request.url.path
    if path.startswith("/search/"):
        assert request.url.raw_path.startswith(b"/search/cable%20clip?") and request.url.params["sort"] == "makes"
        return httpx.Response(200, json={"total": 1, "hits": [
            {"id": 42, "name": "Clip &amp; Hook", "public_url": "https://www.thingiverse.com/thing:42",
             "creator": {"name": "maker"}, "like_count": 7, "thumbnail": "https://cdn/t.jpg",
             "default_image": {"sizes": [{"type": "preview", "size": "large", "url": "https://cdn/pl.jpg"}]}},
            {"id": 43, "name": "nsfw", "is_nsfw": True}]})
    if path == "/things/42":
        return httpx.Response(200, json={"id": 42, "name": "Clip", "license": "Creative Commons - Attribution",
                                         "description_html": "<p>Nice</p>", "creator": {"name": "maker"}})
    if path == "/things/42/images":
        return httpx.Response(200, json=[{"sizes": [{"type": "display", "size": "large", "url": "https://cdn/dl.jpg"}]}])
    if path == "/things/42/files":
        return httpx.Response(200, json=[{"name": "clip.stl", "size": 5}])
    return httpx.Response(404, json={"error": "Not Found"})


def router(request: httpx.Request) -> httpx.Response:
    return printables(request) if "printables" in request.url.host else thingiverse(request)


@pytest.fixture
def search():
    return Search("tv-token", http=httpx.Client(transport=httpx.MockTransport(router)))


def test_printables_search_skips_paid_models(search):
    r = search.search("printables", " benchy ", 1, "popular")
    assert [h["id"] for h in r["results"]] == ["3161"] and r["total"] == 30 and r["has_more"]
    h = r["results"][0]
    assert h["url"] == "https://www.printables.com/model/3161-3d-benchy"
    assert h["thumbnail"] == "https://media.printables.com/media/prints/3161/images/1_ab/thumbs/cover/320x240/png/benchy.jpg"
    assert (h["author"], h["likes"], h["downloads"], h["license"]) == ("Prusa", 5, 9, "CC0")
    assert search.search("printables", "benchy", 2, "popular")["has_more"] is False  # 2*24 >= 30


def test_printables_detail(search):
    d = search.detail("printables", "3161")
    assert d["summary"] == "Test boat" and d["description"] == "Hello & welcome\n• one"
    assert d["images"] == [printables_image("media/prints/3161/images/1_ab/benchy.png", "inside/1280x960")]
    assert d["recommended"] == {"nozzle": "0.4 mm", "layer_height": "0.2 mm", "material": "PLA",
                                "weight_g": 29.0, "print_hours": 2.46}
    assert [(f["name"], f["sliceable"]) for f in d["files"]] == [("benchy.stl", True), ("readme.pdf", False)]
    with pytest.raises(FetchError, match="not found"):
        search.detail("printables", "404")


def test_thingiverse(search):
    r = search.search("thingiverse", "cable clip", 1, "makes")
    assert [h["name"] for h in r["results"]] == ["Clip & Hook"]  # nsfw filtered, html unescaped
    assert r["results"][0]["thumbnail"] == "https://cdn/pl.jpg" and r["has_more"] is False
    d = search.detail("thingiverse", "42")
    assert d["images"] == ["https://cdn/dl.jpg"] and d["license"] == "Creative Commons - Attribution"
    assert d["description"] == "Nice" and d["files"][0]["sliceable"]


def test_validation():
    s = Search("")
    assert {x["id"]: x["available"] for x in s.list_sources()} == {"printables": True, "thingiverse": False}
    with pytest.raises(FetchError, match="token"):
        s.search("thingiverse", "benchy")
    for args in (("printables", ""), ("nowhere", "x"), ("printables", "x", 1, "random")):
        with pytest.raises(FetchError):
            s.search(*args)
    with pytest.raises(FetchError, match="invalid"):
        s.detail("printables", "../1")


def test_text_from_html_limits():
    assert text_from_html("<b>a</b><br>b") == "a\nb"
    assert text_from_html("word " * 2000, limit=20).endswith(" …")
