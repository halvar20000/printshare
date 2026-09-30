"use strict";
// PrintShare web app: link -> settings -> slice -> review -> confirm -> print.
// Plain JS, no build step. All user-visible text lives in I18N (German first, NF-11).

const I18N = {
  de: {
    title: "PrintShare", link: "Modell-Link", paste: "Einfügen", file: "Datei", printer: "Drucker",
    material: "Material", quality: "Qualität", plate: "Druckplatte", supports: "Stützstrukturen",
    brim: "Brim", infill: "Füllung", walls: "Wände", slice: "Slicen", slicing: "Wird geslict …",
    back_to_form: "Zurück (läuft weiter)", print_time: "Druckzeit", layers: "Schichten",
    print: "Drucken", upload_only: "Nur hochladen", to_printer: "Zum Drucker",
    edit: "Einstellungen ändern", new_job: "Neues Modell", no_jobs: "Noch keine Aufträge.",
    token: "API-Token", save: "Speichern", language: "Sprache", lang_auto: "Automatisch",
    install_title: "Als App installieren", install: "Installieren",
    slots_title: "Slots", slot: "Slot", color_n: "Farbe {n}", slot_empty: "leer",
    slot_empty_warn: "{what}: {slot} ist leer – Filament laden oder einen anderen Slot wählen.",
    slot_material_warn: "{what}: Profil ist {want}, in {slot} ist {have}.",
    profiles_title: "Druckerprofil",
    profiles_hint: "Eigenes Druckerprofil aus OrcaSlicer, z. B. für COSMOS mit AFC: in OrcaSlicer den Drucker wählen, dann Datei → Exportieren → Voreinstellungs-Paket (.zip) oder die JSON-Datei des Profils. Der Server prüft das Profil vor der Verwendung.",
    profile_standard: "Standard: {name}", profile_cosmos: " (mit eingebautem COSMOS-Startcode)",
    profile_config: "Aus config.yaml: {name}", profile_for: "Hochladen für",
    profile_upload: "Druckerprofil hochladen", profile_uploading: "Wird hochgeladen …",
    profile_uploaded: "„{name}“ wird ab jetzt für {printer} verwendet.",
    profile_stored: "Hochgeladen: {names}", profile_saved: "{printer} verwendet jetzt: {name}",
    profile_delete: "Löschen", profile_delete_q: "Profil „{name}“ löschen?",
    profile_based_on: "basiert auf {name}", profile_own_start: "eigener Startcode", profile_in_use: "verwendet von {printers}",
    profile_kinds: { machine: "Drucker", process: "Qualität", filament: "Material", unknown: "unbekannt" },
    pair_title: "App verbinden",
    pair_hint: "In der PrintShare-App unter Einstellungen → Server verbinden → QR-Code scannen. Der Code enthält das Zugangs-Token – nicht öffentlich zeigen.",
    pair_url: "Adresse zu Hause", pair_remote: "Adresse unterwegs (optional, z. B. Tailscale)",
    pair_show: "QR-Code anzeigen", pair_hide: "QR-Code verbergen",
    pair_manual: "Oder von Hand eingeben – Server: {url}{remote} · Token: {token}", pair_manual_remote: " · unterwegs: {remote}",
    pair_localhost: "Diese Adresse zeigt auf den Server selbst – das Handy erreicht sie nicht. Bitte die IP-Adresse des Servers eintragen (z. B. http://192.168.1.10:8484).",
    pair_ingress: "Über Home Assistant geöffnet: diese Adresse erreicht die App nicht. Bitte die IP-Adresse des Home-Assistant-Servers mit Port 8484 eintragen.",
    install_ios: "iPhone (Safari): Teilen → „Zum Home-Bildschirm“.",
    install_android: "Android (Chrome): Menü ⋮ → „App installieren“.",
    share_title: "Links teilen",
    share_android: "Android: Nach der Installation steht PrintShare im Teilen-Menü (nur über HTTPS, z. B. Tailscale).",
    share_ios: "iPhone: Kurzbefehl anlegen – „Im Share-Sheet anzeigen“ (URLs), Aktion „URL öffnen“: {origin}/?link=[Kurzbefehleingabe].",
    tab_print: "Drucken", tab_jobs: "Aufträge", tab_printer: "Drucker", tab_settings: "Einstellungen",
    files_loading: "Dateien werden gesucht …", files_one: "Datei: {name}",
    files_many: "{n} Dateien – bitte eine auswählen.", choose_file: "Datei wählen …",
    need_link: "Bitte einen Printables- oder Thingiverse-Link eingeben.",
    need_file: "Bitte eine Datei auswählen.",
    token_missing: "Bitte das API-Token eingeben (steht in config.yaml auf dem Server).",
    token_invalid: "Das API-Token ist ungültig.", offline: "Offline",
    standard: "Standard ({v})", sup_off: "Aus", sup_normal: "Normal", sup_tree: "Baum",
    brim_auto: "Auto", brim_off: "Aus", brim_outer: "Außen",
    plate_names: { "Textured PEI Plate": "Texturierte PEI", "High Temp Plate": "Glatte PEI (High Temp)",
                   "Cool Plate": "Cool Plate", "Engineering Plate": "Engineering Plate",
                   "Supertack Plate": "Supertack Plate" },
    job_states: { slicing: "Slicen …", sliced: "Bereit", sending: "Senden …", uploaded: "Hochgeladen",
                  started: "Gestartet", error: "Fehler", running: "Läuft …", done: "Fertig" },
    printer_states: { idle: "Bereit", active: "Druckt", paused: "Pausiert", done: "Fertig",
                      stopped: "Abgebrochen", error: "Fehler", offline: "Nicht erreichbar", unknown: "Unbekannt" },
    raw_states: { preheating: "Aufheizen", auto_leveling: "Nivellieren", homing: "Referenzfahrt",
                  print_start: "Start", file_checking: "Datei prüfen", resuming: "Fortsetzen …",
                  pausing: "Pausieren …", stopping: "Abbrechen …" },
    plate_empty: "Die Druckplatte ist leer und {material} ist geladen.",
    started_msg: "Druck gestartet.", uploaded_msg: "Auf den Drucker geladen – noch nicht gestartet.",
    sending: "Wird gesendet …",
    cancel_confirm: "Den laufenden Druck wirklich abbrechen?",
    pause: "Pause", resume: "Fortsetzen", cancel: "Abbrechen", camera: "Kamera öffnen",
    nozzle: "Düse", bed: "Bett", progress: "Fortschritt", layer: "Schicht", file_label: "Datei",
    changed: "Geänderte Werte", changed_none: "keine – Profilwerte", profile_values: "Profil",
    infill_v: "Füllung {v}", walls_v: "{v} Wände", supports_v: "Stützen: {v}", brim_v: "Brim: {v}",
    log: [[/^Looking up model files/, "Modelldateien werden gesucht"], [/^Downloading (.*)/, "Download: $1"],
          [/^Waiting for another slice job/, "Wartet auf einen anderen Slice-Auftrag"],
          [/^Slicing for (.*)/, "Slicen für $1"], [/^Sliced: (.*)/, "Geslict: $1"],
          [/^Sending to printer and starting/, "Wird gesendet und gestartet"],
          [/^Sending to printer/, "Wird gesendet"], [/^Done/, "Fertig"]],
  },
  en: {
    title: "PrintShare", link: "Model link", paste: "Paste", file: "File", printer: "Printer",
    material: "Material", quality: "Quality", plate: "Build plate", supports: "Supports",
    brim: "Brim", infill: "Infill", walls: "Walls", slice: "Slice", slicing: "Slicing …",
    back_to_form: "Back (keeps running)", print_time: "Print time", layers: "Layers",
    print: "Print", upload_only: "Upload only", to_printer: "Go to printer",
    edit: "Change settings", new_job: "New model", no_jobs: "No jobs yet.",
    token: "API token", save: "Save", language: "Language", lang_auto: "Automatic",
    install_title: "Install as app", install: "Install",
    slots_title: "Slots", slot: "Slot", color_n: "Colour {n}", slot_empty: "empty",
    slot_empty_warn: "{what}: {slot} is empty – load filament or choose another slot.",
    slot_material_warn: "{what}: the profile is {want}, {slot} holds {have}.",
    profiles_title: "Printer profile",
    profiles_hint: "Your own printer profile from OrcaSlicer, e.g. for COSMOS with AFC: select the printer in OrcaSlicer, then File → Export → preset bundle (.zip) or the profile's JSON file. The server checks the profile before using it.",
    profile_standard: "Standard: {name}", profile_cosmos: " (with built-in COSMOS start code)",
    profile_config: "From config.yaml: {name}", profile_for: "Upload for",
    profile_upload: "Upload printer profile", profile_uploading: "Uploading …",
    profile_uploaded: "“{name}” is now used for {printer}.",
    profile_stored: "Uploaded: {names}", profile_saved: "{printer} now uses: {name}",
    profile_delete: "Delete", profile_delete_q: "Delete profile “{name}”?",
    profile_based_on: "based on {name}", profile_own_start: "own start code", profile_in_use: "used by {printers}",
    profile_kinds: { machine: "Printer", process: "Quality", filament: "Material", unknown: "unknown" },
    pair_title: "Connect the app",
    pair_hint: "In the PrintShare app: Settings → Connect server → Scan QR code. The code contains the access token – don't show it publicly.",
    pair_url: "Home address", pair_remote: "Away address (optional, e.g. Tailscale)",
    pair_show: "Show QR code", pair_hide: "Hide QR code",
    pair_manual: "Or enter by hand – server: {url}{remote} · token: {token}", pair_manual_remote: " · away: {remote}",
    pair_localhost: "This address points to the server itself – the phone can't reach it. Please enter the server's IP address (e.g. http://192.168.1.10:8484).",
    pair_ingress: "Opened through Home Assistant: the app can't reach this address. Please enter the Home Assistant server's IP address with port 8484.",
    install_ios: "iPhone (Safari): Share → “Add to Home Screen”.",
    install_android: "Android (Chrome): menu ⋮ → “Install app”.",
    share_title: "Sharing links",
    share_android: "Android: once installed, PrintShare shows up in the share menu (HTTPS only, e.g. Tailscale).",
    share_ios: "iPhone: create a Shortcut – “Show in Share Sheet” (URLs), action “Open URL”: {origin}/?link=[Shortcut Input].",
    tab_print: "Print", tab_jobs: "Jobs", tab_printer: "Printer", tab_settings: "Settings",
    files_loading: "Looking up files …", files_one: "File: {name}",
    files_many: "{n} files – please pick one.", choose_file: "Choose a file …",
    need_link: "Please enter a Printables or Thingiverse link.",
    need_file: "Please choose a file.",
    token_missing: "Please enter the API token (see config.yaml on the server).",
    token_invalid: "The API token is not valid.", offline: "Offline",
    standard: "Default ({v})", sup_off: "Off", sup_normal: "Normal", sup_tree: "Tree",
    brim_auto: "Auto", brim_off: "Off", brim_outer: "Outer",
    plate_names: { "Textured PEI Plate": "Textured PEI", "High Temp Plate": "Smooth PEI (High Temp)",
                   "Cool Plate": "Cool Plate", "Engineering Plate": "Engineering Plate",
                   "Supertack Plate": "Supertack Plate" },
    job_states: { slicing: "Slicing …", sliced: "Ready", sending: "Sending …", uploaded: "Uploaded",
                  started: "Started", error: "Error", running: "Running …", done: "Done" },
    printer_states: { idle: "Ready", active: "Printing", paused: "Paused", done: "Finished",
                      stopped: "Cancelled", error: "Error", offline: "Not reachable", unknown: "Unknown" },
    raw_states: { preheating: "Heating", auto_leveling: "Leveling", homing: "Homing",
                  print_start: "Starting", file_checking: "Checking file", resuming: "Resuming …",
                  pausing: "Pausing …", stopping: "Cancelling …" },
    plate_empty: "The build plate is empty and {material} is loaded.",
    started_msg: "Print started.", uploaded_msg: "Uploaded to the printer – not started.",
    sending: "Sending …",
    cancel_confirm: "Really cancel the running print?",
    pause: "Pause", resume: "Resume", cancel: "Cancel", camera: "Open camera",
    nozzle: "Nozzle", bed: "Bed", progress: "Progress", layer: "Layer", file_label: "File",
    changed: "Changed values", changed_none: "none – profile values", profile_values: "Profile",
    infill_v: "Infill {v}", walls_v: "{v} walls", supports_v: "Supports: {v}", brim_v: "Brim: {v}",
    log: [],
  },
};

