// What a Bambu report means (pure, tested in node) - the same rules as the server's printshare/printers/bambu.py.
import type { Lane, PrinterStatus } from "../api";
import { kindOf } from "./types";

type Raw = Record<string, any>;

// gcode_state → the names the rest of the app understands
const STATES: Record<string, string> = {
  IDLE: "standby", PREPARE: "printing", SLICING: "printing", RUNNING: "printing", PAUSE: "paused", FINISH: "complete",
  FAILED: "error",
};
const CANCELLED = new Set([0, 50348044]);              // print_error "the task was cancelled"
export const SPEED_LEVELS: Record<number, number> = { 1: 50, 2: 100, 3: 124, 4: 166 };
const FANS: Record<string, string> = { part: "cooling_fan_speed", aux: "big_fan1_speed", chamber: "big_fan2_speed" };
export const STARTING = new Set(["PREPARE", "SLICING", "RUNNING"]);
// serial number prefix → model (OrcaSlicer preset "Bambu Lab <model> 0.4 nozzle")
const MODELS: [string, string][] = [["01P", "P1S"], ["01S", "P1P"], ["00M", "X1 Carbon"], ["03W", "X1E"],
  ["030", "A1 mini"], ["039", "A1"], ["22E", "P2S"], ["094", "H2D"]];

export const modelFor = (serial: string | null | undefined) => MODELS.find(([p]) => serial?.startsWith(p))?.[1] ?? null;
export const machineFor = (serial: string | null | undefined) => {
  const m = modelFor(serial);
  return m ? `Bambu Lab ${m} 0.4 nozzle` : null;
};

/** The P1 series sends only what changed: merge into the kept report; lists of {id} (AMS units, trays) by id. */
export function merge(dst: Raw, src: Raw): void {
  for (const [k, v] of Object.entries(src)) {
    const old = dst[k];
    if (v && typeof v === "object" && !Array.isArray(v) && old && typeof old === "object" && !Array.isArray(old)) {
      merge(old, v);
    } else if (Array.isArray(v) && Array.isArray(old) && v.length && v.every(x => x && typeof x === "object" && "id" in x)) {
      for (const item of v) {
        const hit = old.find((x: Raw) => x && String(x.id) === String(item.id));
        if (hit) merge(hit, item);
        else old.push(item);
      }
    } else {
      dst[k] = v;
    }
  }
}

const colour = (c: unknown): string | null => {
  const s = String(c ?? "");
  return /^[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$/.test(s) && s.slice(6, 8) !== "00" ? `#${s.slice(0, 6).toUpperCase()}` : null;
};

/** AMS trays as lanes: ids A1..A4 (B1.. for a 2nd AMS), tool = tray number across all units. */
export function lanes(report: Raw): Lane[] {
  const ams = report.ams ?? {};
  const exist = parseInt(String(ams.tray_exist_bits ?? "0"), 16) || 0;
  const now = String(ams.tray_now ?? "255");
  const out: Lane[] = [];
  for (const unit of ams.ams ?? []) {
    const u = Number(unit?.id);
    if (!Number.isInteger(u)) continue;
    for (const tray of unit.tray ?? []) {
      const t = Number(tray?.id);
      if (!Number.isInteger(t)) continue;
      const tool = u * 4 + t;
      const inserted = Math.floor(exist / 2 ** tool) % 2 === 1;
      const weight = Number(tray.tray_weight) || 0;
      const remain = typeof tray.remain === "number" && tray.remain >= 0 ? tray.remain : null;
      out.push({
        id: `${String.fromCharCode(65 + u)}${t + 1}`, tool, unit: `AMS ${u + 1}`,
        material: inserted ? tray.tray_type || null : null, color: inserted ? colour(tray.tray_color) : null,
        filament: inserted ? tray.tray_sub_brands || null : null,
        weight_g: inserted && weight && remain !== null ? Math.round(weight * remain / 100) : null,
        loaded: inserted, in_toolhead: now === String(tool), status: inserted ? "ready" : "empty",
      });
    }
  }
  return out.sort((a, b) => (a.tool ?? 0) - (b.tool ?? 0));
}

export function statusFrom(report: Raw): PrinterStatus {
  const g = String(report.gcode_state ?? "").toUpperCase();
  let state: string | null = STATES[g] ?? (g ? g.toLowerCase() : null);
  if (g === "FAILED" && CANCELLED.has(Number(report.print_error ?? 0))) state = "cancelled";
  const remaining = typeof report.mc_remaining_time === "number" && report.mc_remaining_time >= 0
    ? report.mc_remaining_time * 60 : null;
  const lights = Object.fromEntries((report.lights_report ?? []).map((x: Raw) => [x.node, x.mode === "on"]));
  const fans: Record<string, number | null> = {};
  for (const [id, key] of Object.entries(FANS)) {
    const v = Number(report[key]);
    fans[id] = key in report && Number.isFinite(v) ? Math.round(v * 100 / 15) : null;
  }
  const file = report.subtask_name || String(report.gcode_file ?? "").split("/").pop() || null;
  return {
    state, kind: kindOf(state), file, progress: Number(report.mc_percent ?? 0),
    layer: report.layer_num ?? null, layers: report.total_layer_num ?? null, time_remaining_s: remaining,
    nozzle: report.nozzle_temper ?? null, nozzle_target: report.nozzle_target_temper ?? null,
    bed: report.bed_temper ?? null, bed_target: report.bed_target_temper ?? null,
    heaters: {
      nozzle: { actual: report.nozzle_temper ?? null, target: report.nozzle_target_temper ?? null },
      bed: { actual: report.bed_temper ?? null, target: report.bed_target_temper ?? null },
    },
    fans, lights: { light: !!lights.chamber_light }, speed: SPEED_LEVELS[Number(report.spd_lvl ?? 2)] ?? null,
    lanes: lanes(report), camera: null,
  };
}

/** Tray per filament of the print: the app's choice, else the tray in the toolhead for one filament, else n → n. */
export function amsMapping(filaments: number, tools: Record<number, number> | undefined, report: Raw): number[] {
  const loaded = Number((report.ams ?? {}).tray_now ?? 255);
  return Array.from({ length: Math.max(1, filaments) }, (_, i) =>
    tools && tools[i] !== undefined ? tools[i] : filaments <= 1 && loaded < 16 ? loaded : i);
}

export const hasAms = (report: Raw) => (parseInt(String((report.ams ?? {}).ams_exist_bits ?? "0"), 16) || 0) > 0;

/** "Ring – v2 (1).gcode" → "Ring_v2_1" (the task name the printer reports while printing) */
export const taskName = (fileName: string) =>
  fileName.replace(/\.gcode$/i, "").replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^[._]+|[._]+$/g, "").slice(0, 60) || "print";

export function startCommand(task: string, remote: string, mapping: number[], ams: boolean, leveling: boolean): Raw {
  return { print: {
    command: "project_file", param: "Metadata/plate_1.gcode", url: `file:///sdcard/${remote}`, file: remote, md5: "",
    subtask_name: task, project_id: "0", profile_id: "0", task_id: "0", subtask_id: "0", bed_type: "auto",
    timelapse: false, bed_leveling: leveling, bed_levelling: leveling, flow_cali: false, vibration_cali: false,
    layer_inspect: false, use_ams: ams, ams_mapping: ams ? mapping : [],
  } };
}
