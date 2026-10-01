// Printers the app reaches itself on the home Wi-Fi (cloud mode, docs/CLOUD.md step 1).
import { lanIo } from "./io";
import { MoonrakerPrinter } from "./moonraker";
import { OctoPrintPrinter } from "./octoprint";
import { PrusaLinkPrinter } from "./prusalink";
import { SdcpPrinter } from "./sdcp";
import type { Lan } from "./types";

export { LanError, type Lan, type SendOptions, type SendStep } from "./types";
export { lanIo } from "./io";

/** Printer types the app can talk to directly. */
export const LAN_TYPES = ["elegoo_sdcp", "moonraker", "prusalink", "octoprint"] as const;
export const canRelay = (type: string) => (LAN_TYPES as readonly string[]).includes(type);

/** How the app reaches one printer; stored only on the phone. */
export type LanAccess = { address: string; password?: string; apiKey?: string };

export function lanPrinter(type: string, access: LanAccess | string): Lan {
  const a: LanAccess = typeof access === "string" ? { address: access } : access;
  const host = a.address.trim().replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  if (type === "elegoo_sdcp") return new SdcpPrinter(host.replace(/:\d+$/, ""), lanIo);
  if (type === "moonraker") return new MoonrakerPrinter(a.address, a.apiKey);
  if (type === "prusalink") return new PrusaLinkPrinter(a.address, { password: a.password, apiKey: a.apiKey });
  if (type === "octoprint") return new OctoPrintPrinter(a.address, a.apiKey ?? "");
  throw new Error(`printer type ${type} can't be reached from the app yet`);
}
