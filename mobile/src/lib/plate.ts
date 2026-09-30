// Plate options per job (server 0.14.0): copies, position (tilt / lay flat), size.
import type { JobOptions } from "@/lib/api";
import type { T } from "@/lib/i18n";

/** One choice for the position; maps to rotate_x / rotate_y / orient. */
export const TILTS = {
  none: {},
  auto: { orient: true },
  forward: { rotate_x: 90 },
  back: { rotate_x: -90 },
  right: { rotate_y: 90 },
  left: { rotate_y: -90 },
  upside: { rotate_x: 180 },
} as const satisfies Record<string, JobOptions>;
export type Tilt = keyof typeof TILTS;

export const TILT_LABELS = {
  none: "tiltNone", auto: "tiltAuto", forward: "tiltForward", back: "tiltBack", right: "tiltRight",
  left: "tiltLeft", upside: "tiltUpside",
} as const satisfies Record<Tilt, string>;

export const MAX_COPIES = 50;

export function tiltOf(o?: JobOptions | null): Tilt {
  if (!o) return "none";
  if (o.orient) return "auto";
  const x = o.rotate_x ?? 0, y = o.rotate_y ?? 0;
  const hit = (Object.keys(TILTS) as Tilt[]).find(k => k !== "none" && k !== "auto" &&
    ((TILTS[k] as JobOptions).rotate_x ?? 0) === x && ((TILTS[k] as JobOptions).rotate_y ?? 0) === y);
  return hit ?? "none";
}

/** Options for /api/jobs: only what differs from "one copy, as in the model, 100 %". */
export function plateOptions(copies: number, tilt: Tilt, scale: number): JobOptions {
  const o: JobOptions = { ...TILTS[tilt] };
  if (copies > 1) o.copies = Math.min(MAX_COPIES, Math.round(copies));
  if (scale !== 100) o.scale = scale;
  return o;
}

/** "3× · Tip forward · 150 %" – empty when nothing was changed. */
export function plateSummary(t: T, o?: JobOptions | null, copies?: number | null): string {
  const out: string[] = [];
  const n = copies ?? o?.copies ?? 1;
  if (n > 1) out.push(t("copiesV", { n }));
  const tilt = tiltOf(o);
  if (tilt !== "none") out.push(t(TILT_LABELS[tilt]));
  if (o?.scale && o.scale !== 100) out.push(`${o.scale} %`);
  return out.join(" · ");
}
