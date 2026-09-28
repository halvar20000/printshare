// Client for the PrintShare server API (see printshare/api.py).
import { fetch as expoFetch } from "expo/fetch";
import { File } from "expo-file-system";
import { Platform } from "react-native";

import type { T } from "./i18n";

/** `remoteUrl`: optional second address for use away from home (e.g. Tailscale). */
export type Server = { url: string; token: string; remoteUrl?: string };
export type Route = "home" | "remote";

export type Printer = { id: string; name: string; type: string; machine: string };
export type PrinterKind = "idle" | "active" | "paused" | "done" | "stopped" | "error" | "unknown";
export type PrinterStatus = {
  state: string | null; kind: PrinterKind; file?: string | null; progress?: number;
  layer?: number | null; layers?: number | null; print_duration_s?: number | null;
  nozzle?: number | null; nozzle_target?: number | null; bed?: number | null; bed_target?: number | null;
  camera?: string | null;
};
export type Defaults = {
  filament: string; process: string; bed_type: string; supports: string; brim: string;
  infill: number | null; walls: number | null; layer_height?: string | null;
};
export type Options = {
  printer: string; materials: string[]; processes: string[]; plates: string[];
  supports: string[]; brims: string[]; defaults: Defaults;
};
export type JobOptions = Partial<{
  filament: string; process: string; bed_type: string; supports: string; brim: string;
  infill: number; walls: number;
}>;
export type ModelFile = { index: number; name: string; size: number | null };
export type JobState = "slicing" | "sliced" | "sending" | "uploaded" | "started" | "error" | "running" | "done";
export type JobResult = {
  printer: string; source_file: string; print_time: string | null; filament_g: number | null;
  filament_m: number | null; layers: number | null; profiles: Record<string, string>;
  overrides: Record<string, string>;
};
export type Job = {
  id: string; kind: string; state: JobState; log: string[]; result: JobResult | null; error: string | null;
  created: number; printer?: string;
  request: { link: string; printer?: string | null; file?: string | null; options?: JobOptions; name?: string };
};
export type JobSummary = {
  id: string; kind: string; state: JobState; error: string | null; created: number; printer?: string;
  link: string; file: string | null; print_time: string | null; filament_g: number | null;
};
export type Upload = { id: string; link: string; name: string; size: number };
export type Source = { id: "printables" | "thingiverse"; name: string; available: boolean };
export type SortKey = "relevant" | "popular" | "makes";
export type ModelHit = {
  source: Source["id"]; id: string; name: string; url: string; author: string | null; thumbnail: string | null;
  likes: number | null; downloads: number | null; makes: number | null; license: string | null;
};
export type ModelDetail = ModelHit & {
  images: string[]; summary: string; description: string; category: string | null;
  recommended: Partial<{ nozzle: string; layer_height: string; material: string; weight_g: number; print_hours: number }>;
  files: { name: string; size: number | null; sliceable: boolean }[];
};
export type SearchPage = { results: ModelHit[]; total: number | null; page: number; has_more: boolean };

/** Error with a friendly, translated message; `detail` keeps the server's original text. */
export class ApiError extends Error {
  constructor(message: string, public status = 0, public detail = "") {
    super(message);
  }
}

