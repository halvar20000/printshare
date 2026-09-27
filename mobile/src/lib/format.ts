import type { T } from "./i18n";

/** "Elegoo PLA @ECC" -> "Elegoo PLA", "0.20mm Standard @Elegoo CC 0.4 nozzle" -> "0.20mm Standard" */
export const shortName = (name?: string | null) => (name || "").replace(/\s*@.*$/, "");

export const brandOf = (name: string) => shortName(name).split(" ")[0] || name;

export const plateName = (t: T, plate?: string | null) => (plate ? t.table.plates[plate] || plate : "–");

export function extractLink(text?: string | null): string {
  const m = (text || "").match(/https?:\/\/[^\s"'<>]+/);
  return m ? m[0] : "";
}

/** Display name for a job: file name, else a readable link. */
export function jobName(file?: string | null, link?: string | null): string {
  if (file) return file;
  if (!link) return "–";
  if (link.startsWith("upload:")) return link;
  const m = link.match(/printables\.com\/(?:[a-z]{2}\/)?model\/\d+-([\w-]+)/);
  if (m) return m[1].replace(/-/g, " ");
  return link.replace(/^https?:\/\/(www\.)?/, "");
}

export function ago(t: T, ts: number): string {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  try {
    const rtf = new Intl.RelativeTimeFormat(t.lang, { numeric: "auto" });
    if (s < 60) return rtf.format(-s, "second");
    if (s < 3600) return rtf.format(-Math.round(s / 60), "minute");
    if (s < 86400) return rtf.format(-Math.round(s / 3600), "hour");
    return rtf.format(-Math.round(s / 86400), "day");
  } catch {
    const v = s < 3600 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`;
    return t("ago", { v });
  }
}

export function duration(seconds?: number | null): string {
  if (seconds == null || !isFinite(seconds) || seconds < 0) return "–";
  const h = Math.floor(seconds / 3600), m = Math.round((seconds % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

/** Orca prints "1h 5m 3s" / "35m 32s"; show it without seconds. */
export function printTime(v?: string | null): string {
  if (!v) return "–";
  const h = /(\d+)d/.exec(v) ? Number(/(\d+)d/.exec(v)![1]) * 24 : 0;
  const hh = h + Number(/(\d+)h/.exec(v)?.[1] ?? 0), mm = Number(/(\d+)m/.exec(v)?.[1] ?? 0);
  if (!/\d+[dhm]/.test(v)) return v;
  return hh ? `${hh} h ${mm} min` : `${mm} min`;
}

export const temp = (v?: number | null, target?: number | null) =>
  v == null ? "–" : `${Math.round(v)}${target ? ` / ${Math.round(target)}` : ""} °C`;

/** Warnings for odd combinations (DV-04). Material names come from Orca profile names. */
export function comboWarnings(t: T, filament: string, plate: string): string[] {
  const f = filament.toUpperCase(), out: string[] = [];
  const pla = /\bPLA\b/.test(f), petg = /\bPETG\b/.test(f);
  if (pla && plate === "Engineering Plate") out.push(t("warnPlatePla"));
  if (petg && plate === "High Temp Plate") out.push(t("warnPlatePetg"));
  if (!pla && plate === "Cool Plate") out.push(t("warnCoolPlate"));
  if (/[-\s](CF|GF)\b/.test(f)) out.push(t("warnCf"));
  return out;
}
