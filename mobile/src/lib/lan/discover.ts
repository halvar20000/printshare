// Finding printers on the home Wi-Fi (beginner audit P1 #1): nobody should have to look up an IP address.
//  - Elegoo Centauri Carbon (stock firmware): SDCP UDP discovery, "M99999" to port 3000 - every printer answers with
//    {"Data": {"Name", "MachineName", "BrandName", "MainboardIP", "FirmwareVersion", ...}} (checked on Thomas' CC).
//  - Klipper/Moonraker, PrusaLink, OctoPrint: a short HTTP probe of every address of the phone's /24 network:
//    Moonraker `GET /server/info` (port 80 behind Mainsail/Fluidd/COSMOS, else 7125), PrusaLink `GET /api/v1/info`
//    → 401 with digest realm "Printer API", OctoPrint's web page. COSMOS by its macros (`_COSMOS_SETTINGS`).
// Platform-independent: the UDP socket and the phone's address come in as `deps` (Android: modules/lan-discovery).

export type FoundType = "elegoo_sdcp" | "moonraker" | "prusalink" | "octoprint" | "bambu_lan";
/** machine: OrcaSlicer printer preset when the printer tells its model (Bambu, found by a bridge) */
export type Found = { type: FoundType; address: string; name: string; cosmos?: boolean; detail?: string; machine?: string };
export type WifiAddress = { address: string; prefix: number };
export type UdpAnswer = { address: string; data: string };

export type DiscoverDeps = {
  wifi: () => Promise<WifiAddress | null>;
  udp: (message: string, port: number, targets: string[], timeoutMs: number) => Promise<UdpAnswer[]>;
  fetch?: typeof fetch;
  /** tests: other ports than the printers' real ones, and fixed host lists */
  webPort?: number;
  moonrakerPort?: number;
  hosts?: string[];
  concurrency?: number;
  timeoutMs?: number;
};

export class NoWifiError extends Error {
  constructor() { super("not on a Wi-Fi"); }
}

const ip2n = (ip: string) => ip.split(".").reduce((n, p) => n * 256 + (Number(p) & 255), 0);
const n2ip = (n: number) => [24, 16, 8, 0].map(s => Math.floor(n / 2 ** s) % 256).join(".");
const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

/** Addresses to probe: the phone's network, at most the /24 around its own address (bigger networks are rare at home
 *  and would take minutes). The phone's own address is left out. */
export function subnetHosts(address: string, prefix: number): string[] {
  if (!IPV4.test(address)) return [];
  const p = Math.max(24, Math.min(30, prefix || 24));
  const size = 2 ** (32 - p);
  const own = ip2n(address);
  const net = own - (own % size);
  const out: string[] = [];
  for (let n = net + 1; n < net + size - 1; n++) if (n !== own) out.push(n2ip(n));
  return out;
}

export function broadcastAddress(address: string, prefix: number): string {
  const size = 2 ** (32 - Math.max(8, Math.min(30, prefix || 24)));
  const own = ip2n(address);
  return n2ip(own - (own % size) + size - 1);
}

/** One SDCP discovery answer → printer (null for anything else on that port). */
export function parseSdcp(a: UdpAnswer): Found | null {
  try {
    const obj = JSON.parse(a.data);
    const d = obj && typeof obj === "object" ? (obj.Data && typeof obj.Data === "object" ? obj.Data : obj) : null;
    if (!d || !(d.MainboardID || d.MachineName || d.Name)) return null;
    const address = typeof d.MainboardIP === "string" && IPV4.test(d.MainboardIP) ? d.MainboardIP : a.address;
    const model = [d.BrandName, d.MachineName].filter(Boolean).join(" ");
    return { type: "elegoo_sdcp", address, name: String(d.Name || d.MachineName || "Centauri Carbon"),
             detail: [model, d.FirmwareVersion].filter(Boolean).join(" · ") || undefined };
  } catch {
    return null;
  }
}

type Probe = { status: number; headers: Headers; text: string } | null;

