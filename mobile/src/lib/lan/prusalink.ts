// Prusa printers with PrusaLink (MK4/MK4S, MK3.9, CORE One, MINI, XL) on the home Wi-Fi.
// Port of printshare/printers/prusalink.py. Auth: HTTP digest, user "maker" + the password from the printer screen
// (Settings > Network > PrusaLink); older firmware: X-Api-Key. Spec: prusa3d/Prusa-Link-Web spec/openapi.yaml
import type { PrinterStatus } from "../api";
import type { GcodeFile } from "./io";
import { md5Hex } from "./md5";
import { kindOf, LanError, type Lan, type SendOptions } from "./types";

type Raw = Record<string, any>;
const STATES: Record<string, string> = { IDLE: "standby", READY: "standby", BUSY: "busy", PRINTING: "printing",
  PAUSED: "paused", FINISHED: "complete", STOPPED: "cancelled", ERROR: "error", ATTENTION: "attention" };
const md5 = (s: string) => md5Hex(new TextEncoder().encode(s));

/** HTTP digest (RFC 7616, MD5) - with qop=auth when the printer asks for it, else the RFC 2069 form. */
class Digest {
  private realm = ""; private nonce = ""; private opaque = ""; private qop = ""; private nc = 0;

  constructor(private user: string, private password: string) {}

  get ready() { return !!this.nonce; }

  learn(header: string | null): boolean {
    if (!header || !/^Digest /i.test(header)) return false;
    const f: Record<string, string> = {};
    for (const m of header.slice(7).matchAll(/(\w+)=(?:"([^"]*)"|([^,\s]*))/g)) f[m[1].toLowerCase()] = m[2] ?? m[3];
    this.realm = f.realm ?? ""; this.nonce = f.nonce ?? ""; this.opaque = f.opaque ?? "";
    this.qop = (f.qop ?? "").split(",").map(q => q.trim()).includes("auth") ? "auth" : "";
    this.nc = 0;
    return !!this.nonce;
  }

  header(method: string, uri: string): string {
    const ha1 = md5(`${this.user}:${this.realm}:${this.password}`), ha2 = md5(`${method}:${uri}`);
    let parts = `username="${this.user}", realm="${this.realm}", nonce="${this.nonce}", uri="${uri}"`;
    if (this.qop) {
      const nc = (++this.nc).toString(16).padStart(8, "0");
      const cnonce = md5(`${Date.now()}:${Math.random()}`).slice(0, 16);
      parts += `, qop=auth, nc=${nc}, cnonce="${cnonce}", response="${md5(`${ha1}:${this.nonce}:${nc}:${cnonce}:auth:${ha2}`)}"`;
    } else {
      parts += `, response="${md5(`${ha1}:${this.nonce}:${ha2}`)}"`;
    }
    if (this.opaque) parts += `, opaque="${this.opaque}"`;
    return `Digest ${parts}, algorithm=MD5`;
  }
}

export class PrusaLinkPrinter implements Lan {
  private base: string;
  private digest: Digest | null;

  constructor(address: string, private creds: { password?: string; apiKey?: string; username?: string }) {
    const a = address.trim().replace(/\/+$/, "");
    this.base = /^https?:\/\//.test(a) ? a : `http://${a}`;
    if (!creds.password && !creds.apiKey) throw new LanError("enter the PrusaLink password (shown on the printer)");
    this.digest = creds.password ? new Digest(creds.username || "maker", creds.password) : null;
  }

  private auth(method: string, path: string): Record<string, string> {
    if (!this.digest) return { "X-Api-Key": this.creds.apiKey ?? "" };
    return this.digest.ready ? { Authorization: this.digest.header(method, path) } : {};
  }

  private async call(method: string, path: string, init: RequestInit = {}, timeoutMs = 10000): Promise<Response> {
    for (const attempt of [1, 2]) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      let r: Response;
      try {
        r = await fetch(this.base + path, { ...init, method, signal: ctrl.signal,
          headers: { ...(init.headers as Record<string, string> | undefined), ...this.auth(method, path) } });
      } catch {
        throw new LanError("printer not reachable on the Wi-Fi");
      } finally {
        clearTimeout(timer);
      }
      // first contact or an expired nonce: learn the challenge and ask once more
      if (r.status === 401 && attempt === 1 && this.digest?.learn(r.headers.get("www-authenticate"))) continue;
      if (r.status === 401) throw new LanError("PrusaLink rejected the password / API key");
      return r;
    }
    throw new LanError("PrusaLink rejected the password / API key");
  }