// ---------- small helpers ----------
const $ = id => document.getElementById(id);
const store = {
  get(k, d = "") { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  json(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch { return null; } },
};
let lang = "de";
function t(key, vars = {}) {
  let s = I18N[lang][key] ?? I18N.de[key] ?? key;
  if (typeof s !== "string") return s;
  vars = { origin: location.origin, ...vars };
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
}
function applyI18n() {
  const pref = store.get("ps_lang", "auto");
  lang = pref !== "auto" ? pref : (navigator.language || "de").toLowerCase().startsWith("de") ? "de" : "en";
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-t]").forEach(el => { el.textContent = t(el.dataset.t); });
}
const short = name => (name || "").replace(/\s*@.*$/, "");          // "Elegoo PLA @ECC" -> "Elegoo PLA"
const plateName = p => t("plate_names")[p] || p;
const sleep = ms => new Promise(r => setTimeout(r, ms));
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k.startsWith("on")) e[k] = v; else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k);
  return e;
}
function translateLog(line) {
  for (const [re, rep] of t("log")) if (re.test(line)) return line.replace(re, rep);
  return line;
}
function extractLink(text) {
  const m = (text || "").match(/https?:\/\/[^\s"'<>]+/);
  return m ? m[0] : "";
}

// ---------- API ----------
class ApiError extends Error {}
async function api(path, opts = {}) {
  let r;
  try {
    r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json",
      Authorization: "Bearer " + store.get("ps_token"), ...(opts.headers || {}) } });
  } catch {
    $("net").textContent = t("offline"); $("net").hidden = false;
    throw new ApiError(t("offline"));
  }
  $("net").hidden = true;
  const body = await r.json().catch(() => ({}));
  if (r.status === 401) { showSettings(t("token_invalid")); throw new ApiError(t("token_invalid")); }
  if (!r.ok) throw new ApiError(typeof body.detail === "string" ? body.detail : "HTTP " + r.status);
  return body;
}
const post = (path, data) => api(path, { method: "POST", body: JSON.stringify(data) });

