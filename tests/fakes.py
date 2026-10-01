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
        self.params: list[dict] = []          # Cmd 403 payloads (temperatures, fans, light, speed)
        self.rest_status = rest_status  # 0 idle, 8 stopped, 9 completed (after the previous print)
        self.printing: str | None = None

    def _status(self) -> str:
        if self.printing:
            st = {"CurrentStatus": [1], "PrintInfo": {"Status": 13, "Filename": self.printing,
                  "Progress": 42, "CurrentLayer": 5, "TotalLayer": 100, "PrintSpeedPct": 100}}
        else:
            st = {"CurrentStatus": [0], "TempOfNozzle": 25.0, "TempTargetNozzle": 0, "TempOfHotbed": 24.0,
                  "TempTargetHotbed": 0, "PrintInfo": {"Status": self.rest_status, "Filename": "", "PrintSpeedPct": 100}}
        # as seen live on Thomas' CC1 (V0.3.0-o, 2026-09-30)
        st.update({"TempOfBox": 23.1, "TempTargetBox": 0,
                   "CurrentFanSpeed": {"ModelFan": 0, "AuxiliaryFan": 0, "BoxFan": 0},
                   "LightStatus": {"SecondLight": 1, "RgbLight": [0, 0, 0]}})
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
            elif inner["Cmd"] == 403:
                self.params.append(inner["Data"])
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


def test_jpeg(width: int = 1280, height: int = 720, color=(40, 90, 200)) -> bytes:
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


