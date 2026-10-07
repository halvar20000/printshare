"use strict";
// PocketPrint3D web app: link -> settings -> slice -> review -> confirm -> print.
// Plain JS, no build step. All user-visible text lives in I18N (German first, NF-11).

const I18N = {
  de: {
    title: "PocketPrint3D", link: "Modell-Link", paste: "Einfügen", file: "Datei", printer: "Drucker",
    material: "Material", quality: "Qualität", plate: "Druckplatte", supports: "Stützstrukturen",
    brim: "Brim", infill: "Füllung", walls: "Wände", slice: "Slicen", slicing: "Wird geslict …",
    back_to_form: "Zurück (läuft weiter)", print_time: "Druckzeit", layers: "Schichten",
    print: "Drucken", upload_only: "Nur hochladen", to_printer: "Zum Drucker",
    edit: "Einstellungen ändern", new_job: "Neues Modell", no_jobs: "Noch keine Aufträge.",
    token: "API-Token", save: "Speichern", language: "Sprache", lang_auto: "Automatisch",
    install_title: "Als App installieren", install: "Installieren",
    own_profiles: "Eigene Profile",
    power_title: "Stromversorgung",
    power_hint: "Den Drucker über eine smarte Steckdose in Home Assistant ein- und ausschalten (App und Drucker-Tab). Das Token erstellst du in Home Assistant unter Profil → Sicherheit → Langlebige Zugangs-Token.",
    power_addon: "PocketPrint3D läuft als Home-Assistant-Add-on: Adresse und Token können leer bleiben, nur die Steckdose wählen.",
    power_url: "Home-Assistant-Adresse", power_token: "Langlebiges Zugangs-Token", power_entity: "Steckdose (Entität)",
    power_token_kept: "gespeichert (leer = behalten)",
    power_load: "Liste laden", power_test: "Testen", power_remove: "Entfernen",
    power_loaded: "{n} schaltbare Entitäten gefunden – im Feld „Steckdose“ antippen und auswählen.",
    power_ok: "Verbindung OK: {name} ist {state}.", power_saved: "Gespeichert.", power_removed: "Entfernt.",
    power_remove_q: "Stromversorgung für {printer} entfernen?",
    power_on: "Einschalten", power_off: "Ausschalten", power_starting: "Drucker startet …",
    power_off_q: "{printer} ausschalten? Die Steckdose wird abgeschaltet.",
    power_states: { on: "an", off: "aus", unavailable: "nicht erreichbar", unknown: "unbekannt" },
    slots_title: "Slots", slot: "Slot", color_n: "Farbe {n}", slot_empty: "leer",
    slot_empty_warn: "{what}: {slot} ist leer – Filament laden oder einen anderen Slot wählen.",
    slot_material_warn: "{what}: Profil ist {want}, in {slot} ist {have}.",
    profiles_title: "Druckerprofil",
    profiles_hint: "Eigenes Druckerprofil aus OrcaSlicer, z. B. für COSMOS mit AFC: in OrcaSlicer den Drucker wählen, dann Datei → Exportieren → Voreinstellungs-Paket (.zip) oder die JSON-Datei des Profils. Der Server prüft das Profil vor der Verwendung.",
    profile_standard: "Standard: {name}", profile_cosmos: " (mit eingebautem COSMOS-Startcode)",
    profile_config: "Aus config.yaml: {name}", profile_for: "Hochladen für",
    profile_upload: "Druckerprofil hochladen", profile_uploading: "Wird hochgeladen …",
    orca_title: "Aus Orca Cloud importieren", orca_import: "Importieren", orca_importing: "Wird importiert …",
    orca_hint: "Link eines öffentlichen Bundles von cloud.orcaslicer.com – Drucker-, Qualitäts- und Materialprofile, ohne Orca-Konto. Private Bundles lassen sich nur mit Orca-Anmeldung lesen: dann die Profile in OrcaSlicer exportieren und oben hochladen.",
    orca_done: "„{bundle}“: {n} Profile importiert.", orca_skipped: "{n} übersprungen (OrcaSlicer 2.4.2 kennt ihre Basis nicht).",
    orca_choose: "Wähle oben das passende Druckerprofil.",
    profile_uploaded: "„{name}“ wird ab jetzt für {printer} verwendet.",
    profile_stored: "Hochgeladen: {names}", profile_saved: "{printer} verwendet jetzt: {name}",
    profile_delete: "Löschen", profile_delete_q: "Profil „{name}“ löschen?",
    profile_based_on: "basiert auf {name}", profile_own_start: "eigener Startcode", profile_in_use: "verwendet von {printers}",
    profile_kinds: { machine: "Drucker", process: "Qualität", filament: "Material", unknown: "unbekannt" },
    tl_title: "Zeitraffer", tl_always: "Zeitraffer immer erstellen",
    tl_always_hint: "Bei jedem Druck mit Kamera, auch bei Drucken, die direkt am Drucker gestartet wurden (zum Beispiel aus OrcaSlicer). Vor dem Drucken lässt er sich für einen Druck abschalten.",
    sm_title: "Filament-Spulen (Spoolman)", sm_url: "Spoolman-Adresse", sm_test: "Verbindung testen",
    sm_hint: "Adresse deines Spoolman-Servers im Heimnetz, z. B. 192.168.1.20:7912. Der Server liest daraus, welche Spule in welchem Slot liegt (NFC-Chips, NFC-Leser). Die App fragt Spoolman selbst – dort die Adresse unter Einstellungen → Filament-Spulen eintragen.",
    sm_env: "Die Adresse ist in der Server-Konfiguration gesetzt (PRINTSHARE_SPOOLMAN_URL) und gilt vor dieser Einstellung.",
    sm_ok: "Spoolman {version} · {n} Spulen", sm_saved: "Gespeichert.", sm_remove: "Spoolman entfernen",
    sm_remove_q: "Spoolman-Adresse vom Server entfernen?",
    rd_title: "NFC-Leser am Drucker",
    rd_hint: "Ein NFC-Leser im Spulenhalter (ESP32 + PN5180) meldet, welche Spule in welchem Slot liegt – ohne Handy.",
    rd_on: "Eingerichtet (seit {since}).", rd_off: "Nicht eingerichtet.", rd_url: "Adresse", rd_key: "Schlüssel",
    rd_create: "Schlüssel erzeugen", rd_renew: "Neuer Schlüssel", rd_remove: "Leser entfernen",
    rd_key_hint: "Adresse und Schlüssel in den Leser eintragen. Der Schlüssel wird nur jetzt angezeigt.",
    rd_renew_q: "Neuen Schlüssel erzeugen? Der bisherige Leser funktioniert dann erst mit dem neuen Schlüssel wieder.",
    rd_remove_q: "NFC-Leser für {printer} entfernen? Sein Schlüssel funktioniert dann nicht mehr.",
    mf_title: "Eigene Modell-Bibliothek (Manyfold)", mf_url: "Manyfold-Adresse", mf_key: "API-Key",
    mf_hint: "Adresse deines Manyfold (z. B. http://192.168.1.20:3214) und ein API-Key (in Manyfold: dein Name → API-Keys, Bereich „read“). Der Server prüft beides; deine Modelle erscheinen dann in der App unter „Entdecken“.",
    mf_key_kept: "gespeichert (leer = behalten)", mf_ok: "Verbunden – {n} Modelle in deiner Bibliothek.",
    mf_remove: "Manyfold trennen", mf_remove_q: "Manyfold-Verbindung entfernen?", mf_removed: "Entfernt.",
    fd_title: "KI-Fehlererkennung", fd_ml: "Adresse der ML-API", fd_token: "ML_API_TOKEN (optional)",
    fd_server: "Adresse dieses Servers für die ML-API",
    fd_hint: "Erkennt Fehldrucke (Spaghetti, Ablösen) im Kamerabild. Starte nur den Dienst „ml_api“ von Obico (github.com/TheSpaghettiDetective/obico-server, docker compose up -d ml_api, Port 3333, ca. 4 GB RAM). Er holt die Kamerabilder von diesem Server – daher die Server-Adresse, wie der Container sie erreicht. Beim Speichern wird ein Testbild geprüft.",
    fd_sens: "Empfindlichkeit", fd_sens_low: "Niedrig", fd_sens_medium: "Mittel", fd_sens_high: "Hoch",
    fd_action: "Bei Verdacht", fd_act_notify: "Nur melden", fd_act_pause: "Pausieren",
    fd_note: "Die Warnung erscheint in der App (noch keine Push-Mitteilung).",
    fd_ok: "Verbunden – die ML-API hat das Testbild geprüft.", fd_token_kept: "gespeichert (leer = behalten)",
    fd_remove: "Fehlererkennung ausschalten", fd_remove_q: "Fehlererkennung ausschalten?", fd_removed: "Ausgeschaltet.",
    oc_title: "Orca-Cloud-Konto",
    oc_hint: "Deine eigenen Drucker-, Qualitäts- und Materialprofile aus OrcaSlicer kommen automatisch hierher: einmal koppeln, danach holt der Server sie alle 6 Stunden ab. Nur lesen – an deinen Profilen in Orca Cloud ändert sich nichts.",
    oc_id: "Orca-App-ID",
    oc_id_hint: "Orca Cloud verlangt für jede App eine eigene ID (client_id), die das Orca-Team vergibt. Trage hier die ID ein, die du bekommen hast.",
    oc_id_server: "Die App-ID ist auf dem Server eingestellt (ORCA_CLOUD_CLIENT_ID).", oc_id_saved: "App-ID gespeichert.",
    oc_connect: "Mit Orca Cloud koppeln", oc_connect_again: "Neuen Code holen",
    oc_pair_hint: "In Orca Cloud anmelden und diesen Code bestätigen. Diese Seite wartet.", oc_open: "Orca Cloud öffnen",
    oc_waiting: "Warte auf die Bestätigung …", oc_denied: "In Orca Cloud abgelehnt.",
    oc_expired: "Der Code ist abgelaufen – hol einen neuen.",
    oc_connected: "Gekoppelt.", oc_last_sync: "Zuletzt synchronisiert {when} · {n} Profile",
    oc_skipped: "{n} Profile nicht nutzbar: {names}", oc_sync: "Jetzt synchronisieren", oc_synced: "{n} Profile übernommen.",
    oc_disconnect: "Kopplung trennen", oc_disconnect_q: "Die Kopplung mit Orca Cloud trennen?",
    oc_remove_presets_q: "Auch die übernommenen Profile löschen? Profile, die ein Drucker gerade nutzt, bleiben. (Abbrechen = behalten)",
    oc_disconnected: "Kopplung getrennt.",
    bridge_title: "Unterwegs drucken",
    bridge_hint: "Verbindet diesen Server mit deinem kostenlosen PocketPrint3D-Cloud-Konto. Dann erreicht die App seine Drucker von überall – nur über eine ausgehende Verbindung, nichts muss im Router freigegeben werden.",
    bridge_on: "Mit PocketPrint3D Cloud verbinden",
    bridge_off_state: "Aus.", bridge_pairing: "Gib diesen Code in der App ein (Einstellungen → Erweitert → Unterwegs drucken). Er gilt noch {min} Min.",
    bridge_connecting: "Verbinde mit {cloud} …", bridge_connected: "Verbunden mit dem Konto {account}.",
    bridge_error: "Fehler: {error}", bridge_code_hint: "Nach Ablauf erscheint automatisch ein neuer Code.",
    bridge_reset: "Mit anderem Konto koppeln", bridge_reset_q: "Kopplung mit {account} lösen und einen neuen Code anzeigen?",
    pair_title: "App verbinden",
    pair_hint: "In der PocketPrint3D-App unter Einstellungen → Server verbinden → QR-Code scannen. Der Code enthält das Zugangs-Token – nicht öffentlich zeigen.",
    pair_url: "Adresse zu Hause", pair_remote: "Adresse unterwegs (optional, z. B. Tailscale)",
    pair_show: "QR-Code anzeigen", pair_hide: "QR-Code verbergen",
    pair_manual: "Oder von Hand eingeben – Server: {url}{remote} · Token: {token}", pair_manual_remote: " · unterwegs: {remote}",
    pair_localhost: "Diese Adresse zeigt auf den Server selbst – das Handy erreicht sie nicht. Bitte die IP-Adresse des Servers eintragen (z. B. http://192.168.1.10:8484).",
    pair_ingress: "Über Home Assistant geöffnet: diese Adresse erreicht die App nicht. Bitte die IP-Adresse des Home-Assistant-Servers mit Port 8484 eintragen.",
    install_ios: "iPhone (Safari): Teilen → „Zum Home-Bildschirm“.",
    install_android: "Android (Chrome): Menü ⋮ → „App installieren“.",
    share_title: "Links teilen",
    share_android: "Android: Nach der Installation steht PocketPrint3D im Teilen-Menü (nur über HTTPS, z. B. Tailscale).",
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
    infill_pattern: "Füllmuster", pattern_v: "Füllmuster: {v}",
    infill_v: "Füllung {v}", walls_v: "{v} Wände", supports_v: "Stützen: {v}", brim_v: "Brim: {v}",
    arrange: "Auf der Platte", copies: "Anzahl", tilt: "Lage", size: "Größe",
    tilt_: "Wie im Modell", tilt_auto: "Automatisch hinlegen", tilt_x90: "Nach vorne kippen",
    tilt_x_90: "Nach hinten kippen", tilt_y90: "Nach rechts kippen", tilt_y_90: "Nach links kippen",
    tilt_x180: "Auf den Kopf stellen", copies_v: "{n}×", copies_fit: "Nur {n} von {m} Kopien passen auf die Platte.",
    log: [[/^Looking up model files/, "Modelldateien werden gesucht"], [/^Downloading (.*)/, "Download: $1"],
          [/^Waiting for another slice job/, "Wartet auf einen anderen Slice-Auftrag"],
          [/^Slicing for (.*)/, "Slicen für $1"], [/^Sliced: (.*)/, "Geslict: $1"],
          [/^Only (\d+) of (\d+) copies fit on the plate/, "Nur $1 von $2 Kopien passen auf die Platte"],
          [/^Sending to printer and starting/, "Wird gesendet und gestartet"],
          [/^Sending to printer/, "Wird gesendet"], [/^Done/, "Fertig"]],
  },
  en: {
    title: "PocketPrint3D", link: "Model link", paste: "Paste", file: "File", printer: "Printer",
    material: "Material", quality: "Quality", plate: "Build plate", supports: "Supports",
    brim: "Brim", infill: "Infill", walls: "Walls", slice: "Slice", slicing: "Slicing …",
    back_to_form: "Back (keeps running)", print_time: "Print time", layers: "Layers",
    print: "Print", upload_only: "Upload only", to_printer: "Go to printer",
    edit: "Change settings", new_job: "New model", no_jobs: "No jobs yet.",
    token: "API token", save: "Save", language: "Language", lang_auto: "Automatic",
    install_title: "Install as app", install: "Install",
    own_profiles: "Own profiles",
    power_title: "Power",
    power_hint: "Switch the printer on and off with a smart plug in Home Assistant (app and printer tab). Create the token in Home Assistant under Profile → Security → Long-lived access tokens.",
    power_addon: "PocketPrint3D runs as a Home Assistant add-on: address and token can stay empty, just choose the plug.",
    power_url: "Home Assistant address", power_token: "Long-lived access token", power_entity: "Plug (entity)",
    power_token_kept: "stored (empty = keep)",
    power_load: "Load list", power_test: "Test", power_remove: "Remove",
    power_loaded: "{n} switchable entities found – choose one in the “Plug” field.",
    power_ok: "Connection OK: {name} is {state}.", power_saved: "Saved.", power_removed: "Removed.",
    power_remove_q: "Remove the power switch for {printer}?",
    power_on: "Switch on", power_off: "Switch off", power_starting: "Printer is starting …",
    power_off_q: "Switch {printer} off? The plug will be turned off.",
    power_states: { on: "on", off: "off", unavailable: "unreachable", unknown: "unknown" },
    slots_title: "Slots", slot: "Slot", color_n: "Colour {n}", slot_empty: "empty",
    slot_empty_warn: "{what}: {slot} is empty – load filament or choose another slot.",
    slot_material_warn: "{what}: the profile is {want}, {slot} holds {have}.",
    profiles_title: "Printer profile",
    profiles_hint: "Your own printer profile from OrcaSlicer, e.g. for COSMOS with AFC: select the printer in OrcaSlicer, then File → Export → preset bundle (.zip) or the profile's JSON file. The server checks the profile before using it.",
    profile_standard: "Standard: {name}", profile_cosmos: " (with built-in COSMOS start code)",
    profile_config: "From config.yaml: {name}", profile_for: "Upload for",
    profile_upload: "Upload printer profile", profile_uploading: "Uploading …",
    orca_title: "Import from Orca Cloud", orca_import: "Import", orca_importing: "Importing …",
    orca_hint: "Link of a public bundle on cloud.orcaslicer.com – printer, quality and material profiles, no Orca account needed. Private bundles need an Orca login: export the presets in OrcaSlicer and upload the file above instead.",
    orca_done: "“{bundle}”: {n} profiles imported.", orca_skipped: "{n} skipped (OrcaSlicer 2.4.2 doesn't know their base).",
    orca_choose: "Choose the matching printer profile above.",
    profile_uploaded: "“{name}” is now used for {printer}.",
    profile_stored: "Uploaded: {names}", profile_saved: "{printer} now uses: {name}",
    profile_delete: "Delete", profile_delete_q: "Delete profile “{name}”?",
    profile_based_on: "based on {name}", profile_own_start: "own start code", profile_in_use: "used by {printers}",
    profile_kinds: { machine: "Printer", process: "Quality", filament: "Material", unknown: "unknown" },
    tl_title: "Time-lapse", tl_always: "Always make a time-lapse",
    tl_always_hint: "For every print with a camera, also prints started on the printer itself (for example from OrcaSlicer). You can still switch it off for one print before printing.",
    sm_title: "Filament spools (Spoolman)", sm_url: "Spoolman address", sm_test: "Test connection",
    sm_hint: "Address of your Spoolman server on the home network, e.g. 192.168.1.20:7912. The server reads from it which spool sits in which slot (NFC chips, NFC readers). The app asks Spoolman itself – enter the address there under Settings → Filament spools.",
    sm_env: "The address is set in the server configuration (PRINTSHARE_SPOOLMAN_URL) and wins over this setting.",
    sm_ok: "Spoolman {version} · {n} spools", sm_saved: "Saved.", sm_remove: "Remove Spoolman",
    sm_remove_q: "Remove the Spoolman address from the server?",
    rd_title: "NFC reader at the printer",
    rd_hint: "An NFC reader in the spool holder (ESP32 + PN5180) reports which spool sits in which slot – no phone needed.",
    rd_on: "Set up (since {since}).", rd_off: "Not set up.", rd_url: "Address", rd_key: "Key",
    rd_create: "Create key", rd_renew: "New key", rd_remove: "Remove reader",
    rd_key_hint: "Enter the address and key in the reader. The key is shown only now.",
    rd_renew_q: "Create a new key? The current reader works again only with the new key.",
    rd_remove_q: "Remove the NFC reader of {printer}? Its key stops working.",
    mf_title: "Own model library (Manyfold)", mf_url: "Manyfold address", mf_key: "API key",
    mf_hint: "Address of your Manyfold (e.g. http://192.168.1.20:3214) and an API key (in Manyfold: your name → API keys, scope “read”). The server checks both; your models then show up in the app under “Discover”.",
    mf_key_kept: "stored (empty = keep)", mf_ok: "Connected – {n} models in your library.",
    mf_remove: "Disconnect Manyfold", mf_remove_q: "Remove the Manyfold connection?", mf_removed: "Removed.",
    fd_title: "AI failure detection", fd_ml: "ML API address", fd_token: "ML_API_TOKEN (optional)",
    fd_server: "This server's address for the ML API",
    fd_hint: "Spots failed prints (spaghetti, detaching) in the camera picture. Run only Obico's “ml_api” service (github.com/TheSpaghettiDetective/obico-server, docker compose up -d ml_api, port 3333, about 4 GB RAM). It fetches the camera pictures from this server – hence this server's address as the container reaches it. Saving checks a test picture.",
    fd_sens: "Sensitivity", fd_sens_low: "Low", fd_sens_medium: "Medium", fd_sens_high: "High",
    fd_action: "On suspicion", fd_act_notify: "Notify only", fd_act_pause: "Pause",
    fd_note: "The warning shows in the app (no push notification yet).",
    fd_ok: "Connected – the ML API checked the test picture.", fd_token_kept: "stored (empty = keep)",
    fd_remove: "Turn failure detection off", fd_remove_q: "Turn failure detection off?", fd_removed: "Turned off.",
    oc_title: "Orca Cloud account",
    oc_hint: "Your own printer, quality and material presets from OrcaSlicer come here automatically: pair once, then the server fetches them every 6 hours. Read only – nothing changes in Orca Cloud.",
    oc_id: "Orca app ID",
    oc_id_hint: "Orca Cloud requires an own ID (client_id) for every app, given out by the Orca team. Enter the ID you received.",
    oc_id_server: "The app ID is set on the server (ORCA_CLOUD_CLIENT_ID).", oc_id_saved: "App ID saved.",
    oc_connect: "Pair with Orca Cloud", oc_connect_again: "Get a new code",
    oc_pair_hint: "Sign in to Orca Cloud and confirm this code. This page waits.", oc_open: "Open Orca Cloud",
    oc_waiting: "Waiting for the confirmation …", oc_denied: "Declined in Orca Cloud.",
    oc_expired: "The code has expired – get a new one.",
    oc_connected: "Paired.", oc_last_sync: "Last synced {when} · {n} presets",
    oc_skipped: "{n} presets can't be used: {names}", oc_sync: "Sync now", oc_synced: "{n} presets taken over.",
    oc_disconnect: "Unpair", oc_disconnect_q: "Unpair from Orca Cloud?",
    oc_remove_presets_q: "Delete the taken-over presets too? Presets a printer uses stay. (Cancel = keep)",
    oc_disconnected: "Unpaired.",
    bridge_title: "Print from anywhere",
    bridge_hint: "Connects this server to your free PocketPrint3D Cloud account. The app then reaches its printers from anywhere – through an outgoing connection only, nothing has to be opened in your router.",
    bridge_on: "Connect to PocketPrint3D Cloud",
    bridge_off_state: "Off.", bridge_pairing: "Enter this code in the app (Settings → Advanced → Print from anywhere). It is valid for {min} more min.",
    bridge_connecting: "Connecting to {cloud} …", bridge_connected: "Connected to the account {account}.",
    bridge_error: "Error: {error}", bridge_code_hint: "A new code appears by itself when this one expires.",
    bridge_reset: "Pair with another account", bridge_reset_q: "Unpair from {account} and show a new code?",
    pair_title: "Connect the app",
    pair_hint: "In the PocketPrint3D app: Settings → Connect server → Scan QR code. The code contains the access token – don't show it publicly.",
    pair_url: "Home address", pair_remote: "Away address (optional, e.g. Tailscale)",
    pair_show: "Show QR code", pair_hide: "Hide QR code",
    pair_manual: "Or enter by hand – server: {url}{remote} · token: {token}", pair_manual_remote: " · away: {remote}",
    pair_localhost: "This address points to the server itself – the phone can't reach it. Please enter the server's IP address (e.g. http://192.168.1.10:8484).",
    pair_ingress: "Opened through Home Assistant: the app can't reach this address. Please enter the Home Assistant server's IP address with port 8484.",
    install_ios: "iPhone (Safari): Share → “Add to Home Screen”.",
    install_android: "Android (Chrome): menu ⋮ → “Install app”.",
    share_title: "Sharing links",
    share_android: "Android: once installed, PocketPrint3D shows up in the share menu (HTTPS only, e.g. Tailscale).",
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
    infill_pattern: "Infill pattern", pattern_v: "Infill pattern: {v}",
    infill_v: "Infill {v}", walls_v: "{v} walls", supports_v: "Supports: {v}", brim_v: "Brim: {v}",
    arrange: "On the plate", copies: "Copies", tilt: "Position", size: "Size",
    tilt_: "As in the model", tilt_auto: "Lay flat automatically", tilt_x90: "Tip forward",
    tilt_x_90: "Tip backward", tilt_y90: "Tip to the right", tilt_y_90: "Tip to the left",
    tilt_x180: "Upside down", copies_v: "{n}×", copies_fit: "Only {n} of {m} copies fit on the plate.",
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
  if (view === "settings") { loadPairing(); loadProfiles(); loadPower(); loadBridge(); loadAppSettings(); }
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
function fillGrouped(sel, names, value, own = []) {
  const groups = new Map();
  for (const n of names) {
    const g = own.includes(n) ? t("own_profiles") : n.split(" ")[0];     // uploaded presets first, as one group
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

// OrcaSlicer infill patterns: [German, English]; unknown keys are shown as they are
const INFILL_NAMES = {
  rectilinear: ["Geradlinig", "Rectilinear"], alignedrectilinear: ["Geradlinig ausgerichtet", "Aligned Rectilinear"],
  zigzag: ["Zickzack", "Zig Zag"], crosszag: ["Kreuz-Zickzack", "Cross Zag"], lockedzag: ["Locked Zag", "Locked Zag"],
  line: ["Linie", "Line"], grid: ["Gitter", "Grid"], triangles: ["Dreiecke", "Triangles"],
  "tri-hexagon": ["Tri-Hexagon", "Tri-hexagon"], cubic: ["Kubisch", "Cubic"],
  adaptivecubic: ["Adaptiv kubisch", "Adaptive Cubic"], quartercubic: ["Viertel-kubisch", "Quarter Cubic"],
  supportcubic: ["Stütz-kubisch", "Support Cubic"], lightning: ["Blitz", "Lightning"],
  honeycomb: ["Bienenwabe", "Honeycomb"], "3dhoneycomb": ["3D-Bienenwabe", "3D Honeycomb"],
  "lateral-honeycomb": ["Seitliche Wabe", "Lateral Honeycomb"], "lateral-lattice": ["Seitliches Gitter", "Lateral Lattice"],
  crosshatch: ["Kreuzschraffur", "Cross Hatch"], tpmsd: ["TPMS-D", "TPMS-D"], tpmsfk: ["TPMS-FK", "TPMS-FK"],
  gyroid: ["Gyroid", "Gyroid"], concentric: ["Konzentrisch", "Concentric"], hilbertcurve: ["Hilbert-Kurve", "Hilbert Curve"],
  archimedeanchords: ["Archimedische Sehnen", "Archimedean Chords"], octagramspiral: ["Oktagramm-Spirale", "Octagram Spiral"],
};
const infillName = k => (INFILL_NAMES[k] || [k, k])[lang === "de" ? 0 : 1];

function setDetailControls(d, keep = {}) {
  buildSeg($("supports"), S.options.supports, "sup_", keep.supports ?? d.supports);
  buildSeg($("brim"), S.options.brims, "brim_", keep.brim ?? d.brim);
  const inf = [0, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100].filter(v => v !== d.infill);
  fillSelect($("infill"), [["", t("standard", { v: (d.infill ?? "?") + "\u00a0%" })], ...inf.map(v => [v, v + "\u00a0%"])],
             keep.infill ?? "");
  const pats = (S.options.infill_patterns || []).filter(v => v !== d.infill_pattern);   // older servers: none
  $("infill_pattern").hidden = !pats.length;
  document.querySelector('label[for="infill_pattern"]').hidden = !pats.length;
  fillSelect($("infill_pattern"), [["", t("standard", { v: d.infill_pattern ? infillName(d.infill_pattern) : "?" })],
                                   ...pats.map(v => [v, infillName(v)])], keep.infill_pattern ?? "");
  const walls = [1, 2, 3, 4, 5, 6].filter(v => v !== d.walls);
  fillSelect($("walls"), [["", t("standard", { v: d.walls ?? "?" })], ...walls.map(v => [v, String(v)])],
             keep.walls ?? "");
}

// plate options: one choice for the position -> rotate_x / rotate_y / orient (server 0.14.0)
const TILTS = { "": {}, auto: { orient: true }, x90: { rotate_x: 90 }, x_90: { rotate_x: -90 },
                y90: { rotate_y: 90 }, y_90: { rotate_y: -90 }, x180: { rotate_x: 180 } };
const SIZES = [25, 50, 75, 100, 125, 150, 200, 300];
function tiltKey(o) {
  if (o.orient) return "auto";
  return Object.keys(TILTS).find(k => k && k !== "auto" && (TILTS[k].rotate_x || 0) === (o.rotate_x || 0) &&
                                       (TILTS[k].rotate_y || 0) === (o.rotate_y || 0)) || "";
}
function setPlateControls(keep = {}) {
  $("copies").value = keep.copies || 1;
  fillSelect($("tilt"), Object.keys(TILTS).map(k => [k, t("tilt_" + k)]), tiltKey(keep));
  fillSelect($("scale"), SIZES.map(v => [v, v + "\u00a0%"]), keep.scale || 100);
}
function plateLabel(o) {
  const out = [];
  if (o.copies > 1) out.push(t("copies_v", { n: o.copies }));
  const k = tiltKey(o);
  if (k) out.push(t("tilt_" + k));
  if (o.scale && o.scale !== 100) out.push(o.scale + "\u00a0%");
  return out;
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
  fillGrouped($("filament"), S.options.materials, prefs.filament ?? S.options.defaults.filament, S.options.own?.materials);
  const ownP = S.options.own?.processes || [];
  fillSelect($("process"), S.options.processes.map(p => [p, ownP.includes(p) ? `★ ${short(p)}` : short(p)]),
             prefs.process ?? S.options.defaults.process);
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
  if ($("infill_pattern").value !== "") o.infill_pattern = $("infill_pattern").value;
  if ($("walls").value !== "") o.walls = Number($("walls").value);
  const copies = Math.min(50, Math.max(1, Math.round(Number($("copies").value) || 1)));
  if (copies > 1) o.copies = copies;
  Object.assign(o, TILTS[$("tilt").value] || {});
  if (Number($("scale").value) !== 100) o.scale = Number($("scale").value);
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
  if (o.sparse_infill_pattern) out.push(t("pattern_v", { v: infillName(o.sparse_infill_pattern) }));
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
  const ro = j.request?.options || {};
  const arranged = plateLabel({ ...ro, copies: r.copies ?? ro.copies });
  if (arranged.length) rows.push([t("arrange"), arranged.join(" · "), true]);
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
  const fewer = r.copies_requested && r.copies != null && r.copies < r.copies_requested;
  $("review-error").textContent = j.error || (fewer ? t("copies_fit", { n: r.copies, m: r.copies_requested }) : "");
  $("review-error").hidden = !j.error && !fewer;
  $("review-error").classList.toggle("warn", !j.error && fewer);
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
                        supports: o.supports, brim: o.brim, infill: o.infill, infill_pattern: o.infill_pattern,
                        walls: o.walls });
    setPlateControls(o);
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
      style: "display:inline-block;margin-top:12px" }, t("camera") + " ↗") : null,
    // issue #9: smart plug - "switch on" while the printer is off, "switch off" only when it isn't printing
    p.power && !s ? (Date.now() - (S.starting?.[p.id] || 0) < 120000
      ? el("p", { class: "hint" }, t("power_starting"))
      : el("button", { type: "button", class: "primary", onclick: () => switchPower(p, true) }, t("power_on"))) : null,
    p.power && s && !busy ? el("button", { type: "button", class: "ghost", onclick: () => switchPower(p, false) },
      t("power_off")) : null);
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
async function importOrcaCloud() {
  const printer = S.printers.find(p => p.id === $("profile-target").value) || S.printers[0];
  profilesMsg("");
  $("orca-import").disabled = true;
  $("orca-import").textContent = t("orca_importing");
  try {
    const r = await api("/api/profiles/orca-cloud", { method: "POST", body: JSON.stringify({ link: $("orca-link").value.trim() }) });
    const lines = [t("orca_done", { bundle: r.bundle.name || "Orca Cloud", n: r.imported.length })];
    if (r.skipped.length) lines.push(t("orca_skipped", { n: r.skipped.length }));
    // one printer preset for this printer's model: use it; several (nozzles, AFC …): the user picks
    const base = printer && PR.assigned[printer.id] ? PR.assigned[printer.id].machine : null;
    const fitting = r.imported.filter(p => p.kind === "machine" && p.inherits === base);
    if (printer && fitting.length === 1) {
      PR.assigned[printer.id] = await api(`/api/printers/${encodeURIComponent(printer.id)}/profile`,
                                          { method: "PUT", body: JSON.stringify({ machine_file: fitting[0].file }) });
      lines.push(t("profile_uploaded", { name: profileName(fitting[0]), printer: printer.name }));
    } else if (r.imported.some(p => p.kind === "machine")) {
      lines.push(t("orca_choose"));
    }
    profilesMsg(lines.join(" "));
    $("orca-link").value = "";
    PR.profiles = await api("/api/profiles");
  } catch (e) { profilesMsg(e.message, true); }
  $("orca-import").disabled = false;
  $("orca-import").textContent = t("orca_import");
  renderProfiles();
}
$("orca-import").onclick = importOrcaCloud;
$("profile-upload").onclick = () => $("profile-file").click();
$("profile-file").onchange = () => {
  const f = $("profile-file").files[0];
  $("profile-file").value = "";          // the same file can be chosen again
  if (f) uploadProfile(f);
};

