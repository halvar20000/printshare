// Spoolman (spec MA-07): choose the spool per colour, check what's left, book the used filament after the print.
// The app talks to Spoolman itself on the home Wi-Fi (like to the printers in cloud mode); the address stays on
// this phone. Printers whose Moonraker has its own [spoolman] link book the filament themselves (status "spoolman").
// API: https://donkie.github.io/Spoolman/ (GET /api/v1/spool, PUT /api/v1/spool/{id}/use {use_weight}).
// Cloud accounts without a server at home can keep their spools in the PocketPrint3D cloud instead (server 0.17.0,
// same API under <cloud>/spoolman with the session token; creating/editing spools is PocketPrint3D's own shape).
import { authHeaders, type PrinterStatus, type Server } from "./api";
import { getJSON, setJSON } from "./storage";

export type Spool = {
  id: number; name: string; vendor: string | null; material: string | null; color: string | null;
  remaining_g: number | null; location: string | null;
  /** for editing cloud spools */
  filament_g: number | null; initial_g: number | null; comment: string | null; archived: boolean;
};
/** Create / change a spool in the PocketPrint3D cloud (not a real Spoolman: there a spool needs a filament id). */
export type SpoolInput = {
  filament?: { name?: string | null; vendor?: string | null; material?: string | null; color_hex?: string | null;
               weight?: number | null; density?: number | null };
  spool_weight?: number | null;
  remaining_weight?: number | null; location?: string | null; comment?: string | null; archived?: boolean;
};

export class SpoolmanError extends Error {}

type Raw = Record<string, any>;

export class Spoolman {
  private base: string | null = null;
  private candidates: string[];

  constructor(address: string, private headers: Record<string, string> = {}) {
    const a = address.trim().replace(/\/+$/, "").replace(/\/api\/v1$/, "");
    const url = /^https?:\/\//.test(a) ? a : `http://${a}`;
    // Spoolman listens on 7912 unless a port or a proxy path is given
    const rest = url.replace(/^https?:\/\//, "");
    this.candidates = /:\d+(\/|$)/.test(rest) || rest.includes("/") ? [url] : [url, `${url}:7912`];
  }

  private async call(method: string, path: string, body?: unknown, timeoutMs = 8000): Promise<Response> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(`${await this.resolve()}/api/v1${path}`, { method, signal: ctrl.signal,
        headers: { ...this.headers, ...(body ? { "Content-Type": "application/json" } : {}) },
        body: body ? JSON.stringify(body) : undefined });
    } catch (e) {
      if (e instanceof SpoolmanError) throw e;
      throw new SpoolmanError("Spoolman not reachable");
    } finally {
      clearTimeout(timer);
    }
  }

  private async resolve(): Promise<string> {
    if (this.base) return this.base;
    for (const base of this.candidates) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 5000);
      try {
        const r = await fetch(`${base}/api/v1/info`, { signal: ctrl.signal, headers: this.headers });
        if (r.ok && "version" in (await r.json())) return (this.base = base);
      } catch { /* try the next one */ } finally {
        clearTimeout(timer);
      }
    }
    throw new SpoolmanError("Spoolman not reachable");
  }

  async info(): Promise<{ version: string; base: string }> {
    const r = await this.call("GET", "/info");
    if (!r.ok) throw new SpoolmanError(`Spoolman answered HTTP ${r.status}`);
    return { version: String((await r.json()).version ?? ""), base: this.base! };
  }

  /** Spools that are not archived, recently used first; empty ones (0 g left, not archived yet) at the end. */
  async spools(archived = false): Promise<Spool[]> {
    const r = await this.call("GET", `/spool?allow_archived=${archived}&sort=last_used:desc,id:asc`);
    if (!r.ok) throw new SpoolmanError(`Spoolman answered HTTP ${r.status}`);
    const list = ((await r.json()) as Raw[]).filter(s => archived || !s.archived).map(toSpool);
    const empty = (s: Spool) => s.remaining_g != null && s.remaining_g < 1;
    return [...list.filter(s => !empty(s)), ...list.filter(empty)];
  }

  /** Book used filament (grams) on a spool. */
  async use(spoolId: number, grams: number): Promise<Spool> {
    const r = await this.call("PUT", `/spool/${spoolId}/use`, { use_weight: Math.round(grams * 10) / 10 });
    if (r.status === 404) throw new SpoolmanError(`spool #${spoolId} no longer exists`);
    if (!r.ok) throw new SpoolmanError(`Spoolman answered HTTP ${r.status}`);
    return toSpool(await r.json());
  }

  // ---------- PocketPrint3D cloud spools only ----------
  private async send(method: string, path: string, body?: unknown): Promise<Raw> {
    const r = await this.call(method, path, body);
    if (!r.ok) {
      let detail = "";
      try { detail = (await r.json()).detail; } catch { /* plain status */ }
      throw new SpoolmanError(typeof detail === "string" && detail ? detail : `HTTP ${r.status}`);
    }
    return r.json();
  }
  create = async (spool: SpoolInput) => toSpool(await this.send("POST", "/spool", spool));
  update = async (id: number, spool: SpoolInput) => toSpool(await this.send("PATCH", `/spool/${id}`, spool));
  remove = async (id: number) => { await this.send("DELETE", `/spool/${id}`); };
}