async def mjpeg(request: web.Request, frames: int = 3) -> web.StreamResponse:
    """MJPEG like the Centauri (:3031/video) or ustreamer: multipart/x-mixed-replace."""
    resp = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=--foo"})
    await resp.prepare(request)
    frame = test_jpeg(640, 360)
    for _ in range(frames):
        await resp.write(b"----foo\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame) + frame + b"\r\n")
    return resp


class FakeMoonraker:
    def __init__(self, port: int = 7125, afc: bool = False, recorded: dict | None = None) -> None:
        """recorded: objects list + object status captured from a real printer (tests/data/*.json)."""
        self.recorded = recorded
        self.port = port
        self.uploads: list[dict] = []
        self.actions: list[str] = []
        self.state = "printing"
        self.afc = afc
        self.scripts: list[str] = []
        # Moonraker's [spoolman] module: None = not configured (404), else the active spool id
        self.spoolman: dict | None = None
        self.webcams = [{"name": "cam", "enabled": True, "service": "mjpegstreamer-adaptive",
                         "stream_url": "/webcam/?action=stream", "snapshot_url": "/webcam/?action=snapshot"}]
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
            "gcode_move": {"speed_factor": 1.0},
            "fan": {"speed": 0.5},
            "fan_generic aux_fan": {"speed": 0.0},
            "led case": {"color_data": [[1.0, 1.0, 1.0, 1.0]]},
            "temperature_sensor chamber": {"temperature": 31.5},
            "configfile": {"settings": {"extruder": {"max_temp": 320}, "heater_bed": {"max_temp": 110}}},
        }
        if self.recorded:
            objs.update({o: self.recorded["status"].get(o, {}) for o in self.recorded["objects"]})
        if self.afc:
            objs["AFC"] = {"current_load": "lane1", "lanes": list(AFC_LANES), "units": ["CANVAS CANVAS_1"]}
            objs.update({f"AFC_stepper {name}": dict(ln, name=name) for name, ln in AFC_LANES.items()})
        return objs

    async def gcode_script(self, request: web.Request) -> web.Response:
        self.scripts.append(request.query["script"])
        return web.json_response({"result": "ok"})

    async def temperature_store(self, request: web.Request) -> web.Response:
        # like Moonraker: one value per second, oldest first
        n = 1200
        return web.json_response({"result": {
            "extruder": {"temperatures": [20 + i * 0.15 for i in range(n)], "targets": [200.0] * n},
            "heater_bed": {"temperatures": [20 + i * 0.03 for i in range(n)], "targets": [60.0] * n},
            "temperature_sensor chamber": {"temperatures": [25.0] * n}}})

    async def webcams_list(self, request: web.Request) -> web.Response:
        return web.json_response({"result": {"webcams": self.webcams}})

    async def webcam(self, request: web.Request) -> web.StreamResponse:
        if request.query.get("action") == "snapshot":
            return web.Response(body=test_jpeg(), content_type="image/jpeg")
        return await mjpeg(request)

    async def spoolman_status(self, request: web.Request) -> web.Response:
        if self.spoolman is None:
            return web.json_response({"error": {"code": 404, "message": "Not Found"}}, status=404)
        return web.json_response({"result": {"spoolman_connected": True, "pending_reports": [],
                                             "spool_id": self.spoolman.get("spool_id")}})

    async def spoolman_spool(self, request: web.Request) -> web.Response:
        if self.spoolman is None:
            return web.json_response({"error": {"code": 404, "message": "Not Found"}}, status=404)
        self.spoolman["spool_id"] = (await request.json()).get("spool_id")
        return web.json_response({"result": {"spool_id": self.spoolman["spool_id"]}})

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
        app.router.add_get("/server/webcams/list", self.webcams_list)
        app.router.add_post("/printer/gcode/script", self.gcode_script)
        app.router.add_get("/server/temperature_store", self.temperature_store)
        app.router.add_get("/webcam/", self.webcam)
        app.router.add_get("/server/spoolman/status", self.spoolman_status)
        app.router.add_post("/server/spoolman/spool_id", self.spoolman_spool)
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
        self.posts: list[tuple[str, dict]] = []

    @web.middleware
    async def auth(self, request: web.Request, handler):
        # on OctoPi the webcam (mjpg-streamer behind /webcam/) needs no API key
        if not request.path.startswith("/webcam/") and request.headers.get("X-Api-Key") != self.api_key:
            return web.json_response({"error": "Forbidden"}, status=403)
        return await handler(request)

    def routes(self, app: web.Application) -> None:
        app.middlewares.append(self.auth)
        app.router.add_post("/api/files/local", self.upload)
        app.router.add_get("/api/job", self.get_job)
        app.router.add_post("/api/job", self.post_job)
        app.router.add_get("/api/printer", self.printer)
        app.router.add_get("/api/settings", self.settings)
        app.router.add_post("/api/printer/tool", self.tool)
        app.router.add_post("/api/printer/bed", self.bed)
        app.router.add_post("/api/printer/command", self.command)
        app.router.add_get("/webcam/", self.webcam)

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

    async def tool(self, request: web.Request) -> web.Response:
        self.posts.append(("tool", await request.json()))
        return web.Response(status=204)

    async def bed(self, request: web.Request) -> web.Response:
        self.posts.append(("bed", await request.json()))
        return web.Response(status=204)

    async def command(self, request: web.Request) -> web.Response:
        self.posts.append(("command", await request.json()))
        return web.Response(status=204)

    async def settings(self, request: web.Request) -> web.Response:
        # OctoPi default: stream relative, snapshot pointing at the Pi itself
        return web.json_response({"webcam": {"webcamEnabled": True, "streamUrl": "/webcam/?action=stream",
                                             "snapshotUrl": f"http://127.0.0.1:{self.port}/webcam/?action=snapshot"}})

    async def webcam(self, request: web.Request) -> web.StreamResponse:
        if request.query.get("action") == "snapshot":
            return web.Response(body=test_jpeg(320, 240), content_type="image/jpeg")
        return await mjpeg(request)

    async def printer(self, request: web.Request) -> web.Response:
        if not self.connected:
            return web.Response(status=409, text="Printer is not operational")
        import time
        temps = {"tool0": {"actual": 214.8, "target": 215.0}, "bed": {"actual": 60.1, "target": 60.0}}
        if request.query.get("history") == "true":
            temps["history"] = [{"time": int(time.time()) - 20, "tool0": {"actual": 200.0, "target": 215.0},
                                 "bed": {"actual": 58.0, "target": 60.0}},
                                {"time": int(time.time()), "tool0": {"actual": 214.8, "target": 215.0},
                                 "bed": {"actual": 60.1, "target": 60.0}}]
        return web.json_response({
            "temperature": temps,
            "state": {"text": "Printing" if self.printing else "Operational", "flags": {
                "operational": True, "printing": bool(self.printing) and not self.paused, "paused": self.paused,
                "pausing": False, "cancelling": False, "error": False, "ready": not self.printing,
                "closedOrError": False}}})


