// Printers driven by OctoPrint (e.g. Creality Ender, Prusa MK3S, Anycubic) on the home Wi-Fi.
// Port of printshare/printers/octoprint.py. Auth: API key (OctoPrint settings > Application keys).
import type { PrinterStatus } from "../api";
import type { GcodeFile } from "./io";
import { kindOf, LanError, type Lan, type SendOptions } from "./types";

type Raw = Record<string, any>;

function stateOf(printer: Raw | null, job: Raw): string {
  if (printer === null) return "offline";
  const f = printer.state?.flags ?? {};
  if (f.cancelling) return "stopping";
  if (f.pausing) return "pausing";
  if (f.paused) return "paused";
  if (f.printing) return "printing";
  if (f.error || f.closedOrError) return "error";
  if ((job.progress?.completion ?? 0) >= 100) return "complete";
  return "standby";
}

export class OctoPrintPrinter implements Lan {
  private base: string;

  constructor(address: string, private apiKey: string) {
    const a = address.trim().replace(/\/+$/, "");
    this.base = /^https?:\/\//.test(a) ? a : `http://${a}`;
    if (!apiKey) throw new LanError("enter the OctoPrint API key (Settings > Application keys)");
  }

  private async call(method: string, path: string, body?: unknown, timeoutMs = 10000): Promise<Response> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const r = await fetch(this.base + path, { method, signal: ctrl.signal,
        headers: { "X-Api-Key": this.apiKey, ...(body ? { "Content-Type": "application/json" } : {}) },
        body: body ? JSON.stringify(body) : undefined });
      if (r.status === 401 || r.status === 403) throw new LanError("OctoPrint rejected the API key");
      return r;
    } catch (e) {
      if (e instanceof LanError) throw e;
      throw new LanError("OctoPrint not reachable on the Wi-Fi");
    } finally {
      clearTimeout(timer);
    }
  }

  async status(): Promise<PrinterStatus> {
    const jr = await this.call("GET", "/api/job");
    if (!jr.ok) throw new LanError(`OctoPrint answered HTTP ${jr.status}`);
    const job: Raw = await jr.json();
    const pr = await this.call("GET", "/api/printer");
    const printer: Raw | null = pr.status === 409 ? null : pr.ok ? await pr.json() : null;   // 409: not connected
    const state = stateOf(printer, job);
    const t = printer?.temperature ?? {}, tool = t.tool0 ?? {}, bed = t.bed ?? {};
    return {
      state, kind: kindOf(state), file: job.job?.file?.display ?? job.job?.file?.name ?? null,
      progress: Math.round((job.progress?.completion ?? 0) * 10) / 10, layer: null, layers: null,
      print_duration_s: job.progress?.printTime ?? null, time_remaining_s: job.progress?.printTimeLeft ?? null,
      nozzle: tool.actual ?? null, nozzle_target: tool.target ?? null, bed: bed.actual ?? null, bed_target: bed.target ?? null,
      heaters: { nozzle: { actual: tool.actual ?? null, target: tool.target ?? null },
                 bed: { actual: bed.actual ?? null, target: bed.target ?? null } },
      camera: null, lanes: [], speed: null,
    };
  }

  async send(file: GcodeFile, opts: SendOptions): Promise<void> {
    opts.onStep?.("upload");
    const flag = opts.start ? "true" : "false";
    const r = await file.upload(`${this.base}/api/files/local`, "file", { select: flag, print: flag },
      opts.onProgress ? sent => opts.onProgress!(Math.min(1, sent / Math.max(1, file.size))) : undefined,
      { "X-Api-Key": this.apiKey });
    if (r.status === 401 || r.status === 403) throw new LanError("OctoPrint rejected the API key");
    if (r.status === 409) throw new LanError("the printer is busy or not connected in OctoPrint");
    if (r.status >= 300) throw new LanError(`OctoPrint refused the upload (HTTP ${r.status})`);
    if (opts.start) {
      opts.onStep?.("start");
      let effective = true;
      try { effective = JSON.parse(r.body).effectivePrint !== false; } catch { /* keep */ }
      if (!effective) throw new LanError("OctoPrint stored the file but did not start it - is the printer connected?");
    }
  }

  async control(action: "pause" | "resume" | "cancel"): Promise<void> {
    const body = { pause: { command: "pause", action: "pause" }, resume: { command: "pause", action: "resume" },
      cancel: { command: "cancel" } }[action];
    const r = await this.call("POST", "/api/job", body);
    if (r.status === 409) throw new LanError("the printer is busy or not connected in OctoPrint");
    if (r.status >= 300) throw new LanError(`${action} failed (HTTP ${r.status})`);
  }

  close(): void {}
}
