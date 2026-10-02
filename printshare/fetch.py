"""Download printable model files from Printables, Thingiverse or a direct URL.

Printables has no public API: we use the same GraphQL endpoint as the website,
on behalf of the user, for one model at a time. Files are never re-hosted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

SLICEABLE = (".stl", ".3mf", ".obj", ".step", ".stp")
UA = "PocketPrint3D/0.1 (+https://github.com/halvar20000/printshare)"
PRINTABLES_GQL = "https://api.printables.com/graphql/"
THINGIVERSE_API = "https://api.thingiverse.com"


class FetchError(RuntimeError):
    pass


@dataclass
class RemoteFile:
    source: str          # "printables" | "thingiverse" | "url"
    model_id: str
    file_id: str
    name: str
    size: int | None = None
    kind: str = "stl"     # printables download type

    @property
    def sliceable(self) -> bool:
        return self.name.lower().endswith(SLICEABLE)


MAKERWORLD_LINK = re.compile(r"makerworld\.com(?:\.cn)?/(?:[a-z]{2}(?:-[a-z]{2})?/)?models/(\d+)", re.I)
MAKERWORLD_NO_DOWNLOAD = ("MakerWorld only allows downloads with your own MakerWorld account - open the model in "
                          "MakerWorld, download the 3MF there and share the file with PocketPrint3D")


def parse_source(link: str) -> tuple[str, str]:
    """Return (source, id_or_url) for a model link."""
    link = link.strip()
    if m := re.search(r"printables\.com/(?:[a-z]{2}/)?model/(\d+)", link):
        return "printables", m.group(1)
    if m := re.search(r"thingiverse\.com/thing:(\d+)", link):
        return "thingiverse", m.group(1)
    if m := MAKERWORLD_LINK.search(link):
        return "makerworld", m.group(1)
    if link.startswith(("http://", "https://")):
        return "url", link
    if Path(link).exists():
        return "local", link
    raise FetchError(f"Unrecognised model link: {link}")


class Fetcher:
    def __init__(self, thingiverse_token: str = "", timeout: float = 60.0):
        self.thingiverse_token = thingiverse_token
        self.http = httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})

    # ---------- listing ----------
    def list_files(self, link: str) -> list[RemoteFile]:
        source, ident = parse_source(link)
        if source == "makerworld":
            raise FetchError(MAKERWORLD_NO_DOWNLOAD)
        if source == "printables":
            return self._printables_files(ident)
        if source == "thingiverse":
            return self._thingiverse_files(ident)
        name = Path(unquote(urlparse(ident).path)).name if source == "url" else Path(ident).name
        return [RemoteFile(source, ident, ident, name or "model.stl")]

    def _printables_files(self, model_id: str) -> list[RemoteFile]:
        query = """
        query ModelFiles($id: ID!) {
          model: print(id: $id) {
            id name
            stls { id name fileSize folder }
          }
        }"""
        data = self._gql("ModelFiles", query, {"id": model_id})
        model = (data or {}).get("model")
        if not model:
            raise FetchError(f"Printables model {model_id} not found (or not public)")
        return [RemoteFile("printables", model_id, f["id"], f["name"], f.get("fileSize"), "stl")
                for f in model.get("stls") or []]

    def _thingiverse_files(self, thing_id: str) -> list[RemoteFile]:
        if not self.thingiverse_token:
            raise FetchError("Thingiverse needs an app token (thingiverse_token in config.yaml)")
        r = self.http.get(f"{THINGIVERSE_API}/things/{thing_id}/files",
                          headers={"Authorization": f"Bearer {self.thingiverse_token}"})
        if r.status_code != 200:
            raise FetchError(f"Thingiverse API error {r.status_code}: {r.text[:200]}")
        return [RemoteFile("thingiverse", thing_id, str(f["id"]), f["name"], f.get("size"))
                for f in r.json()]

    # ---------- download ----------
    def download(self, f: RemoteFile, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.\- ]+", "_", f.name).strip() or "model.stl"
        target = dest_dir / safe
        if f.source == "local":
            return Path(f.file_id)
        if f.source == "printables":
            url = self._printables_link(f)
            headers = {}
        elif f.source == "thingiverse":
            url = f"{THINGIVERSE_API}/files/{f.file_id}/download"
            headers = {"Authorization": f"Bearer {self.thingiverse_token}"}
        else:
            url, headers = f.file_id, {}
        with self.http.stream("GET", url, headers=headers) as r:
            if r.status_code != 200:
                raise FetchError(f"Download failed ({r.status_code}) for {f.name}")
            with target.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 16):
                    fh.write(chunk)
        return target

    def _printables_link(self, f: RemoteFile) -> str:
        mutation = """
        mutation GetDownloadLink($id: ID!, $modelId: ID!, $fileType: DownloadFileTypeEnum!, $source: DownloadSourceEnum!) {
          getDownloadLink(id: $id, printId: $modelId, fileType: $fileType, source: $source) {
            ok
            errors { field messages }
            output { link ttl }
          }
        }"""
        data = self._gql("GetDownloadLink", mutation, {
            "id": f.file_id, "modelId": f.model_id, "fileType": f.kind, "source": "model_detail"})
        res = (data or {}).get("getDownloadLink") or {}
        link = (res.get("output") or {}).get("link")
        if not res.get("ok") or not link:
            raise FetchError(f"Printables refused the download link: {res.get('errors')}")
        return link

    def _gql(self, op: str, query: str, variables: dict) -> dict:
        r = self.http.post(PRINTABLES_GQL, json={"operationName": op, "query": query, "variables": variables})
        if r.status_code != 200:
            raise FetchError(f"Printables API error {r.status_code}: {r.text[:200]}")
        body = r.json()
        if body.get("errors"):
            raise FetchError(f"Printables API error: {body['errors'][0].get('message')}")
        return body.get("data") or {}


def choose_file(files: list[RemoteFile], choice: str | int | None) -> RemoteFile:
    """Pick one file: by index (1-based), by (partial) name, or the only sliceable one."""
    candidates = [f for f in files if f.sliceable]
    if not candidates:
        raise FetchError("No sliceable files (STL/3MF/OBJ/STEP) in this model")
    if choice is None or choice == "":
        if len(candidates) == 1:
            return candidates[0]
        # prefer a single 3MF (usually a ready plate) if present
        three = [f for f in candidates if f.name.lower().endswith(".3mf")]
        if len(three) == 1:
            return three[0]
        raise FetchError("Model has several files, choose one: " +
                         "; ".join(f"{i}: {f.name}" for i, f in enumerate(candidates, 1)))
    if isinstance(choice, int) or str(choice).isdigit():
        idx = int(choice)
        if not 1 <= idx <= len(candidates):
            raise FetchError(f"File index {idx} out of range 1..{len(candidates)}")
        return candidates[idx - 1]
    matches = [f for f in candidates if str(choice).lower() in f.name.lower()]
    if len(matches) != 1:
        raise FetchError(f"{len(matches)} files match {choice!r}")
    return matches[0]
