// Klipper printers (e.g. Centauri Carbon with OpenCentauri COSMOS) on the home Wi-Fi through Moonraker's HTTP API.
// Port of printshare/printers/moonraker.py: status incl. AFC lanes (CANVAS), upload + start, pause/resume/cancel.
import type { Lane, PrinterStatus } from "../api";
import type { GcodeFile } from "./io";
import { kindOf, LanError, type Lan, type SendOptions } from "./types";

type Raw = Record<string, any>;

export class MoonrakerPrinter implements Lan {
  private base: string | null = null;
  private candidates: string[];

  constructor(address: string, private apiKey?: string) {
    const a = address.trim().replace(/\/+$/, "");
    const url = /^https?:\/\//.test(a) ? a : `http://${a}`;
    // COSMOS serves Moonraker on port 80, a classic Klipper install on 7125
    this.candidates = /:\d+$/.test(url.replace(/^https?:\/\//, "")) ? [url] : [url, `${url}:7125`];
  }

  private headers(): Record<string, string> {
    return this.apiKey ? { "X-Api-Key": this.apiKey } : {};
  }

  private async get(path: string, timeoutMs = 8000): Promise<Raw> {
    const base = await this.resolve();
    const r = await fetchWithTimeout(`${base}${path}`, { headers: this.headers() }, timeoutMs);
    if (!r.ok) throw new LanError(`the printer answered HTTP ${r.status}`);
    return (await r.json()).result;
  }

  private async resolve(): Promise<string> {
    if (this.base) return this.base;
    for (const base of this.candidates) {
      try {
        const r = await fetchWithTimeout(`${base}/server/info`, { headers: this.headers() }, 5000);
        if (r.ok && "result" in (await r.json())) return (this.base = base);
      } catch { /* try the next one */ }
    }
    throw new LanError("printer not reachable on the Wi-Fi");
  }

  async status(): Promise<PrinterStatus> {
    const objects: string[] = (await this.get("/printer/objects/list").catch(() => ({ objects: [] }))).objects ?? [];
    const wanted = ["print_stats", "display_status", "extruder", "heater_bed", "virtual_sdcard", "gcode_move"];
    const st: Raw = (await this.get(`/printer/objects/query?${wanted.join("&")}`)).status;
    const ps = st.print_stats ?? {}, info = ps.info ?? {};
    const state: string | null = ps.state ?? null;
    const progress = (st.display_status?.progress || st.virtual_sdcard?.progress || 0) * 100;
    const base = await this.resolve();
    return {
      state, kind: kindOf(state), file: ps.filename || null, progress: Math.round(progress * 10) / 10,
      layer: info.current_layer ?? null, layers: info.total_layer ?? null, print_duration_s: ps.print_duration ?? null,
      nozzle: st.extruder?.temperature ?? null, nozzle_target: st.extruder?.target ?? null,
      bed: st.heater_bed?.temperature ?? null, bed_target: st.heater_bed?.target ?? null,
      camera: `${base}/webcam/?action=stream`,
      lanes: await this.lanes(objects),
      heaters: { nozzle: { actual: st.extruder?.temperature ?? null, target: st.extruder?.target ?? null },
                 bed: { actual: st.heater_bed?.temperature ?? null, target: st.heater_bed?.target ?? null } },
      speed: typeof st.gcode_move?.speed_factor === "number" ? Math.round(st.gcode_move.speed_factor * 100) : null,
    };
  }

  /** AFC lanes (CANVAS): one Klipper object per lane, "AFC_lane <name>" (AFC 1.2) or "AFC_stepper <name>". */
  private async lanes(objects: string[]): Promise<Lane[]> {
    try {
      if (!objects.includes("AFC")) return [];
      const afc: Raw = (await this.get("/printer/objects/query?AFC")).status.AFC ?? {};
      const have = new Set(objects);
      const objs = (afc.lanes ?? []).map((n: string) => [`AFC_lane ${n}`, `AFC_stepper ${n}`].find(o => have.has(o)))
        .filter(Boolean) as string[];
      if (!objs.length) return [];
      const st: Raw = (await this.get(`/printer/objects/query?${objs.map(encodeURIComponent).join("&")}`)).status;
      return objs.map(obj => {
        const ln = st[obj] ?? {}, name = obj.split(" ").slice(1).join(" ");
        const m = /^T(\d+)$/.exec(String(ln.map ?? ""));
        const color = String(ln.color ?? "");
        return {
          id: name, tool: m ? Number(m[1]) : null, unit: ln.unit ?? null, material: ln.material || null,
          color: /^#?[0-9A-Fa-f]{6,8}$/.test(color) ? `#${color.replace("#", "").slice(0, 6).toUpperCase()}` : null,
          filament: ln.filament_name || null, weight_g: ln.weight ?? null, loaded: !!(ln.prep || ln.load),
          in_toolhead: !!ln.tool_loaded || name === afc.current_load, status: ln.status ?? null,
        };
      }).sort((a, b) => (a.tool ?? 99) - (b.tool ?? 99) || a.id.localeCompare(b.id));
    } catch {
      return [];             // lanes are extra information; the status works without them
    }
  }

  async send(file: GcodeFile, opts: SendOptions): Promise<void> {
    // bed leveling is part of the printer's start G-code; it can't be switched per print here
    opts.onStep?.("upload");
    const base = await this.resolve();
    const r = await file.upload(`${base}/server/files/upload`, "file",
      { root: "gcodes", print: opts.start ? "true" : "false" },
      opts.onProgress ? sent => opts.onProgress!(Math.min(1, sent / Math.max(1, file.size))) : undefined);
    if (r.status !== 200 && r.status !== 201) throw new LanError(`the printer refused the upload (HTTP ${r.status})`);
    if (opts.start) {
      opts.onStep?.("start");
      let started = true;
      try { started = (JSON.parse(r.body).result ?? JSON.parse(r.body)).print_started !== false; } catch { /* keep */ }
      if (!started) throw new LanError("the printer stored the file but did not start it");
    }
  }

  async control(action: "pause" | "resume" | "cancel"): Promise<void> {
    const base = await this.resolve();
    const r = await fetchWithTimeout(`${base}/printer/print/${action}`, { method: "POST", headers: this.headers() }, 15000);
    if (!r.ok) throw new LanError(`${action} failed (HTTP ${r.status})`);
  }

  close(): void {}
}

async function fetchWithTimeout(url: string, init: RequestInit, ms: number): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } catch {
    throw new LanError("printer not reachable on the Wi-Fi");
  } finally {
    clearTimeout(timer);
  }
}