export function normalizeUrl(url: string): string {
  let u = url.trim().replace(/\/+$/, "");
  if (u && !/^https?:\/\//i.test(u)) u = "http://" + u;
  return u;
}

/** Map server error texts to messages a non-technical user understands (SL-04). */
export function friendlyError(t: T, status: number, detail: string): string {
  const d = detail.toLowerCase();
  const rules: [boolean, Parameters<T>[0]][] = [
    [status === 401, "errToken"],
    [d.includes("did not start"), "errNotStarted"],
    [d.includes("refused to start"), "errRefused"],
    [d.includes("busy"), "errBusy"],
    [d.includes("printer not reachable") || d.includes("moonraker not reachable") ||
      d.includes("sending failed"), "errPrinterOffline"],
    [d.includes("unrecognised model link") || d.includes("must be an http"), "errLink"],
    [d.includes("not found (or not public)"), "errNotFound"],
    [d.includes("no sliceable files"), "errNoFiles"],
    [d.includes("unsupported file type"), "errFileType"],
    [status === 413 || d.includes("too large"), "errTooLarge"],
    [d.includes("uploaded file not found"), "errUploadGone"],
    [d.includes("orcaslicer produced no g-code") || d.includes("slice"), "errSlice"],
    [d.includes("preset") && d.includes("not found"), "errProfile"],
    [d.includes("thingiverse needs"), "errThingiverse"],
    [d.includes("not found") && !d.includes("uploaded"), "errNotFound"],
    [d.includes("download failed") || d.includes("printables api error") ||
      d.includes("refused the download"), "errDownload"],
  ];
  for (const [hit, key] of rules) if (hit) return t(key);
  return detail || t("errUnknown");
}

// Address that answered last, per server. Kept outside Api so it survives re-creating the client.
const activeAddress = new Map<string, string>();
const PROBE_MS = 4000;

/** Forget which address worked, e.g. when the app returns to the foreground (maybe left home). */
export function resetRoutes(): void {
  activeAddress.clear();
}

export class Api {
  constructor(private server: Server, private t: T) {}

  private get key() {
    return `${this.server.url}|${this.server.remoteUrl ?? ""}`;
  }

  addresses(): string[] {
    return [...new Set([this.server.url, this.server.remoteUrl].filter((u): u is string => !!u))];
  }

  /** Which address is in use, once known. */
  route(): Route | null {
    const a = activeAddress.get(this.key);
    return !a ? null : a === this.server.url ? "home" : "remote";
  }

  private headers(json = true): Record<string, string> {
    return { Authorization: `Bearer ${this.server.token}`, ...(json ? { "Content-Type": "application/json" } : {}) };
  }

  /** Ask all addresses at once; the first that answers at all (even 401) wins. */
  private probe(): Promise<string | null> {
    const addrs = this.addresses();
    if (addrs.length === 1) return Promise.resolve(addrs[0]);
    return new Promise(resolve => {
      let pending = addrs.length, done = false;
      for (const a of addrs) {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), PROBE_MS);
        fetch(`${a}/api/info`, { headers: this.headers(false), signal: ctrl.signal })
          .then(() => { if (!done) { done = true; resolve(a); } })
          .catch(() => {})
          .finally(() => { clearTimeout(timer); if (--pending === 0 && !done) resolve(null); });
      }
    });
  }

  private async base(): Promise<string> {
    const known = activeAddress.get(this.key);
    if (known) return known;
    const found = await this.probe();
    if (found) activeAddress.set(this.key, found);
    return found ?? this.server.url;
  }

  private async fetchWithTimeout(url: string, init: RequestInit, timeout: number): Promise<Response> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    try {
      return await fetch(url, { ...init, signal: ctrl.signal });
    } catch (e) {
      throw new ApiError(this.t(ctrl.signal.aborted ? "errTimeout" : "errOffline"), 0, String(e));
    } finally {
      clearTimeout(timer);
    }
  }

  private async request<R>(path: string, init: { method?: string; body?: unknown; timeout?: number } = {}): Promise<R> {
    const method = init.method ?? "GET";
    const req: RequestInit = {
      method, headers: this.headers(), body: init.body === undefined ? undefined : JSON.stringify(init.body),
    };
    const timeout = init.timeout ?? 15000;
    const base = await this.base();
    let res: Response;
    try {
      res = await this.fetchWithTimeout(base + path, req, timeout);
    } catch (e) {
      // Maybe we moved between home and away: find the address that works now. Only reads are
      // repeated automatically - a print start or new job is never sent twice.
      if (this.addresses().length < 2) throw e;
      activeAddress.delete(this.key);
      const other = await this.probe();
      if (!other) throw e;
      activeAddress.set(this.key, other);
      if (other === base || method !== "GET") throw e;
      res = await this.fetchWithTimeout(other + path, req, timeout);
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`;
      throw new ApiError(friendlyError(this.t, res.status, detail), res.status, detail);
    }
    return body as R;
  }

  info = () => this.request<{ name: string; version: string; printers: number }>("/api/info", { timeout: 8000 });
  printers = () => this.request<Printer[]>("/api/printers");
  options = (printer: string, process?: string) =>
    this.request<Options>(`/api/printers/${encodeURIComponent(printer)}/options` +
      (process ? `?process=${encodeURIComponent(process)}` : ""), { timeout: 30000 });
  status = (printer: string) =>
    this.request<PrinterStatus>(`/api/printers/${encodeURIComponent(printer)}/status`, { timeout: 20000 });
  control = (printer: string, action: "pause" | "resume" | "cancel") =>
    this.request<{ ok: boolean }>(`/api/printers/${encodeURIComponent(printer)}/control`,
      { method: "POST", body: { action, confirm: action === "cancel" } });
  files = (link: string) =>
    this.request<ModelFile[]>(`/api/files?link=${encodeURIComponent(link)}`, { timeout: 60000 });
  createJob = (link: string, printer: string, file: string | null, options: JobOptions) =>
    this.request<{ job: string }>("/api/jobs", { method: "POST", body: { link, printer, file, options }, timeout: 30000 });
  jobs = () => this.request<JobSummary[]>("/api/jobs");
  job = (id: string) => this.request<Job>(`/api/jobs/${id}`);
  send = (id: string, start: boolean) =>
    this.request<{ job: string }>(`/api/jobs/${id}/send`, { method: "POST", body: { start, confirm: start } });
  deleteJob = (id: string) => this.request<{ deleted: string }>(`/api/jobs/${id}`, { method: "DELETE" });
  sources = () => this.request<Source[]>("/api/sources");
  search = (q: string, source: string, page: number, sort: SortKey) =>
    this.request<SearchPage>(`/api/search?q=${encodeURIComponent(q)}&source=${source}&page=${page}&sort=${sort}`,
      { timeout: 30000 });
  model = (source: string, id: string) =>
    this.request<ModelDetail>(`/api/models/${source}/${encodeURIComponent(id)}`, { timeout: 30000 });

  /** Upload a local model file (document picker or share menu) as raw body. */
  async upload(uri: string, name: string): Promise<Upload> {
    const url = `${await this.base()}/api/uploads?name=${encodeURIComponent(name)}`;
    const headers = { ...this.headers(false), "Content-Type": "application/octet-stream" };
    let res: Response;
    try {
      if (Platform.OS === "web") {
        const blob = await (await fetch(uri)).blob();
        res = await fetch(url, { method: "POST", headers, body: blob });
      } else {
        res = (await expoFetch(url, { method: "POST", headers, body: new File(uri) })) as unknown as Response;
      }
    } catch (e) {
      throw new ApiError(this.t("errOffline"), 0, String(e));
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`;
      throw new ApiError(friendlyError(this.t, res.status, detail), res.status, detail);
    }
    return body as Upload;
  }
}