// ---------- navigation ----------
const VIEWS = ["print", "jobs", "printer", "settings"];
let current = "print";
function show(view) {
  if (!VIEWS.includes(view)) view = "print";
  current = view;
  for (const v of VIEWS) $("view-" + v).hidden = v !== view;
  document.querySelectorAll(".tabs a").forEach(a => {
    if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  if (view === "jobs") loadJobs();
  if (view === "printer") pollPrinters();
  if (view === "settings") { loadPairing(); loadProfiles(); }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", () => show(location.hash.slice(1)));
function showSettings(msg) {
  $("settings-msg").textContent = msg || "";
  $("settings-msg").hidden = !msg;
  if (location.hash !== "#settings") location.hash = "#settings"; else show("settings");
}
function stage(name) {
  for (const s of ["form", "progress", "review"]) $(s).hidden = s !== name;
  window.scrollTo(0, 0);
}

// ---------- print form ----------
const S = { printers: [], options: null, defaults: {}, files: [], filesFor: "", jobId: null, pollToken: 0 };

function fillSelect(sel, items, value) {
  sel.replaceChildren(...items.map(([v, label]) => new Option(label, v)));
  if (value != null && items.some(([v]) => String(v) === String(value))) sel.value = value;
}
function fillGrouped(sel, names, value) {
  const groups = new Map();
  for (const n of names) {
    const g = n.split(" ")[0];
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(n);
  }
  sel.replaceChildren(...[...groups].map(([g, ns]) =>
    el("optgroup", { label: g }, ...ns.map(n => new Option(short(n), n)))));
  if (names.includes(value)) sel.value = value;
}
function buildSeg(box, values, prefix, value) {
  box.replaceChildren(...values.map(v => el("button", {
    type: "button", role: "radio", "aria-checked": String(v === value), "data-value": v,
    onclick: () => box.querySelectorAll("button").forEach(b =>
      b.setAttribute("aria-checked", String(b.dataset.value === v))),
  }, t(prefix + v))));
}
const segValue = box => box.querySelector('[aria-checked="true"]')?.dataset.value ?? null;

function setDetailControls(d, keep = {}) {
  buildSeg($("supports"), S.options.supports, "sup_", keep.supports ?? d.supports);
  buildSeg($("brim"), S.options.brims, "brim_", keep.brim ?? d.brim);
  const inf = [0, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100].filter(v => v !== d.infill);
  fillSelect($("infill"), [["", t("standard", { v: (d.infill ?? "?") + "\u00a0%" })], ...inf.map(v => [v, v + "\u00a0%"])],
             keep.infill ?? "");
  const walls = [1, 2, 3, 4, 5, 6].filter(v => v !== d.walls);
  fillSelect($("walls"), [["", t("standard", { v: d.walls ?? "?" })], ...walls.map(v => [v, String(v)])],
             keep.walls ?? "");
}

async function loadPrinters() {
  S.printers = await api("/api/printers");
  fillSelect($("printer"), S.printers.map(p => [p.id, p.name]), store.get("ps_printer"));
  await loadOptions();
}

async function loadOptions(keep = null) {
  const id = $("printer").value;
  S.options = await api(`/api/printers/${encodeURIComponent(id)}/options`);
  const prefs = keep || store.json("ps_prefs_" + id) || {};
  fillGrouped($("filament"), S.options.materials, prefs.filament ?? S.options.defaults.filament);
  fillSelect($("process"), S.options.processes.map(p => [p, short(p)]), prefs.process ?? S.options.defaults.process);
  fillSelect($("bed_type"), S.options.plates.map(p => [p, plateName(p)]), prefs.bed_type ?? S.options.defaults.bed_type);
  await loadDefaults(keep || {});
}

async function loadDefaults(keep = {}) {
  const id = $("printer").value, process = $("process").value;
  if (process !== S.options.defaults.process) {
    S.options.defaults = (await api(`/api/printers/${encodeURIComponent(id)}/options?process=` +
                                    encodeURIComponent(process))).defaults;
  }
  S.defaults = S.options.defaults;
  setDetailControls(S.defaults, keep);
}

function formOptions() {
  const d = S.defaults, o = {};
  const sup = segValue($("supports")), brim = segValue($("brim"));
  if ($("filament").value !== S.options.defaults.filament) o.filament = $("filament").value;
  o.process = $("process").value;
  o.bed_type = $("bed_type").value;
  if (sup !== d.supports) o.supports = sup;
  if (brim !== d.brim) o.brim = brim;
  if ($("infill").value !== "") o.infill = Number($("infill").value);
  if ($("walls").value !== "") o.walls = Number($("walls").value);
  return o;
}

let filesTimer = null;
function scheduleFiles() { clearTimeout(filesTimer); filesTimer = setTimeout(loadFiles, 500); }
async function loadFiles() {
  const link = $("link").value.trim();
  if (!/^https?:\/\//.test(link) || link === S.filesFor) return;
  S.filesFor = link; S.files = [];
  $("file-row").hidden = true;
  $("files-info").className = "hint"; $("files-info").textContent = t("files_loading");
  try {
    const files = await api("/api/files?link=" + encodeURIComponent(link));
    if (link !== S.filesFor) return;
    S.files = files;
    if (files.length === 1) {
      $("files-info").textContent = t("files_one", { name: files[0].name });
    } else {
      $("files-info").textContent = t("files_many", { n: files.length });
      const size = b => b ? ` (${(b / 1048576).toFixed(1)} MB)` : "";
      const threeMf = files.filter(f => /\.3mf$/i.test(f.name));
      fillSelect($("file"), [["", t("choose_file")], ...files.map(f => [f.index, f.name + size(f.size)])],
                 threeMf.length === 1 ? threeMf[0].index : "");
      $("file-row").hidden = false;
    }
  } catch (e) {
    if (link !== S.filesFor) return;
    S.filesFor = "";
    $("files-info").className = "error"; $("files-info").textContent = e.message;
  }
}

function formError(msg) {
  $("form-error").textContent = msg || ""; $("form-error").hidden = !msg;
  if (msg) window.scrollTo(0, 0);
}

async function submitForm(ev) {
  ev.preventDefault();
  formError("");
  const link = $("link").value.trim();
  if (!/^https?:\/\//.test(link)) return formError(t("need_link"));
  if (S.files.length > 1 && !$("file").value) return formError(t("need_file"));
  const printer = $("printer").value;
  store.set("ps_printer", printer);
  store.set("ps_prefs_" + printer, JSON.stringify({ filament: $("filament").value,
    process: $("process").value, bed_type: $("bed_type").value }));
  $("slice").disabled = true;
  try {
    const { job } = await post("/api/jobs", { link, printer, file: $("file").value || null, options: formOptions() });
    followJob(job);
  } catch (e) { formError(e.message); }
  $("slice").disabled = false;
}

// ---------- job progress + review ----------
async function followJob(id) {
  S.jobId = id;
  const token = ++S.pollToken, started = Date.now();
  stage("progress");
  $("progress-log").replaceChildren();
  while (token === S.pollToken) {
    let j;
    try { j = await api("/api/jobs/" + id); } catch (e) { await sleep(2000); continue; }
    if (token !== S.pollToken) return;
    $("progress-log").replaceChildren(...j.log.map(l => el("li", {}, translateLog(l))));
    $("progress-time").textContent = Math.round((Date.now() - started) / 1000) + " s";
    if (j.state === "error") { stage("form"); formError(j.error); return; }
    if (j.state !== "slicing" && j.state !== "running") { showReview(j); return; }
    await sleep(1000);
  }
}

function overrideLabels(o) {
  const out = [];
  if (o.enable_support === "0") out.push(t("supports_v", { v: t("sup_off") }));
  else if (o.enable_support === "1") out.push(t("supports_v", { v: t(o.support_type?.startsWith("tree") ? "sup_tree" : "sup_normal") }));
  const brim = { auto_brim: "auto", no_brim: "off", outer_only: "outer" }[o.brim_type];
  if (brim) out.push(t("brim_v", { v: t("brim_" + brim) }));
  if (o.sparse_infill_density) out.push(t("infill_v", { v: o.sparse_infill_density.replace("%", "\u00a0%") }));
  if (o.wall_loops) out.push(t("walls_v", { v: o.wall_loops }));
  return out;
}

function showReview(j) {
  S.jobId = j.id;
  const r = j.result || {}, p = r.profiles || {};
  const printer = S.printers.find(x => x.id === r.printer);
  stage("review");
  $("review-file").textContent = r.source_file || j.request?.link || "";
  $("r-time").textContent = r.print_time || "–";
  $("r-grams").textContent = r.filament_g != null ? r.filament_g.toFixed(1) + " g" : "–";
  $("r-meters").textContent = "Filament" + (r.filament_m != null ? ` · ${r.filament_m} m` : "");
  $("r-layers").textContent = r.layers ?? "–";
  const changed = overrideLabels(r.overrides || {});
  const rows = [[t("printer"), printer?.name || r.printer], [t("material"), short(p.filament)],
                [t("quality"), short(p.process)], [t("plate"), plateName(p.bed_type)],
                [t("changed"), changed.length ? changed.join(" · ") : t("changed_none"), changed.length > 0]];
  $("review-details").replaceChildren(...rows.flatMap(([k, v, hi]) =>
    [el("dt", {}, k), el("dd", hi ? { class: "changed" } : {}, v || "–")]));
  $("plate-empty-text").textContent = t("plate_empty", { material: short(p.filament) || "Filament" });
  $("plate-empty").checked = false;
  $("do-print").disabled = true;
  const done = j.state === "started", uploaded = j.state === "uploaded";
  $("confirm-card").hidden = done;
  $("sent-card").hidden = !(done || uploaded);
  $("sent-text").textContent = done ? t("started_msg") : t("uploaded_msg");
  $("edit").hidden = done;
  $("new-job").hidden = !(done || uploaded);
  $("review-error").textContent = j.error || "";
  $("review-error").hidden = !j.error;
  $("do-upload").hidden = uploaded;
  $("do-print").textContent = t("print");
  S.lastJob = j;
  loadSlots(j);
}

// ---------- AFC slots (issue #12), same rules as the app's lib/lanes.ts ----------
const MATERIALS = ["PLA", "PETG", "ABS", "ASA", "TPU", "PA", "PC", "PVA", "HIPS", "PET"];
const materialOf = name => { const w = (name || "").toUpperCase().split(/[^A-Z0-9]+/); return MATERIALS.find(m => w.includes(m)) || null; };
const fitsLane = (preset, lane) => { const want = materialOf(preset), have = (lane?.material || "").toUpperCase();
  return !want || !have || have.startsWith(want); };
function slotList(lanes) {
  const list = (lanes || []).filter(l => l.tool != null);
  const nums = list.map(l => { const m = l.id.match(/(\d+)$/); return m ? Number(m[1]) : null; });
  const numbered = nums.every(n => n != null) && new Set(nums).size === nums.length;
  return list.map((l, i) => ({ ...l, slot: numbered ? `${t("slot")} ${nums[i]}` : l.id, o: numbered ? nums[i] : i }))
    .sort((a, b) => a.o - b.o);
}
function defaultSlotsFor(colours, slots) {
  const rgb = c => (/^#[0-9a-f]{6}$/i.test(c || "") ? [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16)) : null);
  const dist = (a, b) => { const x = rgb(a), y = rgb(b); return x && y ? x.reduce((s, v, i) => s + (v - y[i]) ** 2, 0) : 1e6; };
  const loaded = slots.filter(l => l.loaded), taken = new Set(), out = {};
  for (const c of colours) {
    const fit = loaded.filter(l => fitsLane(c.preset, l)), pool = fit.length ? fit : loaded;
    const free = pool.filter(l => !taken.has(l.tool)), from = free.length ? free : pool;
    const pick = (c.color ? [...from].sort((a, b) => dist(a.color, c.color) - dist(b.color, c.color))[0]
      : from.find(l => l.in_toolhead) || from[0]) || slots[0];
    if (pick) { out[c.index] = pick.tool; taken.add(pick.tool); }
  }
  return out;
}
async function loadSlots(j) {
  S.slots = null;
  $("slots-box").hidden = true;
  const r = j.result || {};
  if (!r.printer || j.state === "started") return;
  let st;
  try { st = await api(`/api/printers/${encodeURIComponent(r.printer)}/status`); } catch { return; }
  const slots = slotList(st.lanes);
  if (!slots.length || S.jobId !== j.id) return;
  const colours = r.filaments && r.filaments.length > 1 ? r.filaments
    : [{ index: 1, color: null, preset: r.profiles?.filament }];
  // keep a choice made for this job (e.g. "upload only" first, then print)
  const kept = S.slotsKept?.job === j.id ? S.slotsKept.chosen : {};
  const chosen = { ...defaultSlotsFor(colours, slots),
    ...Object.fromEntries(Object.entries(kept).filter(([, tool]) => slots.some(l => l.tool === tool))) };
  S.slotsKept = { job: j.id, chosen };
  const label = l => [l.slot, l.loaded ? l.material : t("slot_empty"), l.filament, `T${l.tool}`].filter(Boolean).join(" · ");
  $("slots").replaceChildren(...colours.flatMap(c => {
    const sel = el("select", { id: "slot-" + c.index });
    fillSelect(sel, slots.map(l => [String(l.tool), label(l)]), String(chosen[c.index]));
    sel.onchange = () => { chosen[c.index] = Number(sel.value); checkSlots(); };
    const what = colours.length > 1 ? t("color_n", { n: c.index }) : t("slot");
    return [el("label", { for: sel.id }, what + (c.preset ? ` – ${short(c.preset)}` : "")), sel];
  }));
  S.slots = { colours, slots, chosen };
  $("slots-box").hidden = false;
  checkSlots();
}
function checkSlots() {
  const warn = [];
  let blocking = false;
  if (S.slots) {
    const { colours, slots, chosen } = S.slots;
    for (const c of colours) {
      const lane = slots.find(l => l.tool === chosen[c.index]);
      if (!lane) continue;
      const what = colours.length > 1 ? t("color_n", { n: c.index }) : t("slot");
      if (!lane.loaded) { warn.push(t("slot_empty_warn", { what, slot: lane.slot })); blocking = true; }
      else if (!fitsLane(c.preset, lane)) {
        warn.push(t("slot_material_warn", { what, want: short(c.preset), slot: lane.slot, have: lane.material }));
      }
    }
  }
  S.slotsBlocking = blocking;
  $("slots-warn").textContent = warn.join("\n");
  $("slots-warn").className = blocking ? "error" : "error warn";   // yellow unless the print is blocked
  $("slots-warn").hidden = !warn.length;
  $("do-print").disabled = !$("plate-empty").checked || blocking;
}

async function sendJob(start) {
  const id = S.jobId;
  $("do-print").disabled = $("do-upload").disabled = true;
  $("review-error").hidden = true;
  $("do-print").textContent = t("sending");
  try {
    const body = { start, confirm: start };
    if (S.slots) body.lanes = S.slots.chosen;       // {"<model colour>": <tool of the chosen slot>}
    await post(`/api/jobs/${id}/send`, body);
    for (;;) {
      await sleep(1000);
      const j = await api("/api/jobs/" + id);
      if (j.state !== "sending") { showReview(j); break; }
    }
  } catch (e) {
    $("review-error").textContent = e.message; $("review-error").hidden = false;
    $("do-print").textContent = t("print");
  }
  $("do-upload").disabled = false;
  $("do-print").disabled = !$("plate-empty").checked || !!S.slotsBlocking;
}

async function editJob() {
  const req = S.lastJob?.request;
  stage("form");
  if (!req) return;
  $("link").value = req.link;
  if (req.printer && req.printer !== $("printer").value) $("printer").value = req.printer;
  const o = req.options || {};
  try {
    await loadOptions({ filament: o.filament, process: o.process, bed_type: o.bed_type,
                        supports: o.supports, brim: o.brim, infill: o.infill, walls: o.walls });
  } catch (e) { formError(e.message); }
  await loadFiles();
  if (req.file) $("file").value = req.file;
}

// ---------- jobs list ----------
function ago(ts) {
  const s = Math.round(Date.now() / 1000 - ts);
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  if (s < 60) return rtf.format(-s, "second");
  if (s < 3600) return rtf.format(-Math.round(s / 60), "minute");
  if (s < 86400) return rtf.format(-Math.round(s / 3600), "hour");
  return rtf.format(-Math.round(s / 86400), "day");
}
async function loadJobs() {
  let jobs;
  try { jobs = await api("/api/jobs"); } catch { return; }
  $("jobs-empty").hidden = jobs.length > 0;
  $("jobs").replaceChildren(...jobs.map(j => {
    const name = j.file || (j.link || "").replace(/^https?:\/\/(www\.)?/, "");
    const meta = [S.printers.find(p => p.id === j.printer)?.name, j.print_time,
                  j.filament_g != null ? j.filament_g.toFixed(1) + " g" : null, ago(j.created)];
    const cls = j.state === "error" ? "badge err" : ["started", "done"].includes(j.state) ? "badge ok" : "badge";
    return el("li", { class: "card job", onclick: () => openJob(j.id) },
      el("div", { class: "main" }, el("div", { class: "name" }, name),
         el("div", { class: "meta" }, meta.filter(Boolean).join(" · "))),
      el("span", { class: cls }, t("job_states")[j.state] || j.state));
  }));
}
async function openJob(id) {
  const j = await api("/api/jobs/" + id);
  location.hash = "#print";
  if (j.state === "slicing" || j.state === "running") return followJob(id);
  if (j.state === "error") { S.lastJob = j; await editJob(); return formError(j.error); }
  showReview(j);
}

// ---------- printers ----------
function classify(state) {
  const s = (state || "").toLowerCase();
  if (!s) return "unknown";
  if (["paused", "unloading_paused"].includes(s)) return "paused";
  if (["idle", "standby"].includes(s)) return "idle";
  if (["completed", "complete"].includes(s)) return "done";
  if (["stopped", "cancelled"].includes(s)) return "stopped";
  if (s === "error") return "error";
  return "active";
}
let printerTimer = null;
async function pollPrinters() {
  clearTimeout(printerTimer);
  if (current !== "printer") return;
  if (!S.printers.length) { try { await loadPrinters(); } catch { /* shown elsewhere */ } }
  const cards = await Promise.all(S.printers.map(async p => {
    try { return printerCard(p, await api(`/api/printers/${encodeURIComponent(p.id)}/status`)); }
    catch (e) { return printerCard(p, null, e.message); }
  }));
  if (current !== "printer") return;
  $("printers").replaceChildren(...cards);
  if (!document.hidden) printerTimer = setTimeout(pollPrinters, 5000);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && current === "printer") pollPrinters(); });

function printerCard(p, s, err) {
  const kind = s ? classify(s.state) : "offline";
  let label = t("printer_states")[kind];
  const raw = (s?.state || "").toLowerCase();
  if (kind === "active" && raw !== "printing") label += " · " + (t("raw_states")[raw] || raw);
  const busy = kind === "active" || kind === "paused";
  const temp = (v, tg) => v == null ? "–" : `${Math.round(v)}${tg ? " / " + Math.round(tg) : ""} °C`;
  const btn = (key, action, cls = "ghost") => el("button", { type: "button", class: cls,
    onclick: () => control(p.id, action) }, t(key));
  return el("div", { class: "card printer" },
    el("h2", {}, p.name),
    el("div", { class: "state" }, err ? `${label} – ${err}` : label),
    busy ? el("div", { class: "bar" }, el("span", { style: `width:${Math.min(100, s.progress || 0)}%` })) : null,
    s ? el("dl", { class: "details" },
      ...(busy ? [el("dt", {}, t("file_label")), el("dd", {}, s.file || "–"),
                  el("dt", {}, t("progress")), el("dd", {}, `${s.progress ?? 0}\u00a0%`),
                  el("dt", {}, t("layer")), el("dd", {}, `${s.layer ?? "–"} / ${s.layers ?? "–"}`)] : []),
      el("dt", {}, t("nozzle")), el("dd", {}, temp(s.nozzle, s.nozzle_target)),
      el("dt", {}, t("bed")), el("dd", {}, temp(s.bed, s.bed_target))) : null,
    busy ? el("div", { class: "row" },
      kind === "paused" ? btn("resume", "resume", "primary") : btn("pause", "pause"),
      btn("cancel", "cancel", "danger")) : null,
    s?.camera ? el("a", { href: s.camera, target: "_blank", rel: "noopener", class: "hint",
      style: "display:inline-block;margin-top:12px" }, t("camera") + " ↗") : null);
}
async function control(id, action) {
  if (action === "cancel" && !confirm(t("cancel_confirm"))) return;
  try { await post(`/api/printers/${encodeURIComponent(id)}/control`, { action, confirm: action === "cancel" }); }
  catch (e) { alert(e.message); }
  setTimeout(pollPrinters, 1000);
}

// ---------- settings / install ----------
let installPrompt = null;
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); installPrompt = e; $("install").hidden = false; });
$("install").onclick = async () => { if (installPrompt) { installPrompt.prompt(); installPrompt = null; $("install").hidden = true; } };
$("save-token").onclick = async () => {
  store.set("ps_token", $("token").value.trim());
  $("settings-msg").hidden = true;
  try { await loadPrinters(); location.hash = "#print"; } catch (e) { if (!(e instanceof ApiError)) showSettings(e.message); }
};
$("lang").onchange = () => { store.set("ps_lang", $("lang").value); location.reload(); };

// ---------- own printer profile (issue #2) ----------
const PR = { profiles: [], assigned: {} };
function profilesMsg(text, error = false) {
  $("profiles-msg").textContent = text || "";
  $("profiles-msg").className = error ? "error" : "hint ok";
  $("profiles-msg").hidden = !text;
}
async function loadProfiles() {
  if (!store.get("ps_token")) { $("profiles-card").hidden = true; return; }
  try {
    if (!S.printers.length) S.printers = await api("/api/printers");
    const [profiles, ...assigned] = await Promise.all([api("/api/profiles"),
      ...S.printers.map(p => api(`/api/printers/${encodeURIComponent(p.id)}/profile`))]);
    PR.profiles = profiles;
    PR.assigned = Object.fromEntries(S.printers.map((p, i) => [p.id, assigned[i]]));
  } catch (e) {
    $("profiles-card").hidden = !(e instanceof ApiError) || e.message === t("token_invalid");
    profilesMsg(e.message, true);
    return;
  }
  $("profiles-card").hidden = false;
  renderProfiles();
}
const profileName = p => p.name || p.file;
function renderProfiles() {
  const machines = PR.profiles.filter(p => p.kind === "machine" && !p.error);
  $("profile-printers").replaceChildren(...S.printers.flatMap(pr => {
    const cur = PR.assigned[pr.id] || {};
    const sel = el("select", { id: "profile-" + pr.id });
    const std = t("profile_standard", { name: cur.machine || "–" }) +
                (cur.machine_preset === "cosmos" ? t("profile_cosmos") : "");
    fillSelect(sel, [["", std], ...machines.map(m => [m.file, profileName(m)])], cur.machine_file || "");
    sel.onchange = () => assignProfile(pr, sel.value || null);
    return [el("label", { for: sel.id }, pr.name), sel,
            cur.config_file ? el("p", { class: "hint" }, t("profile_config", { name: cur.config_file })) : null];
  }).filter(Boolean));
  const target = $("profile-target");
  fillSelect(target, S.printers.map(p => [p.id, p.name]), target.value || store.get("ps_printer"));
  $("profile-target-row").hidden = S.printers.length < 2;
  const users = file => S.printers.filter(p => PR.assigned[p.id]?.machine_file === file).map(p => p.name);
  $("profile-list").replaceChildren(...PR.profiles.map(p => {
    const used = users(p.file);
    const meta = [t("profile_kinds")[p.kind] || p.kind, p.inherits ? t("profile_based_on", { name: p.inherits }) : null,
                  p.print_start ? t("profile_own_start") : null,
                  used.length ? t("profile_in_use", { printers: used.join(", ") }) : null, p.error].filter(Boolean);
    return el("li", {},
      el("div", { class: "main" }, el("div", { class: "name" }, profileName(p)),
         el("div", { class: "meta" }, meta.join(" · "))),
      el("button", { type: "button", class: "danger", onclick: () => deleteProfile(p) }, t("profile_delete")));
  }));
}
async function assignProfile(printer, file) {
  profilesMsg("");
  try {
    PR.assigned[printer.id] = await api(`/api/printers/${encodeURIComponent(printer.id)}/profile`,
                                        { method: "PUT", body: JSON.stringify({ machine_file: file }) });
    const m = PR.profiles.find(p => p.file === file);
    profilesMsg(t("profile_saved", { printer: printer.name,
      name: m ? profileName(m) : t("profile_standard", { name: PR.assigned[printer.id].machine }) }));
  } catch (e) { profilesMsg(e.message, true); }
  renderProfiles();
}
async function uploadProfile(file) {
  const printer = S.printers.find(p => p.id === $("profile-target").value) || S.printers[0];
  profilesMsg("");
  $("profile-upload").disabled = true;
  $("profile-upload").textContent = t("profile_uploading");
  try {
    // raw body, like the app (POST /api/profiles?filename=…); never retried
    const stored = await api("/api/profiles?filename=" + encodeURIComponent(file.name),
                             { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } });
    const machine = stored.find(p => p.kind === "machine");
    if (machine && printer) {
      // the usual case: one printer preset -> use it for the chosen printer right away
      PR.assigned[printer.id] = await api(`/api/printers/${encodeURIComponent(printer.id)}/profile`,
                                          { method: "PUT", body: JSON.stringify({ machine_file: machine.file }) });
      profilesMsg(t("profile_uploaded", { name: profileName(machine), printer: printer.name }));
    } else {
      profilesMsg(t("profile_stored", { names: stored.map(profileName).join(", ") }));
    }
    PR.profiles = await api("/api/profiles");
  } catch (e) { profilesMsg(e.message, true); }
  $("profile-upload").disabled = false;
  $("profile-upload").textContent = t("profile_upload");
  renderProfiles();
}
async function deleteProfile(p) {
  if (!confirm(t("profile_delete_q", { name: profileName(p) }))) return;
  profilesMsg("");
  try {
    await api("/api/profiles/" + encodeURIComponent(p.file), { method: "DELETE" });
    PR.profiles = PR.profiles.filter(x => x.file !== p.file);
  } catch (e) { profilesMsg(e.message, true); }
  renderProfiles();
}
$("profile-upload").onclick = () => $("profile-file").click();
$("profile-file").onchange = () => {
  const f = $("profile-file").files[0];
  $("profile-file").value = "";          // the same file can be chosen again
  if (f) uploadProfile(f);
};