  private async json(path: string): Promise<Raw> {
    const r = await this.call("GET", path);
    if (r.status === 204) return {};
    if (!r.ok) throw new LanError(`PrusaLink answered HTTP ${r.status}`);
    return r.json();
  }

  async status(): Promise<PrinterStatus> {
    const st = await this.json("/api/v1/status");
    const job: Raw = st.job ? await this.json("/api/v1/job").catch(() => ({})) : {};
    const pr = st.printer ?? {}, sj = st.job ?? {}, file = job.file ?? {};
    const raw = String(pr.state ?? "").toUpperCase();
    const state = STATES[raw] ?? (raw ? raw.toLowerCase() : null);
    return {
      state, kind: kindOf(state), file: file.display_name ?? file.name ?? null,
      progress: Math.round(Number(sj.progress ?? job.progress ?? 0) * 10) / 10,
      layer: null, layers: null,
      print_duration_s: sj.time_printing ?? job.time_printing ?? null,
      time_remaining_s: sj.time_remaining ?? job.time_remaining ?? null,
      nozzle: pr.temp_nozzle ?? null, nozzle_target: pr.target_nozzle ?? null,
      bed: pr.temp_bed ?? null, bed_target: pr.target_bed ?? null,
      heaters: { nozzle: { actual: pr.temp_nozzle ?? null, target: pr.target_nozzle ?? null },
                 bed: { actual: pr.temp_bed ?? null, target: pr.target_bed ?? null } },
      speed: pr.speed ?? null, camera: null, lanes: [],
    };
  }

  private async storage(): Promise<string> {
    const list: Raw[] = (await this.json("/api/v1/storage")).storage_list ?? [];
    const st = list.find(s => s.available && !s.read_only && s.path);
    if (!st) throw new LanError("no writable storage on the printer - is a USB drive inserted?");
    return String(st.path).replace(/^\/+|\/+$/g, "");
  }

  async send(file: GcodeFile, opts: SendOptions): Promise<void> {
    opts.onStep?.("upload");
    const storage = await this.storage();                  // also gets a fresh digest nonce
    const name = remoteName(file.name);
    const path = `/api/v1/files/${storage}/${encodeURIComponent(name)}`;
    const r = await file.put(this.base + path, {
      "Content-Type": "application/octet-stream", Overwrite: "?1", "Print-After-Upload": opts.start ? "?1" : "?0",
      ...this.auth("PUT", path) },
      opts.onProgress ? sent => opts.onProgress!(Math.min(1, sent / Math.max(1, file.size))) : undefined);
    if (r.status === 401) throw new LanError("PrusaLink rejected the password / API key");
    if (r.status === 409) throw new LanError("the printer is busy");
    if (r.status >= 300) throw new LanError(`the printer refused the upload (HTTP ${r.status})`);
    if (opts.start) opts.onStep?.("start");
  }

  async control(action: "pause" | "resume" | "cancel"): Promise<void> {
    const job = await this.json("/api/v1/job");
    if (!job.id) throw new LanError("no print is running");
    const r = action === "cancel" ? await this.call("DELETE", `/api/v1/job/${job.id}`)
      : await this.call("PUT", `/api/v1/job/${job.id}/${action}`);
    if (r.status >= 300) throw new LanError(`${action} failed (HTTP ${r.status})`);
  }

  close(): void {}
}

/** Printer USB drives are FAT: short, plain names. */
export function remoteName(name: string): string {
  const m = /^(.*?)(\.[^.]+)?$/.exec(name)!;
  const stem = m[1].replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^[._]+|[._]+$/g, "") || "print";
  return `${stem.slice(0, 60)}${(m[2] ?? ".gcode").toLowerCase()}`;
}
