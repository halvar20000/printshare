// What the app needs from a printer it reaches itself on the home Wi-Fi (cloud mode).
import type { PrinterKind, PrinterStatus } from "../api";
import type { GcodeFile } from "./io";

export type SendStep = "download" | "upload" | "start";
export type SendOptions = {
  start: boolean;
  leveling?: boolean | null;
  spoolId?: number;                         // Klipper: Spoolman spool Moonraker books the print on
  onStep?: (step: SendStep) => void;
  onProgress?: (part: number) => void;      // 0..1 of the upload
};

export interface Lan {
  status(): Promise<PrinterStatus>;
  send(file: GcodeFile, opts: SendOptions): Promise<void>;
  control(action: "pause" | "resume" | "cancel"): Promise<void>;
  close(): void;
}

export class LanError extends Error {}

export const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

/** Same buckets as the server's api.printer_kind, so the screens work alike at home and in the cloud. */
export function kindOf(state: string | null | undefined): PrinterKind {
  const s = (state ?? "").toLowerCase();
  if (!s) return "unknown";
  if (["paused", "unloading_paused", "attention"].includes(s)) return "paused";
  if (["idle", "standby", "ready"].includes(s)) return "idle";
  if (["completed", "complete"].includes(s)) return "done";
  if (["stopped", "cancelled"].includes(s)) return "stopped";
  if (["error", "offline"].includes(s)) return "error";
  return "active";
}
