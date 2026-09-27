// All user-visible text. German first, English complete (NF-11).
import { getLocales } from "expo-localization";

const de = {
  appName: "PrintShare",
  // tabs
  tabPrint: "Drucken", tabJobs: "Aufträge", tabPrinters: "Drucker", tabSettings: "Einstellungen",
  tabDiscover: "Entdecken",
  // discover (MQ-05/06)
  discoverTitle: "Modelle entdecken", searchPlaceholder: "Modelle suchen, z. B. Kabelhalter",
  sortRelevant: "Relevanz", sortPopular: "Beliebt", sortMakes: "Oft gedruckt",
  noResults: "Keine Modelle gefunden", noResultsSub: "Versuche einen anderen Suchbegriff.",
  suggestions: "Vorschläge", suggestionList: "Benchy|Kabelhalter|Handyhalter|Vase|Werkzeughalter|Schlüsselanhänger",
  thingiverseHint: "Thingiverse-Suche: auf dem Server ein Thingiverse-App-Token eintragen (thingiverse.com/developers).",
  searchModels: "Modelle suchen", searchModelsSub: "Printables und Thingiverse direkt in der App",
  by: "von {author}", printThis: "Drucken vorbereiten", openOn: "Auf {source} öffnen",
  authorSettings: "Empfehlung des Autors", layerHeight: "Schichthöhe", weight: "Gewicht", printTimeAuthor: "Druckzeit",
  license: "Lizenz", category: "Kategorie", likes: "Likes", downloads: "Downloads", makes: "Drucke",
  description: "Beschreibung", showMore: "Mehr anzeigen", showLess: "Weniger anzeigen",
  printableFiles: "{n} druckbare Dateien", printableFile: "1 druckbare Datei", noPrintableFiles: "Keine druckbaren Dateien (STL, 3MF, OBJ, STEP)",
  // home
  homeTitle: "Was möchtest du drucken?",
  homeSub: "Teile einen Printables-Link direkt aus Safari oder Chrome mit PrintShare – oder füge ihn hier ein.",
  linkPlaceholder: "Printables- oder Thingiverse-Link",
  paste: "Einfügen", next: "Weiter", or: "oder",
  pickFile: "Datei auswählen", pickFileSub: "STL, 3MF, OBJ oder STEP aus Dateien / iCloud",
  uploading: "Datei wird hochgeladen …",
  needLink: "Bitte einen Link zu einem Modell eingeben (https://…).",
  clipboardEmpty: "In der Zwischenablage ist kein Link.",
  notConnectedTitle: "Noch nicht verbunden",
  notConnectedSub: "Verbinde die App einmalig mit deinem PrintShare-Server.",
  connectNow: "Server verbinden",
  recent: "Zuletzt",
  // prepare
  prepareTitle: "Druck vorbereiten",
  model: "Modell", file: "Datei", filesLoading: "Dateien werden gesucht …",
  filesMany: "{n} Dateien – wähle eine aus", printer: "Drucker", material: "Material", quality: "Qualität",
  plate: "Druckplatte", supports: "Stützstrukturen", brim: "Brim", infill: "Füllung", walls: "Wände",
  more: "Weitere Einstellungen", standard: "Standard", standardV: "Standard ({v})",
  supOff: "Aus", supNormal: "Normal", supTree: "Baum",
  brimAuto: "Auto", brimOff: "Aus", brimOuter: "Außen",
  slice: "Slicen", search: "Suchen", noPrinters: "Auf dem Server ist kein Drucker eingerichtet.",
  chooseFile: "Bitte zuerst eine Datei auswählen.",
  warnPlatePla: "PLA haftet auf der Engineering Plate schlecht – Texturierte PEI ist besser.",
  warnPlatePetg: "PETG kann auf glatter PEI zu stark haften. Texturierte PEI oder Kleber verwenden.",
  warnCoolPlate: "Die Cool Plate ist nur für PLA gedacht.",
  warnCf: "Carbon-/Glasfaser-Filament braucht eine gehärtete Düse.",
  // job
  slicing: "Wird geslict …", slicingSub: "Das dauert meist unter einer Minute.",
  keepRunning: "Im Hintergrund weiter", sending: "Wird an den Drucker gesendet …",
  reviewTitle: "Bereit zum Drucken", printTime: "Druckzeit", filament: "Filament", layers: "Schichten",
  details: "Details", changed: "Geänderte Werte", changedNone: "keine – Profilwerte",
  confirmPlate: "Die Druckplatte ist leer und {material} ist geladen.",
  print: "Drucken", uploadOnly: "Nur hochladen", editSettings: "Einstellungen ändern",
  startedTitle: "Druck gestartet", startedSub: "Du kannst den Fortschritt unter „Drucker“ verfolgen.",
  uploadedTitle: "Auf den Drucker geladen", uploadedSub: "Die Datei liegt auf dem Drucker, der Druck ist noch nicht gestartet.",
  toPrinter: "Zum Drucker", newModel: "Neues Modell", deleteJob: "Auftrag löschen",
  deleteJobQ: "Diesen Auftrag löschen?", del: "Löschen", cancelBtn: "Abbrechen",
  errorTitle: "Das hat nicht geklappt", tryAgain: "Erneut versuchen",
  printerBusy: "{printer} druckt gerade. Starten ist möglich, sobald der Drucker frei ist.",
  printerOffline: "{printer} ist nicht erreichbar.",
  confirmStartQ: "Druck auf {printer} jetzt starten?", start: "Starten",
  // jobs
  jobsEmpty: "Noch keine Aufträge", jobsEmptySub: "Geslicte Modelle erscheinen hier.",
  jobStates: { slicing: "Slicen …", sliced: "Bereit", sending: "Senden …", uploaded: "Hochgeladen",
               started: "Gestartet", error: "Fehler", running: "Läuft …", done: "Fertig" } as Record<string, string>,
  // printers
  printerKinds: { idle: "Bereit", active: "Druckt", paused: "Pausiert", done: "Fertig", stopped: "Abgebrochen",
                  error: "Fehler", unknown: "Unbekannt", offline: "Nicht erreichbar" } as Record<string, string>,
  rawStates: { preheating: "Aufheizen", auto_leveling: "Nivellieren", homing: "Referenzfahrt",
               print_start: "Start", file_checking: "Datei prüfen", resuming: "Fortsetzen …",
               pausing: "Pausieren …", stopping: "Abbrechen …" } as Record<string, string>,
  pause: "Pause", resume: "Fortsetzen", cancelPrint: "Druck abbrechen",
  cancelPrintQ: "Den laufenden Druck auf {printer} wirklich abbrechen? Das lässt sich nicht rückgängig machen.",
  nozzle: "Düse", bed: "Bett", layer: "Schicht", remaining: "Rest", camera: "Kamera",
  // settings
  server: "Server", connected: "Verbunden", offline: "Offline", notConnected: "Nicht verbunden", changeServer: "Server ändern",
  disconnect: "Trennen", disconnectQ: "Verbindung zum Server entfernen?",
  language: "Sprache", langAuto: "Automatisch", about: "Über PrintShare",
  aboutText: "Open Source (MIT). Slicen mit OrcaSlicer auf deinem eigenen Server – keine Cloud.",
  sourceCode: "Quellcode auf GitHub", version: "Version",
  // connect
  connectTitle: "Server verbinden",
  connectSub: "PrintShare läuft auf deinem eigenen Server (z. B. Unraid). Scanne den Kopplungs-Code oder gib die Adresse ein.",
  scanQr: "QR-Code scannen",
  scanHelp: "Den Code findest du im Protokoll des Containers bzw. Home-Assistant-Add-ons – oder mit diesem Befehl:",
  manual: "Manuell eingeben", serverUrl: "Server-Adresse", token: "Zugangs-Token",
  connect: "Verbinden", connecting: "Verbinde …",
  scanTitle: "Kopplungs-Code scannen", cameraNeeded: "Zum Scannen braucht PrintShare einmalig Zugriff auf die Kamera.",
  allowCamera: "Kamera erlauben", invalidQr: "Das ist kein PrintShare-Code.",
  // errors (SL-04)
  errOffline: "Der Server ist nicht erreichbar. Bist du im selben Netz oder mit Tailscale verbunden?",
  errTimeout: "Der Server antwortet nicht.",
  errToken: "Das Zugangs-Token ist ungültig.",
  errBusy: "Der Drucker ist noch beschäftigt. Warte, bis der aktuelle Druck fertig ist.",
  errPrinterOffline: "Der Drucker ist nicht erreichbar. Ist er eingeschaltet und im Netz?",
  errLink: "Mit diesem Link kann PrintShare nichts anfangen. Unterstützt: Printables, Thingiverse, direkte Datei-Links.",
  errNotFound: "Das Modell wurde nicht gefunden oder ist nicht öffentlich.",
  errNoFiles: "Dieses Modell enthält keine druckbaren Dateien (STL, 3MF, OBJ, STEP).",
  errFileType: "Dieser Dateityp wird nicht unterstützt. Möglich sind STL, 3MF, OBJ und STEP.",
  errTooLarge: "Die Datei ist zu groß.",
  errUploadGone: "Die hochgeladene Datei ist nicht mehr auf dem Server. Bitte erneut auswählen.",
  errSlice: "Das Slicen ist fehlgeschlagen. Oft ist das Modell zu groß für den Bauraum oder beschädigt.",
  errProfile: "Ein Druckprofil fehlt auf dem Server.",
  errThingiverse: "Für Thingiverse muss auf dem Server ein Thingiverse-Token eingetragen sein.",
  errDownload: "Der Download des Modells ist fehlgeschlagen. Bitte später erneut versuchen.",
  errUnknown: "Unbekannter Fehler.",
  showDetails: "Technische Details",
  log: [[/^Looking up model files/, "Modelldateien werden gesucht"], [/^Downloading (.*)/, "Download: $1"],
        [/^Waiting for another slice job/, "Wartet auf einen anderen Auftrag"],
        [/^Slicing for (.*)/, "Slicen für $1"], [/^Sliced: (.*)/, "Geslict: $1"],
        [/^Sending to printer and starting/, "Wird gesendet und gestartet"],
        [/^Sending to printer/, "Wird gesendet"], [/^Done/, "Fertig"]] as [RegExp, string][],
  plates: { "Textured PEI Plate": "Texturierte PEI", "High Temp Plate": "Glatte PEI",
            "Cool Plate": "Cool Plate", "Engineering Plate": "Engineering Plate",
            "Supertack Plate": "Supertack Plate" } as Record<string, string>,
  ago: "vor {v}",
};

