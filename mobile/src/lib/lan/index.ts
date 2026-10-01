// Printers the app reaches itself on the home Wi-Fi (cloud mode, docs/CLOUD.md step 1).
import { lanIo } from "./io";
import { MoonrakerPrinter } from "./moonraker";
import { SdcpPrinter } from "./sdcp";
import type { Lan } from "./types";

export { LanError, type Lan, type SendOptions, type SendStep } from "./types";
export { lanIo } from "./io";

/** Printer types the app can talk to directly (PrusaLink / OctoPrint follow later). */
export const LAN_TYPES = ["elegoo_sdcp", "moonraker"] as const;
export const canRelay = (type: string) => (LAN_TYPES as readonly string[]).includes(type);

export function lanPrinter(type: string, address: string): Lan {
  const host = address.trim().replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  if (type === "elegoo_sdcp") return new SdcpPrinter(host.replace(/:\d+$/, ""), lanIo);
  if (type === "moonraker") return new MoonrakerPrinter(address);
  throw new Error(`printer type ${type} can't be reached from the app yet`);
}
