"""Search and model details for the app (spec MQ-05, MQ-06, MQ-10), one adapter per source (NF-08).

Printables: the website's GraphQL endpoint (no official API) - kept in this module so a change there
only breaks search, not printing by link. Thingiverse: official REST API, needs the app token.
Results link to the model page; the print flow then uses the normal link handling in fetch.py.
MakerWorld: details only (its JSON for the model page) - no public API, search sits behind a bot check and downloads
need the user's own login, so the app sends the user to MakerWorld and the downloaded 3MF comes back by sharing.
"""
from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx

from .fetch import MAKERWORLD_NO_DOWNLOAD, PRINTABLES_GQL, SLICEABLE, THINGIVERSE_API, UA, FetchError

PRINTABLES_MEDIA = "https://media.printables.com/"
SORTS = ("relevant", "popular", "makes")
PAGE_SIZE = 24


@dataclass
class ModelHit:
    source: str
    id: str
    name: str
    url: str
    author: str | None = None
    thumbnail: str | None = None
    likes: int | None = None
    downloads: int | None = None
    makes: int | None = None
    license: str | None = None
    # what to slice when it isn't `url` (Manyfold: "manyfold:<id>", its web page needs a login)
    link: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelDetail(ModelHit):
    images: list[str] = field(default_factory=list)
    summary: str = ""
    description: str = ""
    category: str | None = None
    # the author's recommended print settings (Printables only)
    recommended: dict[str, Any] = field(default_factory=dict)
    files: list[dict[str, Any]] = field(default_factory=list)
    # "server": the server downloads the files (print from the app); "external": only on the source's site (MakerWorld)
    download: str = "server"
    # variants of the model with their own plates/settings (MakerWorld "profiles")
    variants: list[dict[str, Any]] = field(default_factory=list)


def text_from_html(value: str | None, limit: int = 4000) -> str:
    """Model descriptions are HTML; the app shows plain text."""
    if not value:
        return ""
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>", "\n", value)
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s).strip()
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + " …"


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- Printables
def printables_image(file_path: str | None, size: str = "cover/320x240") -> str | None:
    """Printables serves resized JPEGs next to the original: <dir>/thumbs/<size>/<ext>/<stem>.jpg"""
    if not file_path:
        return None
    p = PurePosixPath(file_path)
    ext = p.suffix.lstrip(".").lower() or "jpg"
    return f"{PRINTABLES_MEDIA}{p.parent}/thumbs/{size}/{ext}/{p.stem}.jpg"