type Strings = typeof de;

const en: Strings = {
  appName: "PrintShare",
  tabPrint: "Print", tabJobs: "Jobs", tabPrinters: "Printers", tabSettings: "Settings",
  tabDiscover: "Discover",
  discoverTitle: "Discover models", searchPlaceholder: "Search models, e.g. cable clip",
  sortRelevant: "Relevance", sortPopular: "Popular", sortMakes: "Most made",
  noResults: "No models found", noResultsSub: "Try a different search term.",
  suggestions: "Suggestions", suggestionList: "Benchy|Cable clip|Phone stand|Vase|Tool holder|Keychain",
  thingiverseHint: "Thingiverse search: add a Thingiverse app token on the server (thingiverse.com/developers).",
  searchModels: "Search models", searchModelsSub: "Printables and Thingiverse right in the app",
  by: "by {author}", printThis: "Prepare print", openOn: "Open on {source}",
  authorSettings: "Author’s recommendation", layerHeight: "Layer height", weight: "Weight", printTimeAuthor: "Print time",
  license: "License", category: "Category", likes: "Likes", downloads: "Downloads", makes: "Makes",
  description: "Description", showMore: "Show more", showLess: "Show less",
  printableFiles: "{n} printable files", printableFile: "1 printable file", noPrintableFiles: "No printable files (STL, 3MF, OBJ, STEP)",
  homeTitle: "What do you want to print?",
  homeSub: "Share a Printables link straight from Safari or Chrome with PrintShare – or paste it here.",
  linkPlaceholder: "Printables or Thingiverse link",
  paste: "Paste", next: "Next", or: "or",
  pickFile: "Choose a file", pickFileSub: "STL, 3MF, OBJ or STEP from Files / iCloud",
  uploading: "Uploading file …",
  needLink: "Please enter a link to a model (https://…).",
  clipboardEmpty: "There is no link on the clipboard.",
  notConnectedTitle: "Not connected yet",
  notConnectedSub: "Connect the app to your PrintShare server once.",
  connectNow: "Connect server",
  recent: "Recent",
  prepareTitle: "Prepare print",
  model: "Model", file: "File", filesLoading: "Looking up files …",
  filesMany: "{n} files – pick one", printer: "Printer", material: "Material", quality: "Quality",
  plate: "Build plate", supports: "Supports", brim: "Brim", infill: "Infill", walls: "Walls",
  more: "More settings", standard: "Default", standardV: "Default ({v})",
  supOff: "Off", supNormal: "Normal", supTree: "Tree",
  brimAuto: "Auto", brimOff: "Off", brimOuter: "Outer",
  slice: "Slice", search: "Search", noPrinters: "No printer is set up on the server.",
  chooseFile: "Please choose a file first.",
  warnPlatePla: "PLA sticks poorly to the Engineering Plate – Textured PEI works better.",
  warnPlatePetg: "PETG can bond too strongly to smooth PEI. Use Textured PEI or glue.",
  warnCoolPlate: "The Cool Plate is meant for PLA only.",
  warnCf: "Carbon/glass-fibre filament needs a hardened nozzle.",
  slicing: "Slicing …", slicingSub: "This usually takes less than a minute.",
  keepRunning: "Continue in background", sending: "Sending to the printer …",
  reviewTitle: "Ready to print", printTime: "Print time", filament: "Filament", layers: "Layers",
  details: "Details", changed: "Changed values", changedNone: "none – profile values",
  confirmPlate: "The build plate is empty and {material} is loaded.",
  print: "Print", uploadOnly: "Upload only", editSettings: "Change settings",
  startedTitle: "Print started", startedSub: "Follow the progress under “Printers”.",
  uploadedTitle: "Uploaded to the printer", uploadedSub: "The file is on the printer; the print has not been started.",
  toPrinter: "Go to printer", newModel: "New model", deleteJob: "Delete job",
  deleteJobQ: "Delete this job?", del: "Delete", cancelBtn: "Cancel",
  errorTitle: "That didn’t work", tryAgain: "Try again",
  printerBusy: "{printer} is printing. You can start once it is free.",
  printerOffline: "{printer} is not reachable.",
  confirmStartQ: "Start the print on {printer} now?", start: "Start",
  jobsEmpty: "No jobs yet", jobsEmptySub: "Sliced models show up here.",
  jobStates: { slicing: "Slicing …", sliced: "Ready", sending: "Sending …", uploaded: "Uploaded",
               started: "Started", error: "Error", running: "Running …", done: "Done" },
  printerKinds: { idle: "Ready", active: "Printing", paused: "Paused", done: "Finished", stopped: "Cancelled",
                  error: "Error", unknown: "Unknown", offline: "Not reachable" },
  rawStates: { preheating: "Heating", auto_leveling: "Leveling", homing: "Homing", print_start: "Starting",
               file_checking: "Checking file", resuming: "Resuming …", pausing: "Pausing …", stopping: "Cancelling …" },
  pause: "Pause", resume: "Resume", cancelPrint: "Cancel print",
  cancelPrintQ: "Really cancel the running print on {printer}? This cannot be undone.",
  nozzle: "Nozzle", bed: "Bed", layer: "Layer", remaining: "Left", camera: "Camera",
  server: "Server", connected: "Connected", offline: "Offline", notConnected: "Not connected", changeServer: "Change server",
  disconnect: "Disconnect", disconnectQ: "Remove the connection to the server?",
  language: "Language", langAuto: "Automatic", about: "About PrintShare",
  aboutText: "Open source (MIT). Slicing with OrcaSlicer on your own server – no cloud.",
  sourceCode: "Source code on GitHub", version: "Version",
  connectTitle: "Connect server",
  connectSub: "PrintShare runs on your own server (e.g. Unraid). Scan the pairing code or enter the address.",
  scanQr: "Scan QR code",
  scanHelp: "The code is shown in the log of the container / Home Assistant add-on – or with this command:",
  manual: "Enter manually", serverUrl: "Server address", token: "Access token",
  connect: "Connect", connecting: "Connecting …",
  scanTitle: "Scan pairing code", cameraNeeded: "PrintShare needs camera access once to scan the code.",
  allowCamera: "Allow camera", invalidQr: "This is not a PrintShare code.",
  errOffline: "The server is not reachable. Are you on the same network or connected to Tailscale?",
  errTimeout: "The server does not respond.",
  errToken: "The access token is not valid.",
  errBusy: "The printer is still busy. Wait until the current print has finished.",
  errPrinterOffline: "The printer is not reachable. Is it switched on and on the network?",
  errLink: "PrintShare can’t use this link. Supported: Printables, Thingiverse, direct file links.",
  errNotFound: "The model was not found or is not public.",
  errNoFiles: "This model has no printable files (STL, 3MF, OBJ, STEP).",
  errFileType: "This file type is not supported. Use STL, 3MF, OBJ or STEP.",
  errTooLarge: "The file is too large.",
  errUploadGone: "The uploaded file is no longer on the server. Please choose it again.",
  errSlice: "Slicing failed. Often the model is larger than the build volume or broken.",
  errProfile: "A print profile is missing on the server.",
  errThingiverse: "Thingiverse needs a Thingiverse token in the server configuration.",
  errDownload: "Downloading the model failed. Please try again later.",
  errUnknown: "Unknown error.",
  showDetails: "Technical details",
  log: [],
  plates: { "Textured PEI Plate": "Textured PEI", "High Temp Plate": "Smooth PEI",
            "Cool Plate": "Cool Plate", "Engineering Plate": "Engineering Plate",
            "Supertack Plate": "Supertack Plate" },
  ago: "{v} ago",
};

export type Lang = "de" | "en";
export type LangPref = Lang | "auto";
const TABLES: Record<Lang, Strings> = { de, en };

export function systemLang(): Lang {
  try {
    return getLocales()[0]?.languageCode === "de" ? "de" : "en";
  } catch {
    return "de";
  }
}

export function resolveLang(pref: LangPref): Lang {
  return pref === "auto" ? systemLang() : pref;
}

type StringKey = { [K in keyof Strings]: Strings[K] extends string ? K : never }[keyof Strings];

export function makeT(lang: Lang) {
  const table = TABLES[lang];
  const t = (key: StringKey, vars: Record<string, string | number> = {}) =>
    (table[key] as string).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
  return Object.assign(t, { lang, table });
}
export type T = ReturnType<typeof makeT>;

export function translateLog(t: T, line: string): string {
  for (const [re, rep] of t.table.log) if (re.test(line)) return line.replace(re, rep);
  return line;
}
