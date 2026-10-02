// OpenPrintTag (https://specs.openprinttag.org): Prusa's open NFC standard for filament spools. The phone reads the tag
// memory (modules/nfc-tag, NFC-V / ISO 15693); this file finds the NDEF record "application/vnd.openprinttag" and
// decodes its CBOR sections: meta (where the regions are), main (static material data), aux (consumed amount …).
// Read only - writing (e.g. the consumed weight) must follow the spec's update rules and is not done here.

export type OpenPrintTag = {
  uid: string;                      // tag UID as the phone reported it (hex)
  brand: string | null;
  name: string | null;              // material_name, e.g. "PLA Galaxy Black"
  materialType: string | null;      // "PLA", "PETG" …
  materialClass: "FFF" | "SLA" | null;
  color: string | null;             // "#RRGGBB"
  colors: string[];                 // secondary colours
  fullWeight: number | null;        // g of material on the full spool (actual, else nominal)
  emptySpoolWeight: number | null;
  consumedWeight: number | null;    // aux region
  remainingWeight: number | null;
  density: number | null;
  diameter: number;                 // mm (1.75 if not given)
  printTemp: [number | null, number | null];
  bedTemp: [number | null, number | null];
  location: string | null;          // aux storage_location
  tags: string[];
  main: Record<number, unknown>;    // all fields, for later use
  aux: Record<number, unknown>;
};

export class TagError extends Error {}

const MIME = "application/vnd.openprinttag";

// fff_material_types (specs.openprinttag.org), key -> abbreviation
const MATERIAL_TYPES: Record<number, string> = {
  0: "PLA", 1: "PETG", 2: "TPU", 3: "ABS", 4: "ASA", 5: "PC", 6: "PCTG", 7: "PP", 8: "PA6", 9: "PA11", 10: "PA12",
  11: "PA66", 12: "CPE", 13: "TPE", 14: "HIPS", 15: "PHA", 16: "PET", 17: "PEI", 18: "PBT", 19: "PVB", 20: "PVA",
  21: "PEKK", 22: "PEEK", 23: "BVOH", 24: "TPC", 25: "PPS", 26: "PPSU", 27: "PVC", 28: "PEBA", 29: "PVDF", 30: "PPA",
  31: "PCL", 32: "PES", 33: "PMMA", 34: "POM", 35: "PPE", 36: "PS", 37: "PSU", 38: "TPI", 39: "SBS", 40: "OBC",
  41: "EVA", 42: "PA612",
};
const TAG_NAMES: Record<number, string> = {};    // material_tags: shown by key until the list is needed

// ---------------------------------------------------------------- CBOR (RFC 8949), only what the tags use
const BREAK = Symbol("break");

/** Decode one CBOR item at `pos`; returns the value and the position after it. */
export function cborDecode(b: Uint8Array, pos = 0): { value: unknown; end: number } {
  let p = pos;
  const need = (n: number) => { if (p + n > b.length) throw new TagError("tag data ends too early"); };
  const uint = (info: number): number | null => {
    if (info < 24) return info;
    if (info === 24) { need(1); return b[p++]; }
    if (info === 25) { need(2); const v = (b[p] << 8) | b[p + 1]; p += 2; return v; }
    if (info === 26) { need(4); const v = ((b[p] << 24) >>> 0) + (b[p + 1] << 16) + (b[p + 2] << 8) + b[p + 3]; p += 4; return v; }
    if (info === 27) {
      need(8); let v = 0;
      for (let i = 0; i < 8; i++) v = v * 256 + b[p + i];
      p += 8; return v;
    }
    if (info === 31) return null;              // indefinite length
    throw new TagError("unsupported CBOR length");
  };
  const item = (): unknown => {
    need(1);
    const ib = b[p++], major = ib >> 5, info = ib & 31;
    if (major === 7) {
      if (info === 31) return BREAK;
      if (info === 20) return false;
      if (info === 21) return true;
      if (info === 22 || info === 23) return null;
      const view = new DataView(b.buffer, b.byteOffset);
      if (info === 25) { need(2); const v = half((b[p] << 8) | b[p + 1]); p += 2; return v; }
      if (info === 26) { need(4); const v = view.getFloat32(p); p += 4; return v; }
      if (info === 27) { need(8); const v = view.getFloat64(p); p += 8; return v; }
      if (info < 24) return info;               // simple value
      throw new TagError("unsupported CBOR simple value");
    }
    const n = uint(info);
    switch (major) {
      case 0: return n;
      case 1: return -1 - (n ?? 0);
      case 2: case 3: {
        let bytes: Uint8Array;
        if (n === null) {                          // indefinite: chunks until break
          const parts: Uint8Array[] = [];
          for (;;) { const c = item(); if (c === BREAK) break; parts.push(major === 2 ? c as Uint8Array : new TextEncoder().encode(c as string)); }
          bytes = concat(parts);
        } else { need(n); bytes = b.slice(p, p + n); p += n; }
        return major === 2 ? bytes : new TextDecoder().decode(bytes);
      }
      case 4: {
        const arr: unknown[] = [];
        for (let i = 0; n === null || i < n; i++) { const v = item(); if (v === BREAK) break; arr.push(v); }
        return arr;
      }
      case 5: {
        const map: Record<string, unknown> = {};
        for (let i = 0; n === null || i < n; i++) {
          const k = item();
          if (k === BREAK) break;
          map[String(k)] = item();
        }
        return map;
      }
      case 6: return item();                       // tag: the tagged value
    }
    throw new TagError("bad CBOR");
  };
  const value = item();
  return { value, end: p };
}