// ---------- power: smart plug through Home Assistant (issue #9) ----------
const PW = { cfg: null };
const powerBase = () => `/api/printers/${encodeURIComponent($("power-printer").value)}/power`;
function powerMsg(text, error = false) {
  $("power-msg").textContent = text || "";
  $("power-msg").className = error ? "error" : "hint";
  $("power-msg").hidden = !text;
}
function powerBody() {
  const b = { url: $("power-url").value.trim(), entity: $("power-entity").value.trim() };
  if ($("power-token").value.trim()) b.token = $("power-token").value.trim();   // empty = keep the stored token
  return b;
}
async function loadPower() {
  if (!store.get("ps_token")) { $("power-card").hidden = true; return; }
  try { if (!S.printers.length) S.printers = await api("/api/printers"); } catch { return; }
  if (!S.printers.length) { $("power-card").hidden = true; return; }
  const sel = $("power-printer");
  fillSelect(sel, S.printers.map(p => [p.id, p.name]), sel.value || store.get("ps_printer"));
  $("power-printer-row").hidden = S.printers.length < 2;
  $("power-card").hidden = false;
  await loadPowerConfig();
}
async function loadPowerConfig() {
  powerMsg("");
  try { PW.cfg = await api(powerBase() + "/config"); } catch (e) { return powerMsg(e.message, true); }
  $("power-url").value = PW.cfg.url || "";
  $("power-entity").value = PW.cfg.entity || "";
  $("power-token").value = "";
  $("power-token").placeholder = PW.cfg.token_set ? t("power_token_kept") : "";
  $("power-addon").hidden = !PW.cfg.addon;
  $("power-remove").hidden = !PW.cfg.configured;
}
$("power-printer").onchange = loadPowerConfig;
$("power-load").onclick = async () => {
  powerMsg("");
  try {
    const list = await post(powerBase() + "/entities", powerBody());
    $("power-entities").replaceChildren(...list.map(e => el("option", { value: e.entity }, `${e.name} (${e.state})`)));
    powerMsg(t("power_loaded", { n: list.length }));
    $("power-entity").focus();
  } catch (e) { powerMsg(e.message, true); }
};
$("power-test").onclick = async () => {
  powerMsg("");
  try {
    const r = await post(powerBase() + "/test", powerBody());
    if (r.ok) powerMsg(t("power_ok", { name: r.name || $("power-entity").value, state: t("power_states")[r.state] || r.state }));
    else powerMsg(r.error, true);
  } catch (e) { powerMsg(e.message, true); }
};
$("power-save").onclick = async () => {
  powerMsg("");
  try {
    await api(powerBase() + "/config", { method: "PUT", body: JSON.stringify(powerBody()) });
    await loadPowerConfig();
    S.printers = await api("/api/printers");          // "power" flag for the printer tab
    powerMsg(t("power_saved"));
  } catch (e) { powerMsg(e.message, true); }
};
$("power-remove").onclick = async () => {
  const name = S.printers.find(p => p.id === $("power-printer").value)?.name || "";
  if (!confirm(t("power_remove_q", { printer: name }))) return;
  try {
    await api(powerBase() + "/config", { method: "DELETE" });
    await loadPowerConfig();
    S.printers = await api("/api/printers");
    powerMsg(t("power_removed"));
  } catch (e) { powerMsg(e.message, true); }
};
async function switchPower(p, on) {
  if (!on && !confirm(t("power_off_q", { printer: p.name }))) return;
  try {
    await post(`/api/printers/${encodeURIComponent(p.id)}/power`, { on });
    if (on) S.starting = { ...(S.starting || {}), [p.id]: Date.now() };
  } catch (e) { alert(e.message); }
  setTimeout(pollPrinters, 1500);
}

