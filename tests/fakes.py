"""Fake printers for tests: SDCP Centauri Carbon, Moonraker, PrusaLink and OctoPrint servers."""
from __future__ import annotations

import hashlib
import json
import re

from aiohttp import WSMsgType, web

MAINBOARD = "FAKECC0001"


class FakeCentauri:
    """WebSocket on :3030/websocket + chunked upload on :80/uploadFile/upload."""

    def __init__(self, drop_starts: int = 0, rest_status: int = 0) -> None:
        self.chunks: dict[str, bytearray] = {}
        self.md5: dict[str, str] = {}
        self.files: dict[str, bytes] = {}
        self.commands: list[dict] = []
        self.runners: list[web.AppRunner] = []
        # like the real CC1 right after an upload: acknowledge a start (Ack 0) but stay idle
        self.drop_starts = drop_starts
        self.rest_status = rest_status  # 0 idle, 8 stopped, 9 completed (after the previous print)
        self.printing: str | None = None

    def _status(self) -> str:
        if self.printing:
            st = {"CurrentStatus": [1], "PrintInfo": {"Status": 13, "Filename": self.printing,
                  "Progress": 42, "CurrentLayer": 5, "TotalLayer": 100}}
        else:
            st = {"CurrentStatus": [0], "TempOfNozzle": 25.0, "TempTargetNozzle": 0, "TempOfHotbed": 24.0,
                  "TempTargetHotbed": 0, "PrintInfo": {"Status": self.rest_status, "Filename": ""}}
        return json.dumps({"Status": st, "MainboardID": MAINBOARD, "Topic": f"sdcp/status/{MAINBOARD}"})

    async def ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str(json.dumps({"Attributes": {"MainboardID": MAINBOARD, "Name": "Fake CC"},
                                      "MainboardID": MAINBOARD, "Topic": f"sdcp/attributes/{MAINBOARD}"}))
        await ws.send_str(self._status())
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            req = json.loads(msg.data)
            inner = req["Data"]
            self.commands.append(inner)
            data: dict = {"Ack": 0}
            started = False
            if inner["Cmd"] == 128:
                if inner["Data"]["Filename"] not in self.files:
                    data["Ack"] = 2
                elif self.drop_starts:
                    self.drop_starts -= 1
                else:
                    started = True
            elif inner["Cmd"] == 258:
                data["FileList"] = [{"name": f"/local/{n}", "FileSize": len(b), "TotalLayers": 100,
                                     "CreateTime": 0} for n, b in self.files.items()]
            await ws.send_str(json.dumps({
                "Id": req["Id"], "Topic": f"sdcp/response/{MAINBOARD}",
                "Data": {"Cmd": inner["Cmd"], "Data": data, "RequestID": inner["RequestID"],
                         "MainboardID": MAINBOARD, "TimeStamp": 0}}))
            if started:
                self.printing = inner["Data"]["Filename"]
            if started or inner["Cmd"] in (0, 512):
                await ws.send_str(self._status())
        return ws

    async def upload(self, request: web.Request) -> web.Response:
        form = await request.post()
        uid, offset = form["Uuid"], int(form["Offset"])
        f = form["File"]
        buf = self.chunks.setdefault(uid, bytearray())
        assert offset == len(buf), "chunks out of order"
        buf += f.file.read()
        if len(buf) == int(form["TotalSize"]):
            assert hashlib.md5(buf).hexdigest() == form["S-File-MD5"]
            self.files[f.filename] = bytes(buf)
        return web.json_response({"code": "000000", "messages": None, "data": None, "success": True})

    async def start(self) -> None:
        ws_app = web.Application()
        ws_app.router.add_get("/websocket", self.ws)
        up_app = web.Application(client_max_size=4 * 1024 * 1024)
        up_app.router.add_post("/uploadFile/upload", self.upload)
        for app, port in ((ws_app, 3030), (up_app, 80)):
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, "127.0.0.1", port).start()
            self.runners.append(runner)

    async def stop(self) -> None:
        for r in self.runners:
            await r.cleanup()


# 4 CANVAS lanes via AFC (fields as AFC_lane.get_status in AFCProject/AFC-Klipper-Add-On)
AFC_LANES = {
    "lane1": {"map": "T0", "material": "PLA", "color": "#FFFFFF", "filament_name": "Elegoo PLA White", "prep": True,
              "load": True, "tool_loaded": True, "weight": 820, "status": "Tooled", "unit": "CANVAS_1"},
    "lane2": {"map": "T1", "material": "PLA", "color": "#e53935", "filament_name": "Elegoo PLA Red", "prep": True,
              "load": True, "tool_loaded": False, "weight": 400, "status": "Loaded", "unit": "CANVAS_1"},
    "lane3": {"map": "T2", "material": "PETG", "color": "#1E88E5", "filament_name": "", "prep": True,
              "load": True, "tool_loaded": False, "weight": 950, "status": "Loaded", "unit": "CANVAS_1"},
    "lane4": {"map": "T3", "material": "", "color": "", "filament_name": "", "prep": False,
              "load": False, "tool_loaded": False, "weight": 0, "status": "None", "unit": "CANVAS_1"},
}


