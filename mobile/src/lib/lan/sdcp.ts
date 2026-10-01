// Elegoo Centauri Carbon (stock firmware) on the home Wi-Fi: SDCP over WebSocket :3030 + chunked HTTP upload :80.
// Port of printshare/printers/elegoo.py (pycentauri). The printer answers a status request without its
// MainboardID and sends the ID along, so the app needs no UDP discovery.
import type { PrinterStatus } from "../api";
import type { GcodeFile, LanIo } from "./io";
import { Md5 } from "./md5";
import { kindOf, LanError, sleep, type Lan, type SendOptions } from "./types";

const CHUNK = 1024 * 1024;           // Elegoo's maximum per request
const FILE_TIMEOUT_MS = 20_000;      // a fresh upload shows up in the file list
const START_TIMEOUT_MS = 25_000;     // the printer leaves its resting state
const STATES: Record<number, string> = {
  0: "idle", 1: "homing", 5: "pausing", 6: "paused", 7: "stopping", 8: "stopped", 9: "completed",
  10: "file_checking", 11: "printer_checking", 12: "resuming", 13: "printing", 14: "error", 15: "auto_leveling",
  16: "preheating", 18: "resuming", 20: "heating", 21: "leveling",
};
const AT_REST = new Set([0, 8, 9]);   // idle / stopped / completed: nothing runs (after a print the CC stays in 9)
const START_ACKS: Record<number, string> = {
  1: "the printer is busy", 2: "file not found on the printer", 3: "MD5 check failed",
  4: "the printer could not read the file", 5: "resolution mismatch", 6: "unknown file format",
  7: "the file was sliced for a different printer model",
};

type Raw = Record<string, any>;
const hex = () => Array.from({ length: 16 }, () => Math.floor(Math.random() * 256).toString(16).padStart(2, "0")).join("");

export class SdcpPrinter implements Lan {
  private ws: WebSocket | null = null;
  private mainboard = "";
  private waiting = new Map<string, (msg: Raw) => void>();
  private statusWaiters: ((st: Raw) => void)[] = [];

  constructor(readonly host: string, private io: LanIo, private wsUrl = `ws://${host}:3030/websocket`,
              private httpBase = `http://${host}`) {}