// ---------- bridge mode (docs/BRIDGE.md) ----------
const B = { timer: 0, state: null };
async function loadBridge() {
  clearTimeout(B.timer);
  if (!store.get("ps_token") || current !== "settings") return;
  let r;
  try { r = await api("/api/bridge"); } catch { $("bridge-card").hidden = true; return; }   // cloud server: no bridge mode
  B.state = r;
  $("bridge-card").hidden = false;
  $("bridge-on").checked = r.enabled;
  const text = !r.enabled ? t("bridge_off_state")
    : r.state === "pairing" && r.code ? t("bridge_pairing", { min: Math.max(1, Math.ceil((r.code_expires_in || 0) / 60)) })
    : r.state === "connected" ? t("bridge_connected", { account: r.account || "?" })
    : r.state === "error" ? t("bridge_error", { error: r.error || "?" })
    : t("bridge_connecting", { cloud: r.cloud.replace(/^https?:\/\//, "") }) + (r.error ? " " + r.error : "");
  $("bridge-state").textContent = text;
  const showCode = r.enabled && r.state === "pairing" && !!r.code;
  $("bridge-code").textContent = showCode ? r.code : "";
  $("bridge-code").hidden = $("bridge-code-hint").hidden = !showCode;
  $("bridge-reset").hidden = !(r.enabled && r.paired);
  // keep it fresh while it changes (code appears, gets entered, connection comes up)
  if (r.enabled) B.timer = setTimeout(loadBridge, r.state === "connected" ? 15000 : 3000);
}
$("bridge-on").onchange = async () => {
  try { await post("/api/bridge", { enabled: $("bridge-on").checked }); } catch (e) { alert(e.message); }
  setTimeout(loadBridge, 800);
};
$("bridge-reset").onclick = async () => {
  if (!confirm(t("bridge_reset_q", { account: B.state?.account || "?" }))) return;
  try { await post("/api/bridge/reset", {}); } catch (e) { alert(e.message); }
  setTimeout(loadBridge, 1500);
};

// ---------- settings the app has too (0.41.0): time-lapse, Spoolman, NFC reader, Manyfold, failure detection ----------
function cardMsg(id, text, error = false) {
  $(id).textContent = text || "";
  $(id).className = error ? "error" : "hint";
  $(id).hidden = !text;
}
async function loadAppSettings() {
  if (!store.get("ps_token")) {
    for (const c of ["timelapse-card", "spoolman-card", "reader-card", "manyfold-card", "failure-card", "orca-card"]) $(c).hidden = true;
    return;
  }
  loadTimelapse(); loadSpoolman(); loadReader(); loadManyfold(); loadFailure(); loadOrca();
}

async function loadTimelapse() {
  cardMsg("tl-msg", "");
  try { $("tl-always").checked = (await api("/api/timelapse/config")).always; }
  catch { $("timelapse-card").hidden = true; return; }        // older server (404) or cloud (409)
  $("timelapse-card").hidden = false;
}
$("tl-always").onchange = async () => {
  const on = $("tl-always").checked;
  cardMsg("tl-msg", "");
  try { $("tl-always").checked = (await api("/api/timelapse/config", { method: "PUT", body: JSON.stringify({ always: on }) })).always; }
  catch (e) { $("tl-always").checked = !on; cardMsg("tl-msg", e.message, true); }
};

async function loadSpoolman() {
  cardMsg("sm-msg", "");
  let r;
  try { r = await api("/api/spool-source"); } catch { $("spoolman-card").hidden = true; return; }
  $("spoolman-card").hidden = false;
  $("sm-url").value = r.spoolman_url || "";
  $("sm-remove").hidden = !r.spoolman_url;
  $("sm-env").hidden = true;
}
async function testSpoolman() {
  const r = await post("/api/spool-source/test", { source: "spoolman", spoolman_url: $("sm-url").value.trim() });
  cardMsg("sm-msg", t("sm_ok", { version: r.version || "?", n: r.spools }));
  return r;
}
$("sm-test").onclick = async () => {
  cardMsg("sm-msg", "");
  try { await testSpoolman(); } catch (e) { cardMsg("sm-msg", e.message, true); }
};
$("sm-save").onclick = async () => {
  cardMsg("sm-msg", "");
  try {
    const tested = await testSpoolman();      // only an address this server reaches
    const r = await api("/api/spool-source", { method: "PUT",
      body: JSON.stringify({ source: "spoolman", spoolman_url: tested.url }) });
    $("sm-url").value = r.spoolman_url || "";
    $("sm-remove").hidden = !r.spoolman_url;
    // PRINTSHARE_SPOOLMAN_URL wins over the stored address
    $("sm-env").hidden = !r.spoolman_url || r.spoolman_url === tested.url;
    cardMsg("sm-msg", t("sm_ok", { version: tested.version || "?", n: tested.spools }) + " · " + t("sm_saved"));
  } catch (e) { cardMsg("sm-msg", e.message, true); }
};
$("sm-remove").onclick = async () => {
  if (!confirm(t("sm_remove_q"))) return;
  try {
    const r = await api("/api/spool-source", { method: "PUT", body: JSON.stringify({ source: "spoolman", spoolman_url: null }) });
    $("sm-url").value = r.spoolman_url || "";
    $("sm-remove").hidden = !r.spoolman_url;
    $("sm-env").hidden = !r.spoolman_url;       // still set: it comes from the server configuration
    cardMsg("sm-msg", "");
  } catch (e) { cardMsg("sm-msg", e.message, true); }
};

const readerBase = () => `/api/printers/${encodeURIComponent($("rd-printer").value)}/reader-key`;
async function loadReader() {
  try { if (!S.printers.length) S.printers = await api("/api/printers"); } catch { /* shown by the other cards */ }
  if (!S.printers.length) { $("reader-card").hidden = true; return; }
  const sel = $("rd-printer");
  fillSelect(sel, S.printers.map(p => [p.id, p.name]), sel.value || S.printers[0].id);
  $("rd-printer-row").hidden = S.printers.length < 2;
  await loadReaderState();
}
async function loadReaderState() {
  cardMsg("rd-msg", "", true);
  $("rd-new").hidden = true;
  $("rd-key").value = "";
  let r;
  try { r = await api(readerBase()); } catch { $("reader-card").hidden = true; return; }   // older server
  $("reader-card").hidden = false;
  $("rd-state").textContent = r.enabled
    ? t("rd_on", { since: r.created ? new Date(r.created * 1000).toLocaleDateString(lang) : "?" }) : t("rd_off");
  $("rd-create").textContent = t(r.enabled ? "rd_renew" : "rd_create");
  $("rd-create").dataset.enabled = r.enabled ? "1" : "";
  $("rd-remove").hidden = !r.enabled;
}
$("rd-printer").onchange = loadReaderState;
$("rd-create").onclick = async () => {
  if ($("rd-create").dataset.enabled && !confirm(t("rd_renew_q"))) return;
  try {
    const r = await post(readerBase(), {});
    await loadReaderState();
    $("rd-url").value = r.url;
    $("rd-key").value = r.key;                   // shown once: the server keeps only its hash
    $("rd-new").hidden = false;
  } catch (e) { cardMsg("rd-msg", e.message, true); }
};
$("rd-remove").onclick = async () => {
  const name = S.printers.find(p => p.id === $("rd-printer").value)?.name || "";
  if (!confirm(t("rd_remove_q", { printer: name }))) return;
  try { await api(readerBase(), { method: "DELETE" }); await loadReaderState(); }
  catch (e) { cardMsg("rd-msg", e.message, true); }
};
for (const id of ["rd-url", "rd-key"]) $(id).onfocus = () => $(id).select();

const MF = { cfg: null };
async function loadManyfold() {
  cardMsg("mf-msg", "");
  try { MF.cfg = await api("/api/manyfold/config"); } catch { $("manyfold-card").hidden = true; return; }
  $("manyfold-card").hidden = false;
  $("mf-url").value = MF.cfg.url || "";
  $("mf-key").value = "";
  $("mf-key").placeholder = MF.cfg.token_set ? t("mf_key_kept") : "";
  $("mf-remove").hidden = !MF.cfg.configured;
}
$("mf-save").onclick = async () => {
  cardMsg("mf-msg", "");
  const body = { url: $("mf-url").value.trim() };
  if ($("mf-key").value.trim()) body.token = $("mf-key").value.trim();      // empty = keep the stored key
  try {
    const r = await api("/api/manyfold/config", { method: "PUT", body: JSON.stringify(body) });
    await loadManyfold();
    cardMsg("mf-msg", t("mf_ok", { n: r.models }));
  } catch (e) { cardMsg("mf-msg", e.message, true); }
};
$("mf-remove").onclick = async () => {
  if (!confirm(t("mf_remove_q"))) return;
  try { await api("/api/manyfold/config", { method: "DELETE" }); await loadManyfold(); cardMsg("mf-msg", t("mf_removed")); }
  catch (e) { cardMsg("mf-msg", e.message, true); }
};

// own OrcaSlicer presets from an Orca Cloud account (0.42.0, issue #7): app ID, pairing code, sync - same as the app
const OC = { st: null, timer: null, opened: false };
function showOrca(st) {
  OC.st = st;
  const p = st.pending, fromServer = st.client_id_from === "server";
  $("orca-card").hidden = false;
  $("oc-id-row").hidden = fromServer;
  $("oc-id-server").hidden = !fromServer;
  if (!fromServer && document.activeElement !== $("oc-id")) $("oc-id").value = st.client_id || "";
  $("oc-pair").hidden = !p;
  if (p) {
    $("oc-code").textContent = p.error ? "" : p.user_code;
    $("oc-code").hidden = !!p.error;
    $("oc-pair-hint").hidden = !!p.error;
    $("oc-pair-state").textContent = p.error === "denied" ? t("oc_denied") : p.error === "expired" ? t("oc_expired")
      : p.error || t("oc_waiting");
    $("oc-pair-state").className = p.error ? "error" : "hint";
    const url = p.verification_uri_complete || p.verification_uri;
    $("oc-open").hidden = !url || !!p.error;
    OC.url = url;
  }
  $("oc-state").hidden = !st.connected;
  if (st.connected) {
    let text = t("oc_connected");
    if (st.last_sync) text += " " + t("oc_last_sync", { when: ago(st.last_sync), n: st.count });
    if (st.skipped && st.skipped.length)
      text += "\n" + t("oc_skipped", { n: st.skipped.length, names: st.skipped.slice(0, 4).map(x => x.name).join(", ") });
    $("oc-state").textContent = text;
  }
  if (st.last_error && !p) cardMsg("oc-msg", st.last_error, true);
  $("oc-connect").hidden = st.connected;
  $("oc-connect").disabled = !st.client_id;
  $("oc-connect").textContent = t(p ? "oc_connect_again" : "oc_connect");
  $("oc-sync").hidden = !st.connected;
  $("oc-disconnect").hidden = !st.connected;
  clearTimeout(OC.timer);
  if (p && !p.error) OC.timer = setTimeout(refreshOrca, 3000);       // follow the pairing until it is confirmed
}
async function refreshOrca() {
  if ($("view-settings").hidden) return;
  try { showOrca(await api("/api/orca-cloud")); } catch { /* keep the last state */ }
}
async function loadOrca() {
  cardMsg("oc-msg", "");
  let st;
  try { st = await api("/api/orca-cloud"); } catch { $("orca-card").hidden = true; return; }   // older server
  showOrca(st);
}
async function orcaCall(path, method, body, message) {
  cardMsg("oc-msg", "");
  try {
    const st = await api(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
    showOrca(st);
    if (message) cardMsg("oc-msg", typeof message === "function" ? message(st) : message);
    return st;
  } catch (e) { cardMsg("oc-msg", e.message, true); }
}
$("oc-save").onclick = () => orcaCall("/api/orca-cloud", "PUT", { client_id: $("oc-id").value.trim() || null }, t("oc_id_saved"));
$("oc-connect").onclick = async () => {
  const w = window.open("about:blank", "_blank");          // opened in the click, filled once the code is there
  const st = await orcaCall("/api/orca-cloud/connect", "POST", {});
  const url = st && st.pending && (st.pending.verification_uri_complete || st.pending.verification_uri);
  if (w) { if (url) w.location = url; else w.close(); }
};
$("oc-open").onclick = () => { if (OC.url) window.open(OC.url, "_blank", "noopener"); };
$("oc-sync").onclick = () => orcaCall("/api/orca-cloud/sync", "POST", {}, st => t("oc_synced", { n: st.count }));
$("oc-disconnect").onclick = async () => {
  if (!confirm(t("oc_disconnect_q"))) return;
  const remove = confirm(t("oc_remove_presets_q"));
  await orcaCall("/api/orca-cloud?remove_presets=" + remove, "DELETE", undefined, t("oc_disconnected"));
};

const FD = { cfg: null };
async function loadFailure() {
  cardMsg("fd-msg", "");
  try { FD.cfg = await api("/api/failure-detection/config"); } catch { $("failure-card").hidden = true; return; }
  $("failure-card").hidden = false;
  $("fd-ml").value = FD.cfg.ml_url || "";
  $("fd-token").value = "";
  $("fd-token").placeholder = FD.cfg.token_set ? t("fd_token_kept") : "";
  $("fd-server").value = FD.cfg.server_url || location.origin;
  buildSeg($("fd-sens"), ["low", "medium", "high"], "fd_sens_", FD.cfg.sensitivity || "medium");
  buildSeg($("fd-action"), ["notify", "pause"], "fd_act_", FD.cfg.action || "notify");
  $("fd-remove").hidden = !FD.cfg.configured;
}
$("fd-save").onclick = async () => {
  cardMsg("fd-msg", "");
  const body = { ml_url: $("fd-ml").value.trim(), server_url: $("fd-server").value.trim(),
    interval: FD.cfg?.interval || 15, sensitivity: segValue($("fd-sens")), action: segValue($("fd-action")) };
  if ($("fd-token").value.trim()) body.ml_token = $("fd-token").value.trim();     // empty = keep the stored token
  try {
    await api("/api/failure-detection/config", { method: "PUT", body: JSON.stringify(body) });
    await loadFailure();
    cardMsg("fd-msg", t("fd_ok"));
  } catch (e) { cardMsg("fd-msg", e.message, true); }
};
$("fd-remove").onclick = async () => {
  if (!confirm(t("fd_remove_q"))) return;
  try { await api("/api/failure-detection/config", { method: "DELETE" }); await loadFailure(); cardMsg("fd-msg", t("fd_removed")); }
  catch (e) { cardMsg("fd-msg", e.message, true); }
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
  setPlateControls();
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});

  show(location.hash.slice(1) || "print");
  if (!store.get("ps_token")) return showSettings(t("token_missing"));
  try { await loadPrinters(); } catch (e) { if (!(e instanceof ApiError) || e.message !== t("token_invalid")) formError(e.message); }
  if (shared) loadFiles();
}
init();
