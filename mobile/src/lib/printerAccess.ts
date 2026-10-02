// Reaching a printer: through the own server (home server), or - with the PocketPrint3D cloud - by the app itself on
// the home Wi-Fi. The printer's address stays on this phone; the cloud never sees it (docs/CLOUD.md).
import { WEB_APP, type Api, type Printer, type PrinterStatus, type Server } from "./api";
import { canRelay, lanIo, lanPrinter, LanError, type LanAccess, type SendOptions } from "./lan";
import { getJSON, setJSON } from "./storage";

export class NoAddressError extends Error {}
/** Web app: a browser can't talk to printers on the home network - only bridge printers work there. */
export class WebLanError extends Error {}

// per printer: address (+ PrusaLink password / API key); kept in the phone's secure storage, never sent to the cloud
type Stored = Record<string, LanAccess | string>;          // plain string = address only (app builds 14-16)
const key = (server: Server) => `ps_lan_${(server.email ?? server.url).replace(/[^\w.-]/g, "_")}`;

export async function loadAccess(server: Server): Promise<Record<string, LanAccess>> {
  const raw = (await getJSON<Stored>(key(server))) ?? {};
  return Object.fromEntries(Object.entries(raw).map(([id, v]) => [id, typeof v === "string" ? { address: v } : v]));
}

export async function saveAccess(server: Server, printerId: string, access: LanAccess | null): Promise<void> {
  const all = await loadAccess(server);
  if (access?.address.trim()) {
    const a: LanAccess = { address: access.address.trim() };
    if (access.password) a.password = access.password;
    if (access.apiKey?.trim()) a.apiKey = access.apiKey.trim();
    all[printerId] = a;
  } else {
    delete all[printerId];
  }
  await setJSON(key(server), all);
}

async function lanFor(server: Server, printer: Printer) {
  if (WEB_APP) throw new WebLanError(printer.id);
  if (!canRelay(printer.type)) throw new LanError("this printer type can only be used with an own server for now");
  const access = (await loadAccess(server))[printer.id];
  if (!access?.address) throw new NoAddressError(printer.id);
  return lanPrinter(printer.type, access);
}

/** Cloud printers on the home Wi-Fi are reached by the phone; own servers and bridges (docs/BRIDGE.md) by the server. */
export const viaServer = (server: Server, printer: Printer) => !server.cloud || !!printer.bridge;

export async function printerStatus(api: Api, server: Server, printer: Printer): Promise<PrinterStatus> {
  if (viaServer(server, printer)) return api.status(printer.id);
  const lan = await lanFor(server, printer);
  try {
    return await lan.status();
  } finally {
    lan.close();
  }
}

export async function printerControl(api: Api, server: Server, printer: Printer,
                                     action: "pause" | "resume" | "cancel"): Promise<void> {
  if (viaServer(server, printer)) {
    await api.control(printer.id, action);
    return;
  }
  const lan = await lanFor(server, printer);
  try {
    await lan.control(action);
  } finally {
    lan.close();
  }
}

/** Cloud: download the sliced G-code (slots already mapped by the server) and send it to the printer. */
export async function relayJob(api: Api, server: Server, printer: Printer, jobId: string, fileName: string,
                               lanes: Record<number, number> | undefined, opts: SendOptions): Promise<void> {
  const lan = await lanFor(server, printer);
  opts.onStep?.("download");
  const { url, headers } = await api.gcodeDownload(jobId, lanes);
  const file = await lanIo.download(url, headers, fileName);
  try {
    await lan.send(file, opts);
  } finally {
    file.release();
    lan.close();
  }
}

/** File name on the printer: model name + .gcode, plain characters (the Centauri's file list is picky). */
export function printerFileName(source: string | null | undefined, jobId: string): string {
  const stem = (source ?? "").replace(/\.[^.]+$/, "").replace(/[^\w.-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60);
  return `${stem || `print_${jobId}`}.gcode`;
}
