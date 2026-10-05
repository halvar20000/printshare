// Bambu Lab printer in LAN-only mode, reached by the phone itself (beginner mode without a bridge; Android).
// The native module (modules/bambu-lan) does MQTT over TLS and the FTPS upload; this keeps one connection per printer
// open, merges the P1's partial reports and starts prints like Bambu Studio (project_file with ams_mapping).
import type { PrinterStatus } from "../api";
import BambuLan from "../../../modules/bambu-lan/src/BambuLanModule";
import { amsMapping, hasAms, merge, STARTING, startCommand, statusFrom, taskName } from "./bambuState";
import type { GcodeFile } from "./io";
import { LanError, sleep, type Lan, type SendOptions } from "./types";

const READY_MS = 10_000;
const START_MS = 45_000;
const LAN_MODE = "Switch on LAN-only mode on the printer (Settings → WLAN), with newer firmware also developer mode - "
  + "without it Bambu printers take no print jobs from other apps.";

type Conn = { report: Record<string, any>; serial: string; code: string; connected: boolean; error: string | null;
  replies: Record<string, { at: number; msg: Record<string, any> }>; opening: Promise<void> | null };
const conns = new Map<string, Conn>();
let listening = false;

function listen() {
  if (listening) return;
  listening = true;
  BambuLan.addListener("onMessage", ({ host, payload }) => {
    const c = conns.get(host);
    if (!c) return;
    let data: Record<string, any>;
    try { data = JSON.parse(payload); } catch { return; }
    const p = data.print;
    if (p && typeof p === "object") {
      if (p.command && p.command !== "push_status") c.replies[p.command] = { at: Date.now(), msg: p };
      merge(c.report, p);
    }
  });
  BambuLan.addListener("onState", ({ host, connected, error }) => {
    const c = conns.get(host);
    if (c) { c.connected = connected; c.error = connected ? null : error; }
  });
}

export class BambuPrinter implements Lan {
  constructor(readonly host: string, private code: string) {}

  private async conn(): Promise<Conn> {
    listen();
    let c = conns.get(this.host);
    if (c && c.code !== this.code) {                       // access code changed
      await BambuLan.disconnectAsync(this.host).catch(() => undefined);
      conns.delete(this.host);
      c = undefined;
    }
    if (!c) {
      c = { report: {}, serial: "", code: this.code, connected: false, error: null, replies: {}, opening: null };
      conns.set(this.host, c);
    }
    if (!c.connected && !c.opening) {
      const cc = c;
      cc.opening = (async () => {
        if (!cc.serial) {
          const cert = await BambuLan.certAsync(this.host);
          if (!cert?.bambu) throw new LanError("printer not reachable on the Wi-Fi - is it on, in LAN-only mode?");
          cc.serial = cert.serial;
        }
        await BambuLan.connectAsync(this.host, cc.serial, this.code);
      })().finally(() => { cc.opening = null; });
    }
    try {
      if (c.opening) await c.opening;
    } catch (e) {
      conns.delete(this.host);
      const msg = (e as Error).message ?? "";
      throw new LanError(/access code|authori/i.test(msg) ? "the printer refused the access code" : msg);
    }
    const until = Date.now() + READY_MS;
    while (!("gcode_state" in c.report) && Date.now() < until) await sleep(200);
    if (!("gcode_state" in c.report)) throw new LanError(c.error ?? "no answer from the printer");
    return c;
  }

  async status(): Promise<PrinterStatus> {
    return statusFrom((await this.conn()).report);
  }

  private async publish(payload: Record<string, any>) {
    await BambuLan.publishAsync(this.host, JSON.stringify(payload));
  }

  async send(file: GcodeFile, opts: SendOptions): Promise<void> {
    if (!file.uri) throw new LanError("this phone can't send files to Bambu printers");
    const c = await this.conn();
    const task = taskName(file.name);
    const remote = `${task}.gcode.3mf`;
    opts.onStep?.("upload");
    let filaments = 1;
    try {
      filaments = (await BambuLan.uploadAsync(this.host, this.code, file.uri, remote)).filaments;
    } catch (e) {
      throw new LanError(`upload to the printer failed: ${(e as Error).message} - is an SD card in the printer?`);
    }
    opts.onProgress?.(1);
    if (!opts.start) return;
    opts.onStep?.("start");
    const ams = hasAms(c.report);
    const sentAt = Date.now();
    await this.publish(startCommand(task, remote, amsMapping(filaments, opts.tools, c.report), ams, opts.leveling !== false));
    // the printer has to show that it starts: without LAN-only mode it ignores the command silently
    while (Date.now() - sentAt < START_MS) {
      const reply = c.replies.project_file;
      if (reply && reply.at >= sentAt && /^(fail|failed|error)$/i.test(String(reply.msg.result ?? ""))) {
        throw new LanError(`the printer refused the print (${reply.msg.reason ?? reply.msg.err_code ?? "refused"}). ${LAN_MODE}`);
      }
      const g = String(c.report.gcode_state ?? "").toUpperCase();
      if (STARTING.has(g) && [task, undefined, null, ""].includes(c.report.subtask_name)) return;
      await sleep(1000);
    }
    throw new LanError(`the printer didn't start the print. ${LAN_MODE}`);
  }

  async control(action: "pause" | "resume" | "cancel"): Promise<void> {
    await this.conn();
    await this.publish({ print: { command: action === "cancel" ? "stop" : action, param: "" } });
  }

  close(): void {
    // the MQTT connection stays open for the next status call (the P1 sends only changes after the first report)
  }
}