// ---------- pairing code for the app (issue #10) ----------
const P = { shown: false, timer: 0, edited: false };
async function loadPairing() {
  if (!store.get("ps_token")) { $("pair-card").hidden = true; return; }
  const q = P.edited ? "?" + new URLSearchParams({ url: $("pair-url").value.trim(), remote: $("pair-remote").value.trim() }) : "";
  let r;
  try { r = await api("/api/pairing" + q); } catch (e) {
    $("pair-warn").textContent = e.message; $("pair-warn").hidden = false;
    $("pair-qr").replaceChildren(); $("pair-manual").textContent = "";   // never leave a stale code
    return;
  }
  $("pair-card").hidden = false;
  if (!P.edited) { $("pair-url").value = r.url; $("pair-remote").value = r.remote_url; }
  const warn = r.warnings.map(w => t("pair_" + w)).join("\n");
  $("pair-warn").textContent = warn; $("pair-warn").hidden = !warn;
  $("pair-qr").innerHTML = r.svg;          // generated by the server (segno), no user HTML
  $("pair-manual").textContent = t("pair_manual", { url: r.url, token: r.token || "–",
    remote: r.remote_url ? t("pair_manual_remote", { remote: r.remote_url }) : "" });
}
function pairingEdited() {
  P.edited = true;
  clearTimeout(P.timer);
  P.timer = setTimeout(loadPairing, 500);
}
$("pair-url").addEventListener("input", pairingEdited);
$("pair-remote").addEventListener("input", pairingEdited);
$("pair-show").onclick = () => {
  P.shown = !P.shown;                      // hidden by default: the code contains the token
  $("pair-code").hidden = !P.shown;
  $("pair-show").textContent = t(P.shown ? "pair_hide" : "pair_show");
};