class PrintablesSource:
    id = "printables"
    name = "Printables"
    ORDER = {"relevant": "best_match", "popular": "popular", "makes": "makes_count"}
    HIT_FIELDS = ("id name slug likesCount downloadCount makesCount premium price "
                  "image { filePath } user { publicUsername } license { name }")

    def __init__(self, http: httpx.Client):
        self.http = http
        self.available = True

    def _gql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        r = self.http.post(PRINTABLES_GQL, json={"query": query, "variables": variables})
        if r.status_code != 200:
            raise FetchError(f"Printables API error {r.status_code}")
        body = r.json()
        if body.get("errors"):
            raise FetchError(f"Printables API error: {body['errors'][0].get('message')}")
        return body.get("data") or {}

    def _hit(self, m: dict[str, Any]) -> ModelHit:
        return ModelHit(
            source=self.id, id=str(m["id"]), name=m.get("name") or "?",
            url=f"https://www.printables.com/model/{m['id']}-{m.get('slug') or ''}".rstrip("-"),
            author=(m.get("user") or {}).get("publicUsername"),
            thumbnail=printables_image((m.get("image") or {}).get("filePath")),
            likes=_int(m.get("likesCount")), downloads=_int(m.get("downloadCount")),
            makes=_int(m.get("makesCount")), license=(m.get("license") or {}).get("name"))

    def search(self, q: str, page: int, sort: str) -> tuple[list[ModelHit], int | None]:
        data = self._gql(
            "query Search($q: String!, $limit: Int!, $offset: Int!, $order: SearchChoicesEnum) {"
            f" searchPrints2(query: $q, limit: $limit, offset: $offset, ordering: $order) {{ totalCount items {{ {self.HIT_FIELDS} }} }} }}",
            {"q": q, "limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE, "order": self.ORDER[sort]})
        res = data.get("searchPrints2") or {}
        # paid / premium models can't be downloaded on the user's behalf
        items = [m for m in res.get("items") or [] if not m.get("premium") and not m.get("price")]
        return [self._hit(m) for m in items], _int(res.get("totalCount"))

    def detail(self, model_id: str) -> ModelDetail:
        data = self._gql(
            "query Detail($id: ID!) { print(id: $id) {"
            f" {self.HIT_FIELDS} summary description images {{ filePath }} category {{ name }}"
            " nozzleDiameters layerHeights materials { name } weight printDuration"
            " stls { id name fileSize } } }", {"id": model_id})
        m = data.get("print")
        if not m:
            raise FetchError(f"Printables model {model_id} not found (or not public)")
        hit = self._hit(m)
        rec = {
            "nozzle": ", ".join(f"{float(n):g} mm" for n in m.get("nozzleDiameters") or []) or None,
            "layer_height": ", ".join(f"{float(n):g} mm" for n in m.get("layerHeights") or []) or None,
            "material": ", ".join(x["name"] for x in m.get("materials") or [] if x.get("name")) or None,
            "weight_g": float(m["weight"]) if m.get("weight") else None,
            "print_hours": float(m["printDuration"]) if m.get("printDuration") else None,
        }
        return ModelDetail(
            **asdict(hit),
            images=[u for u in (printables_image(i.get("filePath"), "inside/1280x960")
                                for i in m.get("images") or []) if u],
            summary=(m.get("summary") or "").strip(), description=text_from_html(m.get("description")),
            category=(m.get("category") or {}).get("name"),
            recommended={k: v for k, v in rec.items() if v},
            files=[{"name": f["name"], "size": _int(f.get("fileSize"))} for f in m.get("stls") or []])


# ---------------------------------------------------------------- Thingiverse
class ThingiverseSource:
    id = "thingiverse"
    name = "Thingiverse"
    ORDER = {"relevant": "relevant", "popular": "popular", "makes": "makes"}

    def __init__(self, http: httpx.Client, token: str):
        self.http = http
        self.token = token
        self.available = bool(token)

    def _get(self, path: str, **params: Any) -> Any:
        if not self.token:
            raise FetchError("Thingiverse needs an app token (thingiverse_token in config.yaml)")
        r = self.http.get(f"{THINGIVERSE_API}{path}", params=params,
                          headers={"Authorization": f"Bearer {self.token}"})
        if r.status_code == 404:
            raise FetchError("Thingiverse model not found (or not public)")
        if r.status_code != 200:
            raise FetchError(f"Thingiverse API error {r.status_code}: {r.text[:200]}")
        return r.json()

    @staticmethod
    def _image(img: dict[str, Any] | None, kinds: tuple[str, ...]) -> str | None:
        """Thingiverse images come in several sizes: [{"type": "display", "size": "large", "url": …}]"""
        sizes = (img or {}).get("sizes") or []
        for kind in kinds:
            t, s = kind.split(":")
            for x in sizes:
                if x.get("type") == t and x.get("size") == s and x.get("url"):
                    return x["url"]
        return (img or {}).get("url")

    def _hit(self, t: dict[str, Any]) -> ModelHit:
        lic = t.get("license")
        return ModelHit(
            source=self.id, id=str(t["id"]), name=html.unescape(t.get("name") or "?"),
            url=t.get("public_url") or f"https://www.thingiverse.com/thing:{t['id']}",
            author=(t.get("creator") or {}).get("name"),
            thumbnail=self._image(t.get("default_image"), ("preview:large", "display:medium"))
            or t.get("preview_image") or t.get("thumbnail"),
            likes=_int(t.get("like_count")), downloads=_int(t.get("download_count")),
            makes=_int(t.get("make_count")), license=lic if isinstance(lic, str) else None)

    def search(self, q: str, page: int, sort: str) -> tuple[list[ModelHit], int | None]:
        data = self._get(f"/search/{quote(q, safe='')}",
                         type="things", page=page, per_page=PAGE_SIZE, sort=self.ORDER[sort])
        hits = data.get("hits") if isinstance(data, dict) else data
        items = [t for t in hits or [] if isinstance(t, dict) and "id" in t and not t.get("is_nsfw")
                 and not t.get("is_private")]
        return [self._hit(t) for t in items], _int(data.get("total")) if isinstance(data, dict) else None

    def detail(self, thing_id: str) -> ModelDetail:
        t = self._get(f"/things/{thing_id}")
        hit = self._hit(t)
        try:
            imgs = self._get(f"/things/{thing_id}/images")
        except FetchError:
            imgs = []
        try:
            files = self._get(f"/things/{thing_id}/files")
        except FetchError:
            files = []
        return ModelDetail(
            **asdict(hit),
            images=[u for u in (self._image(i, ("display:large", "preview:featured", "display:medium"))
                                for i in imgs or [] if isinstance(i, dict)) if u] or
                   ([hit.thumbnail] if hit.thumbnail else []),
            summary="", description=text_from_html(t.get("description_html") or t.get("description")),
            category=None, recommended={},
            files=[{"name": f.get("name"), "size": _int(f.get("size"))} for f in files or []
                   if isinstance(f, dict) and f.get("name")])


# ---------------------------------------------------------------- MakerWorld
class MakerWorldSource:
    id = "makerworld"
    name = "MakerWorld"
    available = True
    searchable = False          # behind a bot check: no search from the server
    API = "https://makerworld.com/api/v1/design-service/design/"

    def __init__(self, http: httpx.Client):
        self.http = http

    def search(self, q: str, page: int, sort: str) -> tuple[list[ModelHit], int | None]:
        raise FetchError("MakerWorld can't be searched from here - open makerworld.com and share a model link")

    def detail(self, design_id: str) -> ModelDetail:
        try:
            r = self.http.get(self.API + design_id, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise FetchError(f"MakerWorld API error: {e.__class__.__name__}") from e
        if r.status_code == 404:
            raise FetchError(f"MakerWorld model {design_id} not found")
        try:
            d = r.json() if r.status_code == 200 else None
        except ValueError:
            d = None
        if not isinstance(d, dict) or "id" not in d:
            raise FetchError(f"MakerWorld API error: HTTP {r.status_code}")
        if d.get("nsfw"):
            raise FetchError(f"MakerWorld model {design_id} not found")
        ext = d.get("designExtension") or {}
        images = [p["url"] for p in ext.get("design_pictures") or [] if isinstance(p, dict) and p.get("url")]
        if d.get("coverUrl"):          # the cover first (the picture people know from the link preview)
            images = [d["coverUrl"]] + [u for u in images if u != d["coverUrl"]]
        variants = []
        for i in d.get("instances") or []:
            fil = [f for f in i.get("instanceFilaments") or [] if isinstance(f, dict)]
            variants.append({
                "id": i.get("id"), "title": i.get("title") or "", "default": i.get("id") == d.get("defaultInstanceId"),
                "weight_g": _int(i.get("weight")),
                "print_hours": round(i["prediction"] / 3600, 2) if isinstance(i.get("prediction"), (int, float)) else None,
                "materials": sorted({str(f.get("type")) for f in fil if f.get("type")}),
                "colors": [str(f.get("color")) for f in fil if f.get("color")],
                "needs_ams": bool(i.get("needAms")),
            })
        default = next((v for v in variants if v["default"]), variants[0] if variants else {})
        rec = {"material": ", ".join(default.get("materials") or []) or None, "weight_g": default.get("weight_g"),
               "print_hours": default.get("print_hours")}
        slug = d.get("slug") or ""
        creator = d.get("designCreator") or {}
        return ModelDetail(
            source=self.id, id=str(d["id"]), name=d.get("title") or f"MakerWorld {design_id}",
            url=f"https://makerworld.com/en/models/{d['id']}" + (f"-{slug}" if slug else ""),
            author=creator.get("name"), thumbnail=d.get("coverUrl"), likes=_int(d.get("likeCount")),
            downloads=_int(d.get("downloadCount")), makes=_int(d.get("printCount")), license=d.get("license"),
            images=images[:20], summary="", description=text_from_html(d.get("summary")),
            category=next((c.get("name") for c in d.get("categories") or [] if c.get("name")), None),
            recommended={k: v for k, v in rec.items() if v}, files=[], download="external", variants=variants)


# ---------------------------------------------------------------- Manyfold (own library, home servers only)
class ManyfoldSource:
    id = "manyfold"
    name = "Manyfold"
    available = True
    searchable = True

    def __init__(self, client) -> None:
        self.client = client

    def _images(self, mid: str, m: dict[str, Any]) -> list[str]:
        """Image files of the model as proxy URLs of this server (the app can't log in to Manyfold), preview first."""
        from .manyfold import file_id
        preview = (m.get("preview_file") or {}).get("@id")
        parts = [p for p in m.get("hasPart") or [] if isinstance(p, dict) and p.get("@id")
                 and str(p.get("encodingFormat") or "").startswith("image/") and p.get("encodingFormat") != "image/svg+xml"]
        parts.sort(key=lambda p: p["@id"] != preview)
        return [f"/api/manyfold/image/{mid}/{file_id(p['@id'])}" for p in parts][:20]

    def _hit(self, mid: str, m: dict[str, Any]) -> ModelHit:
        lic = m.get("spdx:license") or {}
        imgs = self._images(mid, m)
        return ModelHit(source=self.id, id=mid, name=str(m.get("name") or mid), url=f"{self.client.base}/models/{mid}",
                        thumbnail=imgs[0] if imgs else None, license=lic.get("licenseId") if isinstance(lic, dict) else None,
                        link=f"manyfold:{mid}")

    def search(self, q: str, page: int, sort: str) -> tuple[list[ModelHit], int | None]:
        words = q.lower().split()
        found = [m for m in self.client.models() if all(w in m["name"].lower() for w in words)]
        if sort == "relevant":
            found.sort(key=lambda m: (not m["name"].lower().startswith(words[0]) if words else False, m["name"].lower()))
        chunk = found[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
        from concurrent.futures import ThreadPoolExecutor

        def detail(m: dict[str, str]) -> ModelHit:
            try:
                return self._hit(m["id"], self.client.model(m["id"]))
            except FetchError:
                return ModelHit(source=self.id, id=m["id"], name=m["name"], url=f"{self.client.base}/models/{m['id']}",
                                link=f"manyfold:{m['id']}")
        with ThreadPoolExecutor(max_workers=6) as pool:
            hits = list(pool.map(detail, chunk))
        return hits, len(found)

    def detail(self, mid: str) -> ModelDetail:
        from .manyfold import file_name, is_sliceable
        m = self.client.model(mid)
        hit = self._hit(mid, m)
        files = [{"name": file_name(p), "size": None} for p in m.get("hasPart") or []
                 if isinstance(p, dict) and is_sliceable(p)]
        keywords = [str(k) for k in m.get("keywords") or []]
        return ModelDetail(**asdict(hit), images=self._images(mid, m), summary=str(m.get("caption") or "").strip(),
                           description=text_from_html(m.get("description")), category=", ".join(keywords[:5]) or None,
                           recommended={}, files=files)


# ---------------------------------------------------------------- facade
class Search:
    def __init__(self, thingiverse_token: str = "", timeout: float = 20.0, http: httpx.Client | None = None,
                 manyfold=None):
        self.http = http or httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})
        self.manyfold = manyfold
        sources = [PrintablesSource(self.http), ThingiverseSource(self.http, thingiverse_token), MakerWorldSource(self.http)]
        if manyfold is not None:
            sources.append(ManyfoldSource(manyfold))
        self.sources = {s.id: s for s in sources}

    def list_sources(self) -> list[dict[str, Any]]:
        """Sources for the search tabs (MakerWorld only has model pages: left out, older apps would offer a search)."""
        return [{"id": s.id, "name": s.name, "available": s.available} for s in self.sources.values()
                if getattr(s, "searchable", True)]

    def _source(self, source: str):
        s = self.sources.get(source)
        if s is None:
            raise FetchError(f"unknown source {source!r}")
        return s

    def search(self, source: str, q: str, page: int = 1, sort: str = "relevant") -> dict[str, Any]:
        q = q.strip()
        if not q:
            raise FetchError("empty search")
        if sort not in SORTS:
            raise FetchError(f"sort must be one of {', '.join(SORTS)}")
        hits, total = self._source(source).search(q, max(1, page), sort)
        more = len(hits) > 0 and (total is None or page * PAGE_SIZE < total)
        return {"results": [h.as_dict() for h in hits], "total": total, "page": page, "has_more": more}

    def detail(self, source: str, model_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"\d{1,12}" if source != "manyfold" else r"[A-Za-z0-9_-]{1,64}", model_id):
            raise FetchError("invalid model id")
        d = self._source(source).detail(model_id)
        out = asdict(d)
        out["files"] = [f | {"sliceable": str(f["name"]).lower().endswith(SLICEABLE)} for f in d.files]
        return out