function half(h: number): number {
  const s = h & 0x8000 ? -1 : 1, e = (h >> 10) & 0x1f, f = h & 0x3ff;
  if (e === 0) return s * 2 ** -14 * (f / 1024);
  if (e === 31) return f ? NaN : s * Infinity;
  return s * 2 ** (e - 15) * (1 + f / 1024);
}

function concat(parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((a, x) => a + x.length, 0));
  let o = 0;
  for (const x of parts) { out.set(x, o); o += x.length; }
  return out;
}

// ---------------------------------------------------------------- NFC Type 5 memory → NDEF record payload
/** The payload of the OpenPrintTag NDEF record in the tag memory (CC, TLVs, NDEF message). */
export function findPayload(mem: Uint8Array): Uint8Array {
  if (mem.length < 8 || (mem[0] !== 0xe1 && mem[0] !== 0xe2)) throw new TagError("not an NFC Forum tag (no capability container)");
  let p = mem[2] === 0 ? 8 : 4;                       // 8-byte CC when the size doesn't fit one byte
  while (p < mem.length) {
    const t = mem[p++];
    if (t === 0x00) continue;                         // NULL TLV
    if (t === 0xfe) break;                            // terminator
    let len = mem[p++];
    if (len === 0xff) { len = (mem[p] << 8) | mem[p + 1]; p += 2; }
    if (t === 0x03) return findRecord(mem.subarray(p, p + len));
    p += len;
  }
  throw new TagError("the tag has no NDEF data");
}

function findRecord(msg: Uint8Array): Uint8Array {
  let p = 0;
  while (p < msg.length) {
    const hdr = msg[p++], tnf = hdr & 7, sr = hdr & 0x10, il = hdr & 0x08, cf = hdr & 0x20;
    const typeLen = msg[p++];
    let payLen: number;
    if (sr) payLen = msg[p++];
    else { payLen = ((msg[p] << 24) >>> 0) + (msg[p + 1] << 16) + (msg[p + 2] << 8) + msg[p + 3]; p += 4; }
    const idLen = il ? msg[p++] : 0;
    const type = new TextDecoder().decode(msg.subarray(p, p + typeLen));
    p += typeLen + idLen;
    const payload = msg.subarray(p, p + payLen);
    p += payLen;
    if (tnf === 2 && type === MIME && !cf) return payload;
    if (hdr & 0x40) break;                            // message end
  }
  throw new TagError("no OpenPrintTag data on this tag");
}

// ---------------------------------------------------------------- sections
const asMap = (v: unknown): Record<number, unknown> => {
  if (!v || typeof v !== "object" || Array.isArray(v) || v instanceof Uint8Array) throw new TagError("bad OpenPrintTag section");
  return Object.fromEntries(Object.entries(v).map(([k, x]) => [Number(k), x]));
};
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : null);
const rgb = (v: unknown) => v instanceof Uint8Array && v.length >= 3
  ? `#${[...v.subarray(0, 3)].map(x => x.toString(16).padStart(2, "0")).join("").toUpperCase()}` : null;

export function parseTag(mem: Uint8Array, uid = ""): OpenPrintTag {
  const payload = findPayload(mem);
  const metaItem = cborDecode(payload, 0);
  const meta = asMap(metaItem.value);
  const mainAt = num(meta[0]) ?? metaItem.end;
  const main = asMap(cborDecode(payload, mainAt).value);
  let aux: Record<number, unknown> = {};
  const auxAt = num(meta[2]);
  if (auxAt != null && auxAt < payload.length) {
    try { aux = asMap(cborDecode(payload, auxAt).value); } catch { aux = {}; }   // a fresh/wiped aux region may be empty
  }
  const full = num(main[17]) ?? num(main[16]);
  const consumed = num(aux[0]);
  const cls = num(main[8]);
  return {
    uid, main, aux,
    brand: str(main[11]), name: str(main[10]),
    materialType: str(main[52]) ?? (num(main[9]) != null ? MATERIAL_TYPES[num(main[9])!] ?? null : null),
    materialClass: cls === 0 ? "FFF" : cls === 1 ? "SLA" : null,
    color: rgb(main[19]),
    colors: [20, 21, 22, 23, 24].map(k => rgb(main[k])).filter((c): c is string => !!c),
    fullWeight: full, emptySpoolWeight: num(main[18]), consumedWeight: consumed,
    remainingWeight: full != null ? Math.max(0, full - (consumed ?? 0)) : null,
    density: num(main[29]), diameter: num(main[30]) ?? 1.75,
    printTemp: [num(main[34]), num(main[35])], bedTemp: [num(main[37]), num(main[38])],
    location: str(aux[4]),
    tags: Array.isArray(main[28]) ? (main[28] as unknown[]).map(t => TAG_NAMES[t as number] ?? String(t)) : [],
  };
}

export function decodeBase64(b64: string): Uint8Array {
  const bin = atob(b64), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** "Prusament PLA Galaxy Black" - brand + material name, as the spec recommends for the UI. */
export const tagLabel = (t: OpenPrintTag) =>
  [t.brand, t.name ?? t.materialType].filter(Boolean).join(" ") || "OpenPrintTag";