class FakeMoonraker:
    def __init__(self, port: int = 7125, afc: bool = False) -> None:
        self.port = port
        self.uploads: list[dict] = []
        self.actions: list[str] = []
        self.state = "printing"
        self.afc = afc
        self.runner: web.AppRunner | None = None

    async def info(self, request: web.Request) -> web.Response:
        return web.json_response({"result": {"klippy_state": "ready"}})

    async def upload(self, request: web.Request) -> web.Response:
        form = await request.post()
        f = form["file"]
        data = f.file.read()
        self.uploads.append({"name": f.filename, "root": form.get("root"), "print": form.get("print"),
                             "data": data})
        return web.json_response({"result": {"item": {"path": f.filename, "root": "gcodes"},
                                             "print_started": form.get("print") == "true",
                                             "action": "create_file"}}, status=201)

    def _objects(self) -> dict:
        objs = {
            "print_stats": {"state": self.state, "filename": "cube.gcode", "print_duration": 60,
                            "info": {"current_layer": 3, "total_layer": 100}},
            "display_status": {"progress": 0.031},
            "extruder": {"temperature": 210.1, "target": 210},
            "heater_bed": {"temperature": 60.0, "target": 60},
            "virtual_sdcard": {"progress": 0.03},
        }
        if self.afc:
            objs["AFC"] = {"current_load": "lane1", "lanes": list(AFC_LANES), "units": ["CANVAS CANVAS_1"]}
            objs.update({f"AFC_stepper {name}": dict(ln, name=name) for name, ln in AFC_LANES.items()})
        return objs

    async def objects_list(self, request: web.Request) -> web.Response:
        return web.json_response({"result": {"objects": list(self._objects())}})

    async def query(self, request: web.Request) -> web.Response:
        # like Klipper: only the requested objects, unknown ones are left out
        objs = self._objects()
        return web.json_response({"result": {"status": {k: objs[k] for k in request.query if k in objs}}})

    async def control(self, request: web.Request) -> web.Response:
        self.actions.append(request.match_info["action"])
        return web.json_response({"result": "ok"})

    async def start(self) -> None:
        app = web.Application(client_max_size=64 * 1024 * 1024)
        app.router.add_post("/printer/print/{action}", self.control)
        app.router.add_get("/server/info", self.info)
        app.router.add_post("/server/files/upload", self.upload)
        app.router.add_get("/printer/objects/query", self.query)
        app.router.add_get("/printer/objects/list", self.objects_list)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", self.port).start()

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()


class _FakeHTTP:
    port = 0

    def routes(self, app: web.Application) -> None:
        raise NotImplementedError

    async def start(self) -> None:
        app = web.Application(client_max_size=64 * 1024 * 1024)
        self.routes(app)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", self.port).start()

    async def stop(self) -> None:
        await self.runner.cleanup()


