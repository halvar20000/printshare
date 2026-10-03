// Client for the PocketPrint3D server API (see printshare/api.py).
import { fetch as expoFetch } from "expo/fetch";
import { File } from "expo-file-system";
import { Platform } from "react-native";

import type { T } from "./i18n";

/** `remoteUrl`: optional second address for use away from home (e.g. Tailscale).
 * `cloud`: the hosted PocketPrint3D service - `token` is the session of `email`, printers are reached by the app. */
export type Server = { url: string; token: string; remoteUrl?: string; cloud?: boolean; email?: string };
/** The web app on app.pocketprint3d.com (docs/WEB.md): built with EXPO_PUBLIC_WEB_SAME_ORIGIN=1 and served by the cloud
 *  server itself - API on the same address, session in an HttpOnly cookie (`token` stays empty). */
export const WEB_APP = Platform.OS === "web" && process.env.EXPO_PUBLIC_WEB_SAME_ORIGIN === "1";
// EXPO_PUBLIC_CLOUD_URL only for development/tests (inlined at build time); the app uses the real service
export const CLOUD_URL = WEB_APP && typeof location !== "undefined" ? location.origin
  : process.env.EXPO_PUBLIC_CLOUD_URL || "https://api.pocketprint3d.com";

/** How a request proves who it is: the session token, or (web app) the cookie plus the header the server expects
 *  on changes, which a foreign page can't send. */
export function authHeaders(server: Server): Record<string, string> {
  return server.token ? { Authorization: `Bearer ${server.token}` } : WEB_APP ? { "X-Requested-With": "pocketprint3d" } : {};
}
const tokenParam = (server: Server) => server.token ? `token=${encodeURIComponent(server.token)}` : "";
export type Me = { id: string; email: string; printers: number;
  limits: { slices_per_day: number; slices_today: number; upload_mb: number } };
export type PrinterSettings = Partial<{ name: string; type: string; machine: string; cosmos: boolean; auto_leveling: boolean }>;
export type Route = "home" | "remote";

/** What a printer can be controlled with (issue #5). */
export type Controls = {
  heaters: { id: string; max: number }[]; fans: { id: string }[]; lights: { id: string }[];
  speed: { modes?: number[]; min?: number; max?: number } | null; history: boolean;
};
/** {heater: [[seconds before now, actual, target | null], …]} */
export type TempHistory = { series: Record<string, [number, number, number | null][]>; source: string };
export type CameraInfo = { available: boolean; stream: boolean; snapshot: boolean; name: string | null };
/** leveling: null = this printer can't switch bed leveling per print; else its default. */
/** power: a smart plug is set up on the web page (issue #9) -> "switch on" while the printer is off. */
export type Printer = { id: string; name: string; type: string; machine: string; leveling?: boolean | null; power?: boolean;
  cosmos?: boolean;
  /** cloud: reached through this bridge at home (docs/BRIDGE.md) - the server forwards status/control/send */
  bridge?: string | null };
/** A bridge of the cloud account: a PocketPrint3D server at home with an outgoing connection (docs/BRIDGE.md). */
export type Bridge = { id: string; name: string; version: string | null; public_key: string | null; created: number;
  last_seen: number | null; online: boolean; connected: number | null;
  printers: { id: string; name: string; type?: string; machine?: string }[] };
/** A spool booking kept in the cloud account (server 0.29.0, docs/WEB.md step 2). */
export type ServerBooking = {
  id: string; printer: string; printer_name: string | null; file: string; job: string | null;
  uses: { spool: number; grams: number; label: string }[]; booked_uses: { spool: number; grams: number; label: string }[];
  created: number; seen: boolean; progress: number | null; state: "wait" | "ready" | "ask" | "booked" | "dropped";
  ask_part: number | null;
};
export type ServerBookings = { waiting: ServerBooking[]; open: ServerBooking[]; booked: ServerBooking[] };
/** A printer a bridge found on its home network. */
export type BridgeFound = { type: string; address: string; name: string; cosmos?: boolean; detail?: string; added: boolean };
/** Layer data for the G-code viewer; paths are [typeIndex, tool, x0, y0, x1, y1, ...] in 1/unit mm
 * (version 1 without the tool). */