// ---------- wiring ----------
$("form").onsubmit = submitForm;
$("link").addEventListener("input", scheduleFiles);
$("link").addEventListener("change", loadFiles);
$("printer").onchange = () => loadOptions().catch(e => formError(e.message));
$("process").onchange = () => loadDefaults().catch(e => formError(e.message));
$("progress-back").onclick = () => { S.pollToken++; stage("form"); };
$("plate-empty").onchange = () => { $("do-print").disabled = !$("plate-empty").checked || !!S.slotsBlocking; };
$("do-print").onclick = () => sendJob(true);
$("do-upload").onclick = () => sendJob(false);
$("edit").onclick = editJob;
$("to-printer").onclick = () => { location.hash = "#printer"; };
$("new-job").onclick = () => { $("link").value = ""; S.filesFor = ""; S.files = [];
  $("files-info").textContent = ""; $("file-row").hidden = true; stage("form"); };
if (navigator.clipboard?.readText) {
  $("paste").hidden = false;
  $("paste").onclick = async () => {
    try { const l = extractLink(await navigator.clipboard.readText()); if (l) { $("link").value = l; loadFiles(); } }
    catch { /* permission denied */ }
  };
}

async function init() {
  applyI18n();
  $("lang").value = store.get("ps_lang", "auto");
  const qs = new URLSearchParams(location.search);
  if (qs.get("token")) store.set("ps_token", qs.get("token"));
  const shared = qs.get("link") || extractLink([qs.get("url"), qs.get("text"), qs.get("title")].join(" "));
  if (shared) $("link").value = shared;
  if (location.search) history.replaceState(null, "", "/" + location.hash);  // keep the token out of history
  $("token").value = store.get("ps_token");
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});

  show(location.hash.slice(1) || "print");
  if (!store.get("ps_token")) return showSettings(t("token_missing"));
  try { await loadPrinters(); } catch (e) { if (!(e instanceof ApiError) || e.message !== t("token_invalid")) formError(e.message); }
  if (shared) loadFiles();
}
init();