  private open(): Promise<WebSocket> {
    if (this.ws && this.ws.readyState === 1) return Promise.resolve(this.ws);
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.wsUrl);
      const timer = setTimeout(() => { ws.close(); reject(new LanError("printer not reachable on the Wi-Fi")); }, 8000);
      ws.onopen = () => { clearTimeout(timer); this.ws = ws; resolve(ws); };
      ws.onerror = () => { clearTimeout(timer); reject(new LanError("printer not reachable on the Wi-Fi")); };
      ws.onclose = () => { this.ws = null; };
      ws.onmessage = e => this.onMessage(typeof e.data === "string" ? e.data : String(e.data));
    });
  }

  private onMessage(text: string) {
    let msg: Raw;
    try { msg = JSON.parse(text); } catch { return; }      // "pong" and the like
    const data = msg.Data ?? {};
    this.mainboard = msg.MainboardID || data.MainboardID || this.mainboard;
    const topic: string = msg.Topic ?? "";
    if (topic.includes("sdcp/response")) {
      const done = this.waiting.get(data.RequestID);
      if (done) { this.waiting.delete(data.RequestID); done(msg); }
    }
    const status = msg.Status ?? data.Status;
    if (topic.includes("sdcp/status") || status) {
      const waiters = this.statusWaiters.splice(0);
      waiters.forEach(w => w(status ?? {}));
    }
  }

  private async request(cmd: number, payload: Raw = {}, timeoutMs = 8000): Promise<Raw> {
    const ws = await this.open();
    const requestId = hex();
    const answer = new Promise<Raw>((resolve, reject) => {
      const timer = setTimeout(() => { this.waiting.delete(requestId); reject(new LanError("the printer did not answer")); }, timeoutMs);
      this.waiting.set(requestId, m => { clearTimeout(timer); resolve(m); });
    });
    ws.send(JSON.stringify({ Id: hex(), Topic: `sdcp/request/${this.mainboard}`, Data: {
      Cmd: cmd, Data: payload, RequestID: requestId, MainboardID: this.mainboard, TimeStamp: Date.now(), From: 1 } }));
    return answer;
  }

  private async rawStatus(): Promise<Raw> {
    let cancel = () => {};
    const next = new Promise<Raw>((resolve, reject) => {
      const waiter = (st: Raw) => { clearTimeout(timer); resolve(st); };
      const timer = setTimeout(() => { cancel(); reject(new LanError("the printer did not send its status")); }, 8000);
      cancel = () => { clearTimeout(timer); this.statusWaiters = this.statusWaiters.filter(w => w !== waiter); };
      this.statusWaiters.push(waiter);
    });
    try {
      await this.request(0);
    } catch (e) {
      cancel();                   // printer not reachable: no status will come, stop waiting for it
      next.catch(() => {});
      throw e;
    }
    return next;
  }

  async status(): Promise<PrinterStatus> {
    const st = await this.rawStatus();
    const pi = st.PrintInfo ?? {};
    const fans = st.CurrentFanSpeed ?? {}, light = st.LightStatus ?? {};
    const state = STATES[pi.Status] ?? (pi.Status == null ? "idle" : `status_${pi.Status}`);
    return {
      state, kind: kindOf(state), file: pi.Filename || null,
      progress: pi.Progress ?? undefined, layer: pi.CurrentLayer ?? null, layers: pi.TotalLayer ?? null,
      print_duration_s: pi.CurrentTicks ?? null,
      time_remaining_s: pi.TotalTicks && pi.CurrentTicks != null ? Math.max(0, pi.TotalTicks - pi.CurrentTicks) : null,
      nozzle: st.TempOfNozzle ?? null, nozzle_target: st.TempTargetNozzle ?? null,
      bed: st.TempOfHotbed ?? null, bed_target: st.TempTargetHotbed ?? null,
      camera: `http://${this.host}:3031/video`, lanes: [],
      heaters: { nozzle: { actual: st.TempOfNozzle ?? null, target: st.TempTargetNozzle ?? null },
                 bed: { actual: st.TempOfHotbed ?? null, target: st.TempTargetHotbed ?? null },
                 chamber: { actual: st.TempOfBox ?? null, target: st.TempTargetBox ?? null } },
      fans: { part: fans.ModelFan ?? null, aux: fans.AuxiliaryFan ?? null, chamber: fans.BoxFan ?? null },
      lights: "SecondLight" in light ? { light: !!light.SecondLight } : {},
      speed: pi.PrintSpeedPct ?? null,
    };
  }

  private async atRest(): Promise<boolean> {
    const st = await this.rawStatus();
    const code = st.PrintInfo?.Status;
    return (code == null || AT_REST.has(code)) && JSON.stringify(st.CurrentStatus ?? [0]) === "[0]";
  }

  private async upload(file: GcodeFile, onProgress?: (part: number) => void): Promise<void> {
    const data = await file.bytes();
    if (!data.length) throw new LanError("the G-code is empty");
    const md5 = new Md5().update(data).hex();
    const uuid = hex();
    for (let offset = 0; offset < data.length; offset += CHUNK) {
      const chunk = data.subarray(offset, Math.min(offset + CHUNK, data.length));
      const r = await this.io.postChunk(`${this.httpBase}/uploadFile/upload`, {
        Check: "1", "S-File-MD5": md5, Offset: String(offset), Uuid: uuid, TotalSize: String(data.length) },
        "File", file.name, chunk);
      let ok = false;
      try { ok = r.status === 200 && JSON.parse(r.body).code === "000000"; } catch { /* not JSON */ }
      if (!ok) throw new LanError(`the printer refused the upload (HTTP ${r.status})`);
      onProgress?.((offset + chunk.length) / data.length);
    }
  }

  private async waitForFile(name: string): Promise<void> {
    const end = Date.now() + FILE_TIMEOUT_MS;
    while (Date.now() < end) {
      try {
        const r = await this.request(258, { Url: "/local" });
        const files: Raw[] = r.Data?.Data?.FileList ?? [];
        if (files.some(f => String(f.name ?? "").split("/").pop() === name)) return;
      } catch { /* listing is only a readiness hint */ }
      await sleep(1000);
    }
  }

  async send(file: GcodeFile, opts: SendOptions): Promise<void> {
    opts.onStep?.("upload");
    await this.upload(file, opts.onProgress);
    if (!opts.start) return;
    opts.onStep?.("start");
    // CC1 V0.3.0-o acknowledges a start sent right after the upload but drops it: wait for the file to be
    // listed, then check that the printer really leaves its resting state, and retry once (finding 11).
    await this.waitForFile(file.name);
    for (const attempt of [1, 2]) {
      const r = await this.request(128, { Filename: file.name, StartLayer: 0, Calibration_switch: opts.leveling === false ? 0 : 1,
        PrintPlatformType: 0, Tlp_Switch: 0, slot_map: [], path_prefix: "/local" });
      const ack = r.Data?.Data?.Ack;
      if (ack != null && ack !== 0) throw new LanError(`the printer refused to start: ${START_ACKS[ack] ?? `error code ${ack}`}`);
      const end = Date.now() + START_TIMEOUT_MS;
      while (Date.now() < end) {
        await sleep(2000);
        if (!(await this.atRest())) return;
      }
      if (attempt === 2) break;
    }
    throw new LanError("the printer accepted the start but did not begin - the file is on the printer, start it on its screen");
  }

  async control(action: "pause" | "resume" | "cancel"): Promise<void> {
    await this.request({ pause: 129, cancel: 130, resume: 131 }[action]);
  }

  close(): void {
    this.ws?.close();
    this.ws = null;
  }
}
