// Reading OpenPrintTag spools with the phone (Android, modules/nfc-tag) and finding the matching spool.
import NfcTag from "../../modules/nfc-tag/src/NfcTagModule";
import type { T } from "./i18n";
import { decodeBase64, parseTag, TagError, type OpenPrintTag } from "./openprinttag";
import type { Api } from "./api";
import type { Spool } from "./spoolman";

/** Is NFC there at all? ("none": no hardware / not Android - hide the NFC buttons) */
export function nfcStatus(): "on" | "off" | "none" {
  try { return NfcTag.status(); } catch { return "none"; }
}

/** Wait for a tag (max 30 s) and read it; errors come back translated. */
export async function scanSpool(t: T): Promise<OpenPrintTag> {
  try {
    const raw = await NfcTag.readAsync(30000);
    return parseTag(decodeBase64(raw.data), raw.uid);
  } catch (e) {
    if (e instanceof TagError) throw new Error(t("nfcNotOpt"));
    const code = (e as { code?: string }).code ?? "";
    if (code === "ERR_NFC_OFF") throw new Error(t("nfcOff"));
    if (code === "ERR_NFC_UNAVAILABLE") throw new Error(t("nfcNone"));
    if (code === "ERR_NFC_TIMEOUT") throw new Error(t("nfcTimeout"));
    if (code === "ERR_NFC_CANCELLED") throw new Error("");
    throw new Error(t("nfcReadFailed"));
  }
}

export const cancelScan = () => NfcTag.cancelAsync().catch(() => {});

function rgb(hex: string | null): number[] | null {
  const m = (hex ?? "").replace("#", "").match(/^([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i);
  return m ? [1, 2, 3].map(i => parseInt(m[i], 16)) : null;
}
const colorDistance = (a: string | null, b: string | null) => {
  const x = rgb(a), y = rgb(b);
  return x && y ? Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) : null;
};
const norm = (s: string | null | undefined) => (s ?? "").toLowerCase().replace(/[^a-z0-9+]/g, "");

/** The spool a scanned tag belongs to: same material, then brand, name and colour; among equal ones the one whose
 *  remaining weight is closest to the tag's. null if no spool has that material. */
export function matchSpool(tag: OpenPrintTag, spools: Spool[]): Spool | null {
  const type = norm(tag.materialType);
  let best: { s: Spool; score: number; diff: number } | null = null;
  for (const s of spools) {
    const mat = norm(s.material);
    if (!type || !mat || !(mat.startsWith(type) || type.startsWith(mat))) continue;
    let score = 0;
    if (tag.brand && norm(s.vendor) && (norm(s.vendor).includes(norm(tag.brand)) || norm(tag.brand).includes(norm(s.vendor)))) score += 3;
    const tn = norm(tag.name), sn = norm(s.name);
    if (tn && sn && (tn.includes(sn) || sn.includes(tn))) score += 2;
    const d = colorDistance(tag.color, s.color);
    if (d != null) score += d < 40 ? 2 : d < 90 ? 1 : -1;
    const diff = tag.remainingWeight != null && s.remaining_g != null ? Math.abs(tag.remainingWeight - s.remaining_g) : 1e9;
    if (!best || score > best.score || (score === best.score && diff < best.diff)) best = { s, score, diff };
  }
  return best && best.score >= 2 ? best.s : null;
}


// ---------- any NFC chip: linked to a spool once by its chip number (server 0.38.0, /api/spool-tags) ----------
/** A chip held to the phone: its number (hex, upper case) and - for an OpenPrintTag - what is written in it. */
export type Chip = { uid: string; tag: OpenPrintTag | null };

/** Wait for any chip: OpenPrintTag / ISO 15693 (content read), NTAG sticker or a Bambu spool's tag (number only). */
export async function scanChip(t: T): Promise<Chip> {
  let raw: { uid: string; data: string };
  try {
    raw = await NfcTag.readAsync(30000);
  } catch (e) {
    const code = (e as { code?: string }).code ?? "";
    if (code === "ERR_NFC_OFF") throw new Error(t("nfcOff"));
    if (code === "ERR_NFC_UNAVAILABLE") throw new Error(t("nfcNone"));
    if (code === "ERR_NFC_TIMEOUT") throw new Error(t("nfcTimeout"));
    if (code === "ERR_NFC_CANCELLED") throw new Error("");
    throw new Error(t("nfcReadFailed"));
  }
  let tag: OpenPrintTag | null = null;
  if (raw.data) {
    try { tag = parseTag(decodeBase64(raw.data), raw.uid); } catch { tag = null; }   // blank or another format
  }
  return { uid: raw.uid.replace(/[^0-9a-f]/gi, "").toUpperCase(), tag };
}

/** The spool of a chip: linked on the server by its number, else (OpenPrintTag) by what the tag says. */
export async function identifyChip(api: Api | null, chip: Chip, spools: Spool[]): Promise<Spool | null> {
  if (api) {
    try {
      const linked = (await api.spoolTag(chip.uid)).spool;
      const sp = linked != null ? spools.find(s => s.id === linked) : undefined;
      if (sp) return sp;
    } catch { /* older server: no links yet */ }
  }
  return chip.tag ? matchSpool(chip.tag, spools) : null;
}