function toSpool(s: Raw): Spool {
  const f: Raw = s.filament ?? {};
  const hex = String(f.color_hex ?? f.multi_color_hexes ?? "").split(",")[0].replace("#", "");
  return {
    id: Number(s.id), name: f.name ?? "", vendor: f.vendor?.name ?? null, material: f.material ?? null,
    color: /^[0-9A-Fa-f]{6}/.test(hex) ? `#${hex.slice(0, 6).toUpperCase()}` : null,
    remaining_g: typeof s.remaining_weight === "number" ? s.remaining_weight : null, location: s.location ?? null,
    filament_g: typeof f.weight === "number" ? f.weight : null,
    initial_g: typeof s.initial_weight === "number" ? s.initial_weight : null,
    comment: s.comment ?? null, archived: !!s.archived,
  };
}

/** "#3 Elegoo PLA Black" */
export const spoolLabel = (s: Spool) => [`#${s.id}`, s.vendor, s.name || s.material].filter(Boolean).join(" ");

// ---------- stored on the phone, per server / cloud account ----------
const sk = (server: Server) => (server.email ?? server.url).replace(/[^\w.-]/g, "_");

export const loadSpoolmanUrl = async (server: Server) => (await getJSON<{ url: string }>(`ps_spoolman_${sk(server)}`))?.url ?? null;
/** Stored instead of an address: the spools are kept in the PocketPrint3D cloud account. */
export const CLOUD_SPOOLS = "cloud";
/** The Spoolman behind a stored setting: the user's own server, or the cloud account's spools. */
export const openSpoolman = (server: Server, url: string) => url === CLOUD_SPOOLS
  ? new Spoolman(`${server.url.replace(/\/+$/, "")}/spoolman`, authHeaders(server))
  : new Spoolman(url);
export const saveSpoolmanUrl = (server: Server, url: string | null) =>
  setJSON(`ps_spoolman_${sk(server)}`, url?.trim() ? { url: url.trim() } : null);

/** Last spool per colour of a printer (default for the next print). */
export const loadLastSpools = async (server: Server, printer: string) =>
  (await getJSON<Record<string, number>>(`ps_spools_${sk(server)}_${printer.replace(/[^\w.-]/g, "_")}`)) ?? {};
export const saveLastSpools = (server: Server, printer: string, v: Record<string, number>) =>
  setJSON(`ps_spools_${sk(server)}_${printer.replace(/[^\w.-]/g, "_")}`, v);

// ---------- bookings: filament to book once the print is over ----------
export type BookingUse = { spool: number; grams: number; label: string };
export type Booking = {
  id: string; printer: string; printerName: string; file: string; uses: BookingUse[]; created: number;
  seen?: boolean;              // the printer was seen printing this file
  progress?: number;           // last progress seen (%)
  ready?: boolean;             // finished: book as soon as Spoolman answers
  ask?: { part: number };      // outcome unclear (cancelled, missed): the user decides; part = suggested share 0..1
};

const MAX_BOOKINGS = 20;
const bk = (server: Server) => `ps_bookings_${sk(server)}`;
export const loadBookings = async (server: Server) => (await getJSON<Booking[]>(bk(server))) ?? [];
const saveBookings = (server: Server, list: Booking[]) => setJSON(bk(server), list.slice(-MAX_BOOKINGS));

export async function addBooking(server: Server, b: Omit<Booking, "id" | "created">): Promise<void> {
  if (!b.uses.length) return;
  const list = (await loadBookings(server)).filter(x => !(x.printer === b.printer && !x.seen && !x.ask));
  list.push({ ...b, id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, created: Date.now() });
  await saveBookings(server, list);
}

