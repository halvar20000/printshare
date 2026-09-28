"""Fake printers for tests: an SDCP Centauri Carbon and a Moonraker server."""
from __future__ import annotations

import hashlib
import json

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


class FakeMoonraker:
    def __init__(self, port: int = 7125) -> None:
        self.port = port
        self.uploads: list[dict] = []
        self.actions: list[str] = []
        self.state = "printing"
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

    async def query(self, request: web.Request) -> web.Response:
        return web.json_response({"result": {"status": {
            "print_stats": {"state": self.state, "filename": "cube.gcode", "print_duration": 60,
                            "info": {"current_layer": 3, "total_layer": 100}},
            "display_status": {"progress": 0.031},
            "extruder": {"temperature": 210.1, "target": 210},
            "heater_bed": {"temperature": 60.0, "target": 60}}}})

    async def control(self, request: web.Request) -> web.Response:
        self.actions.append(request.match_info["action"])
        return web.json_response({"result": "ok"})

    async def start(self) -> None:
        app = web.Application(client_max_size=64 * 1024 * 1024)
        app.router.add_post("/printer/print/{action}", self.control)
        app.router.add_get("/server/info", self.info)
        app.router.add_post("/server/files/upload", self.upload)
        app.router.add_get("/printer/objects/query", self.query)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", self.port).start()

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
