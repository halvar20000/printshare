// Slots of an AFC unit (issue #12): people think "colour 1 from slot 2", not "CANVAS_4 (T0)".
// The same rules as Dominique's iOS app (LanePlan.swift), shared by prepare.tsx and job/[id].tsx.
import type { Lane } from "./api";
import { materialOf } from "./format";

const slotNumber = (id: string) => {
  const m = id.match(/(\d+)$/);
  return m ? Number(m[1]) : null;
};

/** Lanes that have a tool, in physical order (CANVAS_1, CANVAS_2 …), with their label:
 *  "Slot N" from the number at the end of the id, the id itself if numbers are missing or repeat (two units). */
export function slots(lanes: Lane[] | null | undefined): (Lane & { slot: string })[] {
  const list = (lanes ?? []).filter(l => l.tool != null);
  const nums = list.map(l => slotNumber(l.id));
  const numbered = nums.every(n => n != null) && new Set(nums).size === nums.length;
  const order = (i: number) => (numbered ? nums[i]! : i);
  return list.map((l, i) => ({ l: { ...l, slot: numbered ? `Slot ${nums[i]}` : l.id }, o: order(i) }))
    .sort((a, b) => a.o - b.o).map(x => x.l);
}

/** Material of a lane in the same words as the presets ("PLA", "PETG" …). */
export const laneMaterial = (l?: Lane | null) => materialOf(l?.material) ?? (l?.material || null);

/** Does a preset fit the material in a lane? Unknown on either side counts as fitting. */
export function fits(preset: string | null | undefined, lane?: Lane | null): boolean {
  const want = materialOf(preset), have = (lane?.material ?? "").toUpperCase();
  return !want || !have || have.startsWith(want);
}

/** Preset for slicing that follows the slot: a preset named like the lane's filament, else the last choice,
 *  else the standard preset if it has that material, else the first preset of that material. */
export function presetForLane(lane: Lane | null | undefined, materials: string[], last: string | null,
                              standard: string | null): string | null {
  if (!lane?.loaded) return null;
  const name = (lane.filament ?? "").trim().toLowerCase();
  if (name) {
    const named = materials.find(m => m.toLowerCase().startsWith(name));
    if (named) return named;
  }
  const mat = laneMaterial(lane);
  if (!mat) return null;
  if (last && materials.includes(last) && materialOf(last) === mat) return last;
  if (standard && materials.includes(standard) && materialOf(standard) === mat) return standard;
  return materials.find(m => materialOf(m) === mat) ?? null;
}

const hex = (c?: string | null) =>
  (c && /^#[0-9a-f]{6}$/i.test(c) ? [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16)) : null);
function colorDistance(a?: string | null, b?: string | null): number {
  const x = hex(a), y = hex(b);
  return x && y ? x.reduce((s, v, i) => s + (v - y[i]) ** 2, 0) : 1e6;
}

/** Default slot per model colour: a loaded slot with the closest colour, each slot once if possible;
 *  without colours (single-colour model) the slot in the toolhead, else the first loaded one.
 *  With a preset (after slicing) slots holding its material come first. `fixed` = choices already made. */
export function defaultSlots(colors: { index: number; color?: string | null; preset?: string | null }[],
                             lanes: Lane[], fixed: Record<number, number> = {}): Record<number, number> {
  const loaded = lanes.filter(l => l.loaded);
  const out: Record<number, number> = {};
  const taken = new Set(Object.values(fixed));
  for (const c of colors) {
    if (fixed[c.index] != null) { out[c.index] = fixed[c.index]; continue; }
    const candidates = loaded.filter(l => fits(c.preset, l));
    const pool = candidates.length ? candidates : loaded;
    const free = pool.filter(l => !taken.has(l.tool!));
    const from = free.length ? free : pool;
    const pick = c.color
      ? [...from].sort((a, b) => colorDistance(a.color, c.color) - colorDistance(b.color, c.color))[0]
      : from.find(l => l.in_toolhead) ?? from[0];
    const lane = pick ?? lanes[0];
    if (lane?.tool != null) { out[c.index] = lane.tool; taken.add(lane.tool); }
  }
  return out;
}