class FakeHomeAssistant(_FakeHTTP):
    """Home Assistant REST API (developers.home-assistant.io/docs/api/rest) with one smart plug (issue #9)."""

    def __init__(self, port: int = 8123, token: str = "ha-token") -> None:
        self.port, self.token = port, token
        self.states = {"switch.drucker": "off", "light.werkstatt": "on", "sensor.temp": "21.5",
                       "switch.kaputt": "unavailable"}
        self.names = {"switch.drucker": "Drucker-Steckdose", "light.werkstatt": "Werkstatt"}
        self.calls: list[tuple[str, str]] = []

    def routes(self, app: web.Application) -> None:
        app.router.add_get("/api/", self.api_root)
        app.router.add_get("/api/states", self.all_states)
        app.router.add_get("/api/states/{entity}", self.one_state)
        app.router.add_post("/api/services/{domain}/{service}", self.service)

    def _ok(self, request: web.Request) -> bool:
        return request.headers.get("Authorization") == f"Bearer {self.token}"

    def _entity(self, e: str) -> dict:
        return {"entity_id": e, "state": self.states[e], "attributes": {"friendly_name": self.names.get(e, e)}}

    async def api_root(self, request: web.Request) -> web.Response:
        if not self._ok(request):
            return web.Response(status=401, text="401: Unauthorized")
        return web.json_response({"message": "API running."})

    async def all_states(self, request: web.Request) -> web.Response:
        if not self._ok(request):
            return web.Response(status=401)
        return web.json_response([self._entity(e) for e in self.states])

    async def one_state(self, request: web.Request) -> web.Response:
        if not self._ok(request):
            return web.Response(status=401)
        e = request.match_info["entity"]
        if e not in self.states:
            return web.json_response({"message": "Entity not found."}, status=404)
        return web.json_response(self._entity(e))

    async def service(self, request: web.Request) -> web.Response:
        if not self._ok(request):
            return web.Response(status=401)
        body = await request.json()
        e, service = body["entity_id"], request.match_info["service"]
        self.calls.append((service, e))
        if e in self.states and self.states[e] != "unavailable":
            self.states[e] = {"turn_on": "on", "turn_off": "off"}.get(service, self.states[e])
        return web.json_response([self._entity(e)] if e in self.states else [])


class FakeSpoolman(_FakeHTTP):
    """Spoolman REST API v1 (https://donkie.github.io/Spoolman/): spools with filament + vendor, bookings via /use.
    Only used by the app's tests (the app talks to Spoolman itself)."""

    def __init__(self, port: int = 7912) -> None:
        self.port = port
        self.runner = None
        self.uses: list[tuple[int, float]] = []
        vendor = {"id": 1, "registered": "2026-01-01T00:00:00", "name": "Elegoo", "extra": {}}

        def spool(i, name, material, color, remaining, archived=False):
            return {"id": i, "registered": "2026-01-01T00:00:00", "archived": archived, "extra": {},
                    "used_weight": 1000 - remaining, "used_length": 0, "remaining_weight": remaining,
                    "initial_weight": 1000, "location": "Shelf", "last_used": None,
                    "filament": {"id": i, "registered": "2026-01-01T00:00:00", "name": name, "material": material,
                                 "vendor": vendor, "density": 1.24, "diameter": 1.75, "color_hex": color, "extra": {}}}
        self.spools = {3: spool(3, "PLA Black", "PLA", "000000", 812.4), 4: spool(4, "PETG White", "PETG", "FFFFFFFF", 6.0),
                       5: spool(5, "Old", "PLA", "FF0000", 100, archived=True)}

    def routes(self, app: web.Application) -> None:
        async def info(request):
            return web.json_response({"version": "0.22.1", "debug_mode": False, "automatic_backups": True,
                                      "data_dir": "/data", "logs_dir": "/logs", "backups_dir": "/b",
                                      "db_type": "sqlite", "external_db_name": ""})

        async def spool_list(request):
            archived = request.query.get("allow_archived") == "true"
            return web.json_response([s for s in self.spools.values() if archived or not s["archived"]])

        async def use(request):
            sid = int(request.match_info["id"])
            if sid not in self.spools:
                return web.json_response({"message": "not found"}, status=404)
            body = await request.json()
            grams = body.get("use_weight")
            self.uses.append((sid, grams))
            s = self.spools[sid]
            s["used_weight"] += grams
            s["remaining_weight"] = max(0, s["remaining_weight"] - grams)
            return web.json_response(s)
        app.router.add_get("/api/v1/info", info)
        app.router.add_get("/api/v1/spool", spool_list)
        app.router.add_put("/api/v1/spool/{id}/use", use)