async function probe(f: typeof fetch, url: string, ms: number): Promise<Probe> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await f(url, { signal: ctl.signal, headers: { Accept: "application/json, text/html" } });
    // web pages can be big; the first 64 kB are enough to recognise them
    const text = (await r.text()).slice(0, 65536);
    return { status: r.status, headers: r.headers, text };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

const json = (p: Probe): any => {
  try { return p && p.status === 200 ? JSON.parse(p.text) : null; } catch { return null; }
};
const withPort = (host: string, port: number) => (port === 80 ? host : `${host}:${port}`);

/** What answers at this address? null = no printer we know. */
export async function identify(host: string, deps: Pick<DiscoverDeps, "fetch" | "webPort" | "moonrakerPort" | "timeoutMs">): Promise<Found | null> {
  const f = deps.fetch ?? fetch;
  const ms = deps.timeoutMs ?? 1500;
  const webPort = deps.webPort ?? 80, mrPort = deps.moonrakerPort ?? 7125;
  const web = `http://${withPort(host, webPort)}`;
  const [onWeb, onMr] = await Promise.all([probe(f, `${web}/server/info`, ms), probe(f, `http://${host}:${mrPort}/server/info`, ms)]);
  const isMoonraker = (p: Probe) => {
    const r = json(p)?.result;
    return !!r && typeof r === "object" && ("klippy_state" in r || "moonraker_version" in r || "klippy_connected" in r);
  };
  const mrBase = isMoonraker(onWeb) ? web : isMoonraker(onMr) ? `http://${host}:${mrPort}` : null;
  if (mrBase) {
    const [objs, info] = await Promise.all([probe(f, `${mrBase}/printer/objects/list`, ms * 2), probe(f, `${mrBase}/printer/info`, ms * 2)]);
    const objects: string[] = json(objs)?.result?.objects ?? [];
    const cosmos = objects.some(o => /cosmos/i.test(o));
    const hostname = String(json(info)?.result?.hostname ?? "");
    // MoonrakerPrinter tries the address and then :7125 itself
    const address = mrBase === web ? withPort(host, webPort) : (mrPort === 7125 ? host : `${host}:${mrPort}`);
    return { type: "moonraker", address, cosmos, name: cosmos ? "Centauri Carbon (COSMOS)" : hostname || "Klipper",
             detail: cosmos ? "OpenCentauri COSMOS" : hostname ? "Klipper" : undefined };
  }
  if (!onWeb) return null;                                       // nothing (or no web server) at this address
  const pl = await probe(f, `${web}/api/v1/info`, ms);
  if (pl && pl.status === 401 && /realm="?Printer API/i.test(pl.headers.get("www-authenticate") ?? "")) {
    return { type: "prusalink", address: withPort(host, webPort), name: "Prusa", detail: "PrusaLink" };
  }
  const page = onWeb.status === 404 || onWeb.status === 401 || onWeb.status === 403 ? await probe(f, `${web}/`, ms) : onWeb;
  if (page && /octoprint/i.test(page.text)) {
    return { type: "octoprint", address: withPort(host, webPort), name: "OctoPrint", detail: "OctoPrint" };
  }
  return null;
}

/** Find printers; `onFound` is called for each one as soon as it answers. Throws NoWifiError when the phone isn't on a
 *  Wi-Fi. `cancelled()` stops the scan early (screen closed). */