export type Preview = {
  version: number; unit: number; types: string[]; bounds: [number, number, number, number] | null;
  bed: [number, number] | null; layers: { z: number; paths: number[][] }[]; filament_colors?: string[];
};
/** Filaments (colours) of a model, from its 3MF project; `used` = indices printed with. */
export type ModelColors = {
  file: string; filaments: { index: number; color: string; type: string | null; name: string | null }[];
  used: number[]; painted: boolean;
};
export type PrinterKind = "idle" | "active" | "paused" | "done" | "stopped" | "error" | "unknown";
/** A filament lane of a multi-filament unit (AFC / CANVAS); `tool` is the T number it prints as. */
export type Lane = {
  id: string; tool: number | null; unit: string | null; material: string | null; color: string | null;
  filament: string | null; weight_g: number | null; loaded: boolean; in_toolhead: boolean; status: string | null;
  /** server 0.16.0: Spoolman spool assigned to the lane in AFC */
  spool_id?: number | null;
};
export type PrinterStatus = {
  state: string | null; kind: PrinterKind; file?: string | null; progress?: number;
  layer?: number | null; layers?: number | null; print_duration_s?: number | null; time_remaining_s?: number | null;
  nozzle?: number | null; nozzle_target?: number | null; bed?: number | null; bed_target?: number | null;
  camera?: string | null;
  lanes?: Lane[];
  heaters?: Record<string, { actual: number | null; target: number | null }>;
  fans?: Record<string, number | null>;
  lights?: Record<string, boolean>;
  speed?: number | null;
  /** server 0.23.0, own servers with AI failure detection set up */
  watch?: WatchState;
  /** server 0.16.0, Klipper: Moonraker's own Spoolman link (it books the filament itself); null = none */
  spoolman?: { connected: boolean; spool_id: number | null } | null;
};
/** AI failure detection of one printer (Obico ML API on the user's server). */
export type WatchState = {
  state: "idle" | "warming" | "watching" | "alert" | "muted"; score: number; threshold: number; frames: number;
  last_check: number | null; alerted_at: number | null; paused: boolean; action: "notify" | "pause";
  error: string | null; frame: boolean;
};
export type FailureConfig = {
  configured: boolean; ml_url: string | null; token_set: boolean; server_url: string | null; interval: number;
  sensitivity: "low" | "medium" | "high"; action: "notify" | "pause";
};
export type Defaults = {
  filament: string; process: string; bed_type: string; supports: string; brim: string;
  infill: number | null; walls: number | null; layer_height?: string | null;
  /** server 0.15.2: the quality profile's infill pattern and line width (mm) */
  infill_pattern?: string | null; infill_line_width?: number | null;
};
export type Options = {
  printer: string; materials: string[]; processes: string[]; plates: string[];
  supports: string[]; brims: string[]; defaults: Defaults;
  /** uploaded quality/material presets among materials/processes (#2, later Orca Cloud #7) */
  own?: { materials: string[]; processes: string[] };
  /** server 0.15.2: OrcaSlicer infill patterns that can be chosen per print */
  infill_patterns?: string[];
};
export type JobOptions = Partial<{
  filament: string; process: string; bed_type: string; supports: string; brim: string;
  infill: number; infill_pattern: string; walls: number; filaments: (string | null)[];
  /** plate (server 0.14.0): copies 1-50, tilt in degrees, size in %, lay flat automatically */
  copies: number; rotate_x: number; rotate_y: number; scale: number; orient: boolean;
}>;
export type ModelFile = { index: number; name: string; size: number | null };
export type JobState = "uploading" | "slicing" | "sliced" | "sending" | "uploaded" | "started" | "error" | "running" | "done";
export type JobResult = {
  printer: string; source_file: string; print_time: string | null; filament_g: number | null;
  filament_m: number | null; layers: number | null; profiles: Record<string, string>;
  /** path of the G-code on the server (its file name is the name on the printer) */
  gcode?: string;
  overrides: Record<string, string>;
  filaments?: { index: number; color: string | null; preset: string; grams: number | null }[];
  /** server 0.14.0: copies asked for / on the plate (null for one copy) */
  copies_requested?: number | null; copies?: number | null;
};
export type Job = {
  id: string; kind: string; state: JobState; log: string[]; result: JobResult | null; error: string | null;
  created: number; printer?: string;
  request: { link: string; printer?: string | null; file?: string | null; options?: JobOptions; name?: string };
  /** sent through a bridge: the file's name on the printer (server 0.29.0) */
  printer_file?: string | null;
  /** time-lapse of this print (server 0.32.0) */
  timelapse?: { state: "recording" | "rendering" | "ready" | "failed"; frames: number; error?: string | null; size?: number };
};
export type JobSummary = {
  id: string; kind: string; state: JobState; error: string | null; created: number; printer?: string;
  link: string; file: string | null; print_time: string | null; filament_g: number | null;
};
export type Upload = { id: string; link: string; name: string; size: number };
export type Source = { id: "printables" | "thingiverse" | "manyfold"; name: string; available: boolean };
export type SortKey = "relevant" | "popular" | "makes";
export type ModelHit = {
  source: Source["id"]; id: string; name: string; url: string; author: string | null; thumbnail: string | null;
  likes: number | null; downloads: number | null; makes: number | null; license: string | null;
  /** what to slice when it isn't `url` (server 0.21.0, Manyfold: "manyfold:<id>") */
  link?: string | null;
};
/** A filament of SpoolmanDB (one per name + material + colour; `weights` = sizes it is sold in). */
export type FilamentPreset = {
  id: string | null; name: string; material: string; color_hex: string | null; color_hexes: string[] | null;
  density: number | null; extruder_temp: number | null; bed_temp: number | null; finish: string | null;
  weights: { weight: number; spool_weight: number | null }[]; diameter: number;
};
export type ModelDetail = ModelHit & {
  images: string[]; summary: string; description: string; category: string | null;
  recommended: Partial<{ nozzle: string; layer_height: string; material: string; weight_g: number; print_hours: number }>;
  files: { name: string; size: number | null; sliceable: boolean }[];
  /** server 0.17.1: "external" = only downloadable on the source's site (MakerWorld) */
  download?: "server" | "external";
  variants?: { id: number; title: string; default: boolean; weight_g: number | null; print_hours: number | null;
               materials: string[]; colors: string[]; needs_ams: boolean }[];
};
/** An OrcaSlicer preset uploaded to the server (issue #2). */
export type UserProfile = {
  file: string; kind: "machine" | "process" | "filament" | "unknown"; name: string | null;
  inherits: string | null; print_start?: boolean; error?: string;
};
export type PrinterProfile = {
  machine: string; machine_file: string | null; config_file: string | null; machine_preset: string | null;
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
    // messages of the app's own printer connections (lib/lan) and of the newer server features
    [d.includes("rejected the api key") || d.includes("rejected the password"), "errLanAuth"],
    [d.includes("enter the octoprint api key") || d.includes("enter the prusalink password"), "errLanAuth"],
    [d.includes("not connected in octoprint") || d.includes("is the printer connected?"), "errLanOcto"],
    [d.includes("no writable storage"), "errLanStorage"],
    [d.includes("accepted the start but did not begin") || d.includes("stored the file but did not start"), "errNotStarted"],
    [d.includes("no print is running"), "errNoPrint"],
    [d.includes("not reachable on the wi-fi") || d.includes("did not answer") || d.includes("did not send its status") ||
      /^(octoprint|prusalink|the printer) answered http/.test(d), "errLanOffline"],
    [d.includes("refused the upload"), "errLanUpload"],
    [d.includes("spoolman not reachable") || d.startsWith("spoolman answered http"), "errSpoolmanOffline"],
    [d.includes("manyfold refused"), "errManyfoldKey"],
    [d.includes("manyfold not reachable") || d.includes("manyfold sent no json"), "errManyfoldOffline"],
    [d.includes("ml api"), "errMlOffline"],
    [d.includes("bundle not found or private"), "errOrcaPrivate"],
    [d.includes("not an orca cloud share link"), "errOrcaLink"],
    [d.includes("makerworld only allows downloads"), "errMakerWorld"],
    [d.includes("bridge is offline") || d.includes("bridge went offline") || d.includes("bridge was removed") ||
      d.includes("bridge connection broke"), "errBridgeOffline"],
    [d.includes("bridge didn't answer in time"), "errBridgeTimeout"],
    [d.includes("unknown or expired code"), "errBridgeCode"],
    [d.includes("set up on the server at home itself"), "errBridgeServerPrinter"],
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

/** Text for any error shown to the user: server errors are already translated, the rest goes through the same rules. */
export function errorText(t: T, e: unknown): string {
  if (e instanceof ApiError) return e.message;
  const msg = e instanceof Error ? e.message : String(e ?? "");
  return friendlyError(t, 0, msg);
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
  /** Images the server serves itself (Manyfold previews, "/api/…"): full address with the key, as image views
   *  can't send headers. Other addresses are returned as they are. */
  imageUrl(u: string | null | undefined): string | undefined {
    if (!u) return undefined;
    if (!u.startsWith("/api/")) return u;
    const base = activeAddress.get(this.key) ?? this.server.url;
    const tp = tokenParam(this.server);
    return tp ? `${base}${u}${u.includes("?") ? "&" : "?"}${tp}` : `${base}${u}`;
  }

  /** Own Manyfold library (server 0.21.0, own servers only). */
  manyfoldConfig = () => this.request<{ configured: boolean; url: string | null; token_set: boolean; client_set: boolean }>("/api/manyfold/config");
  setManyfold = (url: string, token?: string) =>
    this.request<{ configured: boolean; url: string; models: number }>("/api/manyfold/config",
      { method: "PUT", body: { url, ...(token ? { token } : {}) }, timeout: 60000 });
  removeManyfold = () => this.request<{ configured: boolean }>("/api/manyfold/config", { method: "DELETE" });

  /** AI failure detection (server 0.23.0, own servers only). */
  failureConfig = () => this.request<FailureConfig>("/api/failure-detection/config");
  setFailureConfig = (c: { ml_url: string; ml_token?: string; server_url?: string; sensitivity: string; action: string }) =>
    this.request<FailureConfig & { test: { detections: number } }>("/api/failure-detection/config",
      { method: "PUT", body: c, timeout: 90000 });
  removeFailureConfig = () => this.request<{ configured: boolean }>("/api/failure-detection/config", { method: "DELETE" });
  muteWatch = (printer: string) =>
    this.request<WatchState>(`/api/printers/${encodeURIComponent(printer)}/watch/mute`, { method: "POST" });

  route(): Route | null {
    const a = activeAddress.get(this.key);
    return !a ? null : a === this.server.url ? "home" : "remote";
  }

  private headers(json = true): Record<string, string> {
    return { ...authHeaders(this.server), ...(json ? { "Content-Type": "application/json" } : {}) };
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
      const msg = res.status === 401 && this.server.cloud ? this.t("errSession") : friendlyError(this.t, res.status, detail);
      throw new ApiError(msg, res.status, detail);
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
  inspect = (link: string, file: string | null) =>
    this.request<ModelColors>(`/api/inspect?link=${encodeURIComponent(link)}` +
      (file ? `&file=${encodeURIComponent(file)}` : ""), { timeout: 120000 });
  files = (link: string) =>
    this.request<ModelFile[]>(`/api/files?link=${encodeURIComponent(link)}`, { timeout: 60000 });
  createJob = (link: string, printer: string, file: string | null, options: JobOptions) =>
    this.request<{ job: string }>("/api/jobs", { method: "POST", body: { link, printer, file, options }, timeout: 30000 });
  jobs = () => this.request<JobSummary[]>("/api/jobs");
  job = (id: string) => this.request<Job>(`/api/jobs/${id}`);
  /** lanes: {"<model filament, 1-based>": <printer tool of the chosen lane>};
   *  spoolId (server 0.16.0): Spoolman spool Moonraker books the print on (status.spoolman not null) */
  send = (id: string, start: boolean, leveling?: boolean, lanes?: Record<string, number>, spoolId?: number, timelapse?: boolean) =>
    this.request<{ job: string }>(`/api/jobs/${id}/send`,
      { method: "POST", body: { start, confirm: start, leveling, lanes, ...(spoolId != null ? { spool_id: spoolId } : {}),
                                ...(timelapse ? { timelapse: true } : {}) } });
  /** The time-lapse video (MP4) of a job; video players can't send headers, so the token goes into the URL. */
  async timelapseUrl(id: string): Promise<string> {
    const tp = tokenParam(this.server);
    return `${await this.base()}/api/jobs/${encodeURIComponent(id)}/timelapse${tp ? `?${tp}` : ""}`;
  }
  preview = (id: string) => this.request<Preview>(`/api/jobs/${id}/preview?format=2`, { timeout: 60000 });
  deleteJob = (id: string) => this.request<{ deleted: string }>(`/api/jobs/${id}`, { method: "DELETE" });
  /** Where the app downloads the G-code itself (cloud: it sends it to the printer); `lanes` = AFC slot mapping. */
  async gcodeDownload(id: string, lanes?: Record<number, number>) {
    const q = lanes && Object.keys(lanes).length ? `?lanes=${encodeURIComponent(JSON.stringify(lanes))}` : "";
    return { url: `${await this.base()}/api/jobs/${id}/gcode${q}`, headers: authHeaders(this.server) };
  }

  /** The model file itself for the 3D view (server 0.10.1, served from the download cache). */
  async modelFileDownload(link: string, file: string | null) {
    const q = new URLSearchParams({ link, ...(file ? { file } : {}) });
    return { url: `${await this.base()}/api/model-file?${q}`, headers: authHeaders(this.server) };
  }

  // ---------- cloud account (docs/API.md "Cloud accounts") ----------
  me = () => this.request<Me>("/api/auth/me");
  /** OrcaSlicer printer models for the model choice (server 0.15.3) */
  machines = () => this.request<{ name: string; vendor: string }[]>("/api/machines", { timeout: 30000 });
  logout = () => this.request<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
  deleteAccount = () => this.request<{ deleted: boolean }>("/api/auth/account?confirm=true", { method: "DELETE" });
  addPrinter = (p: PrinterSettings) => this.request<Printer>("/api/printers", { method: "POST", body: p });
  updatePrinter = (id: string, p: PrinterSettings) =>
    this.request<Printer>(`/api/printers/${encodeURIComponent(id)}`, { method: "PATCH", body: p });
  deletePrinter = (id: string) =>
    this.request<{ deleted: string }>(`/api/printers/${encodeURIComponent(id)}`, { method: "DELETE" });
  // send from OrcaSlicer (cloud, server 0.31.0): OctoPrint-compatible upload with one key per printer
  orcaUpload = (printer: string) =>
    this.request<{ enabled: boolean; url: string; created?: number; last_used?: number | null }>(
      `/api/printers/${encodeURIComponent(printer)}/orca-upload`);
  createOrcaUpload = (printer: string) =>
    this.request<{ enabled: boolean; url: string; key: string }>(`/api/printers/${encodeURIComponent(printer)}/orca-upload`,
      { method: "POST" });
  deleteOrcaUpload = (printer: string) =>
    this.request<{ deleted: boolean }>(`/api/printers/${encodeURIComponent(printer)}/orca-upload`, { method: "DELETE" });
  // spool bookings in the account (cloud spools, server 0.29.0)
  bookings = () => this.request<ServerBookings>("/api/bookings");
  createBooking = (b: { printer: string; file: string; uses: { spool: number; grams: number; label?: string }[];
                        printer_name?: string; job?: string }) =>
    this.request<{ booking: ServerBooking | null }>("/api/bookings", { method: "POST", body: b });
  observeBookings = (statuses: Record<string, PrinterStatus | null>) =>
    this.request<ServerBookings & { booked_now: ServerBooking[] }>("/api/bookings/observe", { method: "POST", body: { statuses } });
  resolveBooking = (id: string, part: number) =>
    this.request<{ booking: ServerBooking }>(`/api/bookings/${encodeURIComponent(id)}/resolve`, { method: "POST", body: { part } });
  // bridges (cloud, docs/BRIDGE.md)
  bridges = () => this.request<Bridge[]>("/api/bridges");
  pairBridge = (code: string, name?: string) =>
    this.request<Bridge>("/api/bridges/pair", { method: "POST", body: { code, ...(name ? { name } : {}) } });
  renameBridge = (id: string, name: string) =>
    this.request<Bridge>(`/api/bridges/${encodeURIComponent(id)}`, { method: "PATCH", body: { name } });
  deleteBridge = (id: string) =>
    this.request<{ deleted: string }>(`/api/bridges/${encodeURIComponent(id)}`, { method: "DELETE" });
  bridgeDiscover = (id: string) =>
    this.request<BridgeFound[]>(`/api/bridges/${encodeURIComponent(id)}/discover`, { method: "POST", timeout: 40000 });
  bridgeAddPrinter = (id: string, printer: { name: string; type: string; machine?: string; cosmos?: boolean }, sealed: string) =>
    this.request<Printer>(`/api/bridges/${encodeURIComponent(id)}/printers`, { method: "POST", body: { printer, sealed }, timeout: 40000 });
  bridgePrinterAccess = (printerId: string, sealed: string) =>
    this.request<{ ok: boolean }>(`/api/printers/${encodeURIComponent(printerId)}/bridge-access`, { method: "PUT", body: { sealed } });
  sources = () => this.request<Source[]>("/api/sources");
  search = (q: string, source: string, page: number, sort: SortKey) =>
    this.request<SearchPage>(`/api/search?q=${encodeURIComponent(q)}&source=${source}&page=${page}&sort=${sort}`,
      { timeout: 30000 });
  model = (source: string, id: string) =>
    this.request<ModelDetail>(`/api/models/${source}/${encodeURIComponent(id)}`, { timeout: 30000 });

  profiles = () => this.request<UserProfile[]>("/api/profiles", { timeout: 30000 });
  power = (printer: string) =>
    this.request<{ available: boolean; state: "on" | "off" | "unavailable" | "unknown" | null; error?: string | null }>(
      `/api/printers/${encodeURIComponent(printer)}/power`, { timeout: 20000 });
  setPower = (printer: string, on: boolean) =>
    this.request<{ ok: boolean }>(`/api/printers/${encodeURIComponent(printer)}/power`,
      { method: "POST", body: { on }, timeout: 20000 });
  controls = (printer: string) =>
    this.request<Controls>(`/api/printers/${encodeURIComponent(printer)}/controls`, { timeout: 20000 });
  adjust = (printer: string, kind: "heater" | "fan" | "light" | "speed", id: string, value: number | boolean,
            confirm = false) =>
    this.request<{ ok: boolean }>(`/api/printers/${encodeURIComponent(printer)}/adjust`,
      { method: "POST", body: { kind, id, value, confirm }, timeout: 20000 });
  temperatures = (printer: string) =>
    this.request<TempHistory>(`/api/printers/${encodeURIComponent(printer)}/temperatures`, { timeout: 20000 });
  cameraInfo = (printer: string) =>
    this.request<CameraInfo>(`/api/printers/${encodeURIComponent(printer)}/camera`, { timeout: 20000 });

  /** Image source for the camera (issue #3). Native image views send the token as a header; the web
   * preview and the MJPEG view inside a WebView can't, so there it goes into the URL. */
  async cameraSource(printer: string, kind: "snapshot" | "stream", width?: number, tokenInUrl = false) {
    const q = new URLSearchParams();
    if (width) q.set("w", String(width));
    if (kind === "snapshot") q.set("t", String(Date.now()));          // always a fresh image
    if ((tokenInUrl || Platform.OS === "web") && this.server.token) q.set("token", this.server.token);
    const qs = q.toString();
    return {
      uri: `${await this.base()}/api/printers/${encodeURIComponent(printer)}/camera/${kind}${qs ? `?${qs}` : ""}`,
      headers: authHeaders(this.server),
    };
  }
  deleteProfile = (file: string) =>
    this.request<{ deleted: string }>(`/api/profiles/${encodeURIComponent(file)}`, { method: "DELETE" });
  printerProfile = (printer: string) =>
    this.request<PrinterProfile>(`/api/printers/${encodeURIComponent(printer)}/profile`);
  setPrinterProfile = (printer: string, machineFile: string | null) =>
    this.request<PrinterProfile>(`/api/printers/${encodeURIComponent(printer)}/profile`,
      { method: "PUT", body: { machine_file: machineFile }, timeout: 30000 });
  /** Upload an OrcaSlicer preset (JSON) or preset bundle (zip). */
  uploadProfile = (uri: string, name: string) =>
    this.rawUpload<UserProfile[]>(`/api/profiles?filename=${encodeURIComponent(name)}`, uri);

  /** Import a bundle shared on cloud.orcaslicer.com (server 0.18.0, issue #7) - no Orca account needed. */
  /** SpoolmanDB filament presets for adding spools (server 0.19.0). */
  filamentBrands = () => this.request<{ name: string; count: number }[]>("/api/filament-db/brands", { timeout: 60000 });
  filamentPresets = (brand: string) =>
    this.request<FilamentPreset[]>(`/api/filament-db/filaments?brand=${encodeURIComponent(brand)}`, { timeout: 60000 });
  importOrcaCloud = (link: string) =>
    this.request<{ bundle: { name: string | null; author: string | null; version: string | null };
                   imported: UserProfile[]; skipped: { name: string | null; error: string }[] }>(
      "/api/profiles/orca-cloud", { method: "POST", body: { link }, timeout: 60000 });

  /** Upload a local model file (document picker or share menu) as raw body. */
  upload = (uri: string, name: string) =>
    this.rawUpload<Upload>(`/api/uploads?name=${encodeURIComponent(name)}`, uri);

  private async rawUpload<R>(path: string, uri: string): Promise<R> {
    const url = `${await this.base()}${path}`;
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
    return body as R;
  }
}


// ---------- cloud login (before there is a session) ----------
async function cloudPost<R>(t: T, path: string, body: unknown): Promise<R> {
  let res: Response;
  try {
    res = await fetch(CLOUD_URL + path, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
  } catch (e) {
    throw new ApiError(t("errOffline"), 0, String(e));
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`;
    throw new ApiError(cloudError(t, res.status, detail), res.status, detail);
  }
  return data as R;
}

function cloudError(t: T, status: number, detail: string): string {
  const d = detail.toLowerCase();
  if (d.includes("valid e-mail")) return t("errEmail");
  if (status === 429) return t("errTooManyCodes");
  if (d.includes("wrong code")) return t("errWrongCode");
  if (d.includes("expired")) return t("errCodeExpired");
  if (status === 502) return t("errMail");
  return detail;
}

export const cloudRequestCode = (t: T, email: string) =>
  cloudPost<{ sent: boolean; email: string }>(t, "/api/auth/code", { email, lang: t.lang });
/** Web app: the server keeps the session in an HttpOnly cookie and answers `token: null`. */
export const cloudLogin = (t: T, email: string, code: string) =>
  cloudPost<{ token: string | null; user: { id: string; email: string } }>(t, "/api/auth/login",
    { email, code, device: WEB_APP ? "web browser" : `${Platform.OS} app`, ...(WEB_APP ? { cookie: true } : {}) });