export async function dropBooking(server: Server, id: string): Promise<void> {
  await saveBookings(server, (await loadBookings(server)).filter(b => b.id !== id));
}

/** The same print? File names on the printer may be shortened or cleaned up (PrusaLink: plain FAT names). */
export function sameFile(a: string | null | undefined, b: string): boolean {
  const norm = (s: string) => s.split("/").pop()!.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9]/g, "");
  return !!a && !!norm(b) && norm(a) === norm(b);
}

const WAIT_START_MS = 20 * 60 * 1000;       // heating + leveling can take a while before the file shows up
const GIVE_UP_MS = 3 * 24 * 3600 * 1000;    // printer never seen again

/** What to do with a booking given the printer's status now (null = not reachable). Pure, for tests. */
export function judge(b: Booking, st: PrinterStatus | null, now = Date.now()): Booking {
  if (b.ready || b.ask) return b;
  const age = now - b.created;
  if (!st) return age > GIVE_UP_MS ? { ...b, ask: { part: 1 } } : b;
  if (sameFile(st.file, b.file)) {
    const progress = typeof st.progress === "number" ? st.progress : b.progress;
    switch (st.kind) {
      case "active": case "paused": return { ...b, seen: true, progress };
      case "done": return { ...b, ready: true };
      case "stopped": case "error": return { ...b, ask: { part: Math.min(1, (progress ?? 0) / 100) } };
      default:      // idle with the file still shown (e.g. PrusaLink after FINISHED)
        if (b.seen && (b.progress ?? 0) >= 99) return { ...b, ready: true };
        if (b.seen) return { ...b, ask: { part: Math.min(1, (b.progress ?? 0) / 100) } };
        return age > WAIT_START_MS ? { ...b, ask: { part: 1 } } : b;
    }
  }
  // the printer shows something else now: finished unseen (app closed) or replaced
  if (b.seen) return (b.progress ?? 0) >= 99 ? { ...b, ready: true } : { ...b, ask: { part: Math.min(1, (b.progress ?? 0) / 100) } };
  return age > WAIT_START_MS ? { ...b, ask: { part: 1 } } : b;
}

let settling: Promise<unknown> | null = null;

/** Called with fresh printer statuses (printers tab): finished prints are booked, unclear ones are kept for the user.
 *  Returns what was booked now and what waits for a decision. */
export async function settleBookings(server: Server, statuses: Record<string, PrinterStatus | null>):
  Promise<{ booked: Booking[]; open: Booking[]; error?: string }> {
  while (settling) await settling.catch(() => {});
  const run = (async () => {
    const before = await loadBookings(server);
    if (!before.length) return { booked: [], open: [] };
    const list = before.map(b => (b.printer in statuses ? judge(b, statuses[b.printer]) : b));
    const booked: Booking[] = [];
    let error: string | undefined;
    const url = await loadSpoolmanUrl(server);
    for (const b of list.filter(x => x.ready)) {
      if (!url) break;
      const uses = b.uses.slice();             // bookUses empties the list as it goes
      try {
        await bookUses(server, url, b, 1, list);
        booked.push({ ...b, uses });
      } catch (e) {
        error = (e as Error).message;            // retried with the next status refresh
        break;
      }
    }
    const done = new Set(booked.map(b => b.id));
    const rest = list.filter(b => !done.has(b.id));
    await saveBookings(server, rest);
    return { booked, open: rest.filter(b => b.ask), error };
  })();
  settling = run;
  try { return await run; } finally { settling = null; }
}

/** Book a share of a booking (1 = all); spools already booked are removed from it, so a retry never books twice. */
async function bookUses(server: Server, url: string, b: Booking, part: number, list: Booking[]): Promise<void> {
  const sm = openSpoolman(server, url);
  while (b.uses.length) {
    const u = b.uses[0];
    const grams = u.grams * part;
    if (grams >= 0.05) await sm.use(u.spool, grams);
    b.uses.shift();
    await saveBookings(server, list);
  }
}

/** The user's decision on an open booking: book `part` of the filament (0 = discard). */
export async function resolveBooking(server: Server, id: string, part: number): Promise<void> {
  while (settling) await settling.catch(() => {});
  const list = await loadBookings(server);
  const b = list.find(x => x.id === id);
  if (!b) return;
  if (part > 0) {
    const url = await loadSpoolmanUrl(server);
    if (!url) throw new SpoolmanError("no Spoolman address set");
    await bookUses(server, url, b, part, list);
  }
  await saveBookings(server, list.filter(x => x.id !== id));
}