class FakePrusaLink(_FakeHTTP):
    """PrusaLink v1 API (spec/openapi.yaml of prusa3d/Prusa-Link-Web) with HTTP digest auth."""

    REALM, NONCE = "Printer API", "c0ffee42"

    def __init__(self, port: int = 7461, password: str = "secret", api_key: str | None = None,
                 usb: bool = True) -> None:
        self.port, self.password, self.api_key, self.usb = port, password, api_key, usb
        self.files: dict[str, bytes] = {}
        self.actions: list[str] = []
        self.job: dict | None = None
        self.state = "IDLE"

    def _authorized(self, request: web.Request) -> bool:
        if self.api_key and request.headers.get("X-Api-Key") == self.api_key:
            return True
        h = request.headers.get("Authorization", "")
        if not h.startswith("Digest "):
            return False
        f = dict(re.findall(r'(\w+)="?([^",]+)"?', h[7:]))
        ha1 = hashlib.md5(f"{f.get('username')}:{self.REALM}:{self.password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{request.method}:{f.get('uri')}".encode()).hexdigest()
        expected = hashlib.md5(f"{ha1}:{f.get('nonce')}:{f.get('nc')}:{f.get('cnonce')}:{f.get('qop')}:{ha2}".encode()).hexdigest()
        return f.get("username") == "maker" and f.get("response") == expected

    @web.middleware
    async def auth(self, request: web.Request, handler):
        if not self._authorized(request):
            return web.Response(status=401, headers={
                "WWW-Authenticate": f'Digest realm="{self.REALM}", nonce="{self.NONCE}", qop="auth"'})
        return await handler(request)

    def routes(self, app: web.Application) -> None:
        app.middlewares.append(self.auth)
        app.router.add_get("/api/v1/storage", self.storage)
        app.router.add_put("/api/v1/files/{storage}/{path:.*}", self.upload)
        app.router.add_get("/api/v1/status", self.status)
        app.router.add_get("/api/v1/job", self.get_job)
        app.router.add_put("/api/v1/job/{id}/{action}", self.job_action)
        app.router.add_delete("/api/v1/job/{id}", self.job_stop)

    async def storage(self, request: web.Request) -> web.Response:
        return web.json_response({"storage_list": [
            {"name": "USB", "type": "USB", "path": "/usb", "available": self.usb, "read_only": False}]})

    async def upload(self, request: web.Request) -> web.Response:
        if self.job and self.state == "PRINTING":
            return web.json_response({"title": "busy"}, status=409)
        name = request.match_info["path"]
        self.files[f"{request.match_info['storage']}/{name}"] = await request.read()
        if request.headers.get("Print-After-Upload") == "?1":
            self.state = "PRINTING"
            self.job = {"id": 7, "state": "PRINTING", "progress": 12.0, "time_printing": 60, "time_remaining": 440,
                        "file": {"name": name[:8], "display_name": name, "path": "/usb"}}
        return web.Response(status=201)

    async def status(self, request: web.Request) -> web.Response:
        body = {"printer": {"state": self.state, "temp_nozzle": 214.9, "target_nozzle": 215.0,
                            "temp_bed": 59.5, "target_bed": 60.0}}
        if self.job:
            body["job"] = {k: self.job[k] for k in ("id", "progress", "time_remaining", "time_printing")}
        return web.json_response(body)

    async def get_job(self, request: web.Request) -> web.Response:
        return web.json_response(self.job) if self.job else web.Response(status=204)

    async def job_action(self, request: web.Request) -> web.Response:
        if not self.job or int(request.match_info["id"]) != self.job["id"]:
            return web.Response(status=404)
        action = request.match_info["action"]
        self.actions.append(action)
        self.state = {"pause": "PAUSED", "resume": "PRINTING"}.get(action, self.state)
        return web.Response(status=204)

    async def job_stop(self, request: web.Request) -> web.Response:
        if not self.job or int(request.match_info["id"]) != self.job["id"]:
            return web.Response(status=404)
        self.actions.append("stop")
        self.state, self.job = "STOPPED", None
        return web.Response(status=204)


class FakeOctoPrint(_FakeHTTP):
    """OctoPrint REST API (docs.octoprint.org): files, job, printer."""

    def __init__(self, port: int = 7462, api_key: str = "OCTOKEY", connected: bool = True) -> None:
        self.port, self.api_key, self.connected = port, api_key, connected
        self.uploads: list[dict] = []
        self.commands: list[dict] = []
        self.printing: str | None = None
        self.paused = False

    @web.middleware
    async def auth(self, request: web.Request, handler):
        if request.headers.get("X-Api-Key") != self.api_key:
            return web.json_response({"error": "Forbidden"}, status=403)
        return await handler(request)

    def routes(self, app: web.Application) -> None:
        app.middlewares.append(self.auth)
        app.router.add_post("/api/files/local", self.upload)
        app.router.add_get("/api/job", self.get_job)
        app.router.add_post("/api/job", self.post_job)
        app.router.add_get("/api/printer", self.printer)

    async def upload(self, request: web.Request) -> web.Response:
        form = await request.post()
        f = form["file"]
        self.uploads.append({"name": f.filename, "select": form.get("select"), "print": form.get("print"),
                             "data": f.file.read()})
        started = form.get("print") == "true" and self.connected
        if started:
            self.printing = f.filename
        return web.json_response({"done": True, "files": {"local": {"name": f.filename, "path": f.filename}},
                                  "effectiveSelect": form.get("select") == "true", "effectivePrint": started},
                                 status=201)

    async def get_job(self, request: web.Request) -> web.Response:
        state = "Offline" if not self.connected else "Paused" if self.paused else "Printing" if self.printing else "Operational"
        return web.json_response({
            "job": {"file": {"name": self.printing, "display": self.printing}},
            "progress": {"completion": 33.3 if self.printing else None, "printTime": 120, "printTimeLeft": 240},
            "state": state})

    async def post_job(self, request: web.Request) -> web.Response:
        body = await request.json()
        if not self.printing:
            return web.json_response({"error": "No job"}, status=409)
        self.commands.append(body)
        if body["command"] == "cancel":
            self.printing = None
        else:
            self.paused = body.get("action") == "pause"
        return web.Response(status=204)

    async def printer(self, request: web.Request) -> web.Response:
        if not self.connected:
            return web.Response(status=409, text="Printer is not operational")
        return web.json_response({
            "temperature": {"tool0": {"actual": 214.8, "target": 215.0}, "bed": {"actual": 60.1, "target": 60.0}},
            "state": {"text": "Printing" if self.printing else "Operational", "flags": {
                "operational": True, "printing": bool(self.printing) and not self.paused, "paused": self.paused,
                "pausing": False, "cancelling": False, "error": False, "ready": not self.printing,
                "closedOrError": False}}})