export async function discoverPrinters(deps: DiscoverDeps, onFound: (f: Found) => void,
                                       cancelled: () => boolean = () => false,
                                       onProgress?: (done: number, total: number) => void): Promise<number> {
  const wifi = await deps.wifi();
  if (!wifi && !deps.hosts) throw new NoWifiError();
  const seen = new Set<string>();
  const report = (p: Found | null) => {
    if (!p || cancelled()) return;
    const host = p.address.replace(/:\d+$/, "");
    if (seen.has(host)) return;
    seen.add(host);
    onFound(p);
  };
  const hosts = deps.hosts ?? subnetHosts(wifi!.address, wifi!.prefix);
  const udp = (async () => {
    const targets = wifi ? ["255.255.255.255", broadcastAddress(wifi.address, wifi.prefix)] : hosts;
    for (const a of await deps.udp("M99999", 3000, targets, 2500).catch(() => [] as UdpAnswer[])) report(parseSdcp(a));
  })();
  let next = 0, done = 0;
  const worker = async () => {
    while (next < hosts.length && !cancelled()) {
      const host = hosts[next++];
      // a Centauri found by UDP needs no HTTP probe (its web server is only the upload endpoint)
      const found = seen.has(host) ? null : await identify(host, deps).catch(() => null);
      report(found);
      onProgress?.(++done, hosts.length);
    }
  };
  await Promise.all([udp, ...Array.from({ length: Math.max(1, deps.concurrency ?? 24) }, worker)]);
  return seen.size;
}

// ---------- PocketPrint3D bridges on the Wi-Fi (ready-made Raspberry Pi image): found and paired with one tap ----------
export type FoundBridge = { address: string; name: string; version: string; bridgeId: string | null;
  paired: boolean; account: string | null; pairable: boolean; bridgeOnly: boolean };

/** `GET /api/bridge/hello` (no token) at one address; only bridges count, not other PocketPrint3D servers. */
export async function bridgeHello(base: string, f: typeof fetch = fetch, ms = 1500): Promise<FoundBridge | null> {
  const h = json(await probe(f, `${base}/api/bridge/hello`, ms));
  if (!h || h.pocketprint3d !== "bridge") return null;
  return { address: base, name: String(h.name || "PocketPrint3D"), version: String(h.version || ""),
           bridgeId: typeof h.bridge_id === "string" ? h.bridge_id : null, paired: !!h.paired,
           account: typeof h.account === "string" ? h.account : null, pairable: !!h.pairable,
           bridgeOnly: !!h.bridge_only };
}

/** The pairing code of a found bridge - it hands it out only on its home network (server: /api/bridge/local-code). */
export async function bridgeLocalCode(base: string, f: typeof fetch = fetch): Promise<string> {
  const r = await f(`${base}/api/bridge/local-code`, { headers: { Accept: "application/json" } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok || typeof body.code !== "string") throw new Error(String(body.detail || `HTTP ${r.status}`));
  return body.code;
}

/** Bridges on the phone's network: the Pi image answers on port 80 (also as pocketprint3d.local), a bridge container on
 *  8484. `onFound` per bridge as soon as it answers. */
export async function discoverBridges(deps: Pick<DiscoverDeps, "wifi" | "fetch" | "hosts" | "concurrency" | "timeoutMs"> & { ports?: number[] },
                                      onFound: (b: FoundBridge) => void,
                                      cancelled: () => boolean = () => false): Promise<number> {
  const wifi = deps.hosts ? null : await deps.wifi();
  if (!wifi && !deps.hosts) throw new NoWifiError();
  const f = deps.fetch ?? fetch;
  const ms = deps.timeoutMs ?? 1500;
  const ports = deps.ports ?? [80, 8484];
  const seen = new Set<string>();
  const report = (b: FoundBridge | null) => {
    if (!b || cancelled()) return;
    const key = b.bridgeId ?? b.address;
    if (seen.has(key)) return;
    seen.add(key);
    onFound(b);
  };
  const hosts = deps.hosts ?? subnetHosts(wifi!.address, wifi!.prefix);
  let next = 0;
  const worker = async () => {
    while (next < hosts.length && !cancelled()) {
      const host = hosts[next++];
      for (const port of ports) report(await bridgeHello(`http://${withPort(host, port)}`, f, ms).catch(() => null));
    }
  };
  await Promise.all([
    deps.hosts ? Promise.resolve() : bridgeHello("http://pocketprint3d.local", f, ms).then(report).catch(() => undefined),
    ...Array.from({ length: Math.max(1, deps.concurrency ?? 24) }, worker),
  ]);
  return seen.size;
}
