# Mobile Print-App – Softwareanforderungen

Sep 26, 2026 · @Dominique

## 1. Ziel und Umfang

Eine iOS-App soll 3D-Modelle am iPhone finden, druckfertig einstellen und direkt an den eigenen Drucker schicken – nach dem Vorbild von Bambu Handy, aber selbst gehostet und herstellerunabhängig. Das Slicen übernimmt ein OrcaSlicer auf dem Heimserver (Unraid), nicht das Telefon.

**Im Umfang**

- Modellquellen: Printables, Dateien, Teilen-Menü von iOS, eigene Bibliothek
- Druckvorbereitung am Handy: Drucker, Düse, Druckplatte, Material, Qualität, Supports, Platzierung
- Slicen auf dem Server, Vorschau und Prüfung in der App
- Druck starten, überwachen, steuern, benachrichtigen
- Zieldrucker: Elegoo Centauri Carbon mit COSMOS (Klipper/Moonraker) und CANVAS (4 Lanes via AFC); weitere Klipper-Drucker; optional Centauri mit Stock-Firmware (SDCP)

**Nicht im Umfang (v1)**

- Slicen auf dem iPhone selbst
- Supports malen, Modifier, Teile schneiden, Mehrfarben-Bemalung einzelner Flächen – dafür Desktop-Orca, Ergebnis als 3MF-Projekt übernehmen
- Cloud-Betrieb für Dritte, Druckfarm-Funktionen

**Abgrenzung zu SimplyPrint:** SimplyPrint deckt Cloud-Slicing, App und Centauri-Anbindung bereits ab, erzwingt aber die Cloud und bietet keine direkte Printables-Suche. Die Eigenentwicklung rechtfertigt sich über lokalen Betrieb, Printables-Integration und Home-Assistant-Anbindung.

## 2. Systemarchitektur

Die App spricht nur mit dem eigenen Orchestrator; der erledigt Download, Slicing und Drucker-Kommunikation im LAN. Der Drucker ist nie direkt aus dem Internet erreichbar.

| Komponente | Aufgabe | Technik (Vorschlag) |
| --- | --- | --- |
| iOS-App | Modellsuche, Einstellungen, Vorschau, Steuerung, Push | SwiftUI, SceneKit/Model I/O, WebView für G-Code-Viewer |
| Share Extension | Printables-Link oder Datei aus Safari/Dateien übernehmen | iOS App Extension |
| Orchestrator | REST/WebSocket-API, Jobs, Printables-Anbindung, Druckerlogik, Dateiablage | FastAPI oder Node, Docker |
| Slice-Dienst | OrcaSlicer-CLI kapseln, Profile anwenden, Metadaten auslesen | Basis: AFKFelix/orca-slicer-api oder escalopa/orcaslicer-api |
| Profil-GUI (optional) | Profile komfortabel im Browser pflegen | linuxserver/orcaslicer |
| Drucker-Adapter | Upload, Start, Status, Steuerung je Drucker | Moonraker (primär), SDCP (optional) |
| Speicher | Modelle, Profile, G-Code, Verlauf | Unraid-Volume + SQLite |
| Home Assistant (optional) | Automationen, Benachrichtigungen, AWTRIX-Anzeige | Webhook/MQTT |

Ablauf: App → Orchestrator (Modell + Einstellungen) → Slice-Dienst → Prüfung in der App → Orchestrator → Moonraker → Drucker; Status fließt per WebSocket zurück.

## 3. Modellquellen und Bibliothek

Priorität: **M** = Muss (MVP), **S** = Soll, **K** = Kann.

| ID | Anforderung | Prio |
| --- | --- | --- |
| MQ-01 | Printables-Link per Teilen-Menü (Safari) an die App übergeben; Server lädt die Dateien des Modells | M |
| MQ-02 | Bei mehreren Dateien eines Modells: Liste mit Vorschau, Auswahl einzelner oder aller Dateien | M |
| MQ-03 | Lokale Dateien importieren (STL, 3MF, OBJ, STEP) aus Dateien-App und iCloud | M |
| MQ-04 | Fertige 3MF-Projekte (am Desktop vorbereitet) und bereits geslicten G-Code direkt drucken | M |
| MQ-05 | Printables-Suche und -Stöbern in der App (Name, Kategorie, Sortierung, Bilder, Likes, Downloads) | S |
| MQ-06 | Printables-Details: Bilder, Beschreibung, Lizenz, Urheber, empfohlene Druckeinstellungen des Autors anzeigen | S |
| MQ-07 | Eigene Bibliothek: Modelle mit Quelle, Datum, Tags, Favoriten; zuletzt gedruckt | S |
| MQ-08 | Erneut drucken aus dem Verlauf mit den damaligen Einstellungen | S |
| MQ-09 | Weitere Quellen (Thingiverse, MakerWorld, eigene OpenSCAD-Ausgaben aus Ordner) | K |
| MQ-10 | Lizenz und Urheber werden gespeichert und im Verlauf angezeigt | S |

Hinweis: Printables hat keine offizielle API. MQ-05/06 nutzen die interne GraphQL-Schnittstelle und müssen gekapselt sein, damit ein Bruch nur den Such-Teil betrifft (siehe Risiken).

## 4. Druckvorbereitung (Einstellungen in der App)

Standard ist ein Profil mit wenigen Schaltern; alle Werte überschreiben das gewählte Orca-Profil nur für diesen Auftrag. Vorbelegung jeweils mit der zuletzt genutzten Auswahl pro Drucker.

### 4.1 Drucker und Hardware

| ID | Anforderung | Prio |
| --- | --- | --- |
| DV-01 | Drucker auswählen (mehrere Drucker möglich); Online-Status und Belegung sichtbar | M |
| DV-02 | Düse: Durchmesser (0,2 / 0,4 / 0,6 / 0,8 mm) und Material (Messing, gehärteter Stahl) je Drucker hinterlegt, pro Auftrag wählbar | M |
| DV-03 | Druckplatte wählen: Textured PEI, Smooth PEI, Cool Plate, Engineering Plate, eigene Platten; setzt Betttemperatur je Material | M |
| DV-04 | Warnung bei unpassender Kombination (z. B. PLA auf Engineering Plate, CF-Filament auf Messingdüse, Modell größer als Bauraum) | M |

### 4.2 Material

| ID | Anforderung | Prio |
| --- | --- | --- |
| MA-01 | Filamentprofil wählen (Typ, Marke, Profilname) aus den synchronisierten Orca-Profilen | M |
| MA-02 | Aktuell geladenes Material je Lane vom Drucker lesen (CANVAS/AFC über Moonraker: Typ, Farbe, Lane-Status) | M |
| MA-03 | Einfarbiger Druck: Lane wählen; Vorschlag der Lane mit passendem Material | M |
| MA-04 | Mehrfarbig: Objekte bzw. Filamente eines 3MF den 4 Lanes zuordnen (Mapping-Dialog mit Farbfeldern) | S |
| MA-05 | Mehrfarb-Optionen: Spülvolumen-Faktor, Prime Tower an/aus und Position, Spülen in Infill/Support | S |
| MA-06 | Kosten und Verbrauch je Filament anzeigen (Preis pro kg im Profil) | S |
| MA-07 | Spoolman-Anbindung: Spule wählen, Restmenge prüfen, Warnung bei zu wenig Filament | K |
| MA-08 | Temperatur-Overrides (Düse, Bett) je Auftrag | K |

### 4.3 Qualität und Festigkeit

| ID | Anforderung | Prio |
| --- | --- | --- |
| QU-01 | Qualitätsstufe als Prozessprofil (z. B. 0,12 Fein / 0,20 Standard / 0,28 Entwurf) | M |
| QU-02 | Schichthöhe frei wählbar innerhalb der Düsengrenzen; erste Schicht separat | S |
| QU-03 | Wandanzahl, obere/untere Schichten | M |
| QU-04 | Füllung: Dichte und Muster (Gyroid, Grid, Cubic, Lightning …) | M |
| QU-05 | Ironing (Glattbügeln) an/aus | K |
| QU-06 | Vasenmodus | K |

### 4.4 Supports und Haftung

| ID | Anforderung | Prio |
| --- | --- | --- |
| SU-01 | Supports an/aus | M |
| SU-02 | Typ: normal oder Tree; nur auf Druckplatte ja/nein | M |
| SU-03 | Überhangwinkel (Schwellwert) | S |
| SU-04 | Support-Material/Interface-Lane bei Mehrfarbe (z. B. PETG als Trennschicht für PLA) | K |
| SU-05 | Brim: aus / automatisch / außen, Breite; Raft an/aus | M |
| SU-06 | Hinweis, wenn Orca Überhänge ohne Support erkennt | S |

### 4.5 Platzierung und Druckplatte

| ID | Anforderung | Prio |
| --- | --- | --- |
| PL-01 | 3D-Ansicht des Modells auf der Druckplatte (drehen, zoomen) | M |
| PL-02 | Automatisch ausrichten (Auto-Orient) und auf Fläche legen | M |
| PL-03 | Drehen in 90°-Schritten und frei; Skalieren (%, mm, einheitlich) | M |
| PL-04 | Anzahl Kopien; automatisch anordnen (Arrange) – die CLI hat keinen Arrange-Schritt, daher im Orchestrator | S |
| PL-05 | Mehrere Modelle auf einer Platte kombinieren | S |
| PL-06 | Mehrteilige 3MF: einzelne Platten auswählen | S |

### 4.6 Druckoptionen

| ID | Anforderung | Prio |
| --- | --- | --- |
| DO-01 | Bettnivellierung vor dem Druck an/aus (Makro-Parameter in COSMOS-Startcode) | S |
| DO-02 | Timelapse an/aus | K |
| DO-03 | Voreinstellungen als eigene „Rezepte“ speichern (z. B. „Funktionsteil PETG“) | S |

## 5. Slicing, Vorschau und Prüfung

Vor jedem Druck sieht der Nutzer eine Zusammenfassung und bestätigt aktiv; ohne Bestätigung wird nichts gestartet.

| ID | Anforderung | Prio |
| --- | --- | --- |
| SL-01 | Slicen asynchron anstoßen; Fortschritt und Abbruch in der App | M |
| SL-02 | Zusammenfassung: Vorschaubild, Druckzeit, Filament (g/m) je Lane, Kosten, Schichtanzahl, Maße | M |
| SL-03 | Anzeige der verwendeten Profile und aller geänderten Werte | M |
| SL-04 | Verständliche Fehlermeldung bei Slice-Fehlern (Modell defekt, außerhalb Bauraum, Profil fehlt) | M |
| SL-05 | Einstellung ändern und neu slicen ohne Neustart des Ablaufs | M |
| SL-06 | Schichtansicht (G-Code-Viewer): Schicht-Slider, Farben nach Linientyp, Travel ein/aus, Lane-Farben bei Mehrfarbe | S |
| SL-07 | Viewer lädt vom Server vorverarbeitete Schichtdaten (kompaktes Format, nur sichtbare Schichten) statt Roh-G-Code | S |
| SL-08 | Warnungen aus Orca anzeigen (lose Teile, fehlende Supports, schwebende Bereiche) | S |
| SL-09 | Geslicte Ergebnisse cachen: gleiches Modell + gleiche Einstellungen = kein erneutes Slicen | K |
| SL-10 | G-Code bzw. gcode.3mf exportieren/teilen | K |

## 6. Druckauftrag, Druckeranbindung und Überwachung

Primäre Schnittstelle ist Moonraker, weil der Centauri Carbon unter COSMOS Klipper nutzt; SDCP ist nur für Stock-Firmware nötig.

| ID | Anforderung | Prio |
| --- | --- | --- |
| DR-01 | Drucker einrichten: Name, IP/Host, Typ (Moonraker/SDCP), API-Key, Kamera-URL, Bauraum | M |
| DR-02 | Moonraker: Upload per `/server/files/upload`, Druckstart, Status per WebSocket | M |
| DR-03 | Vor dem Start prüfen: Drucker bereit, Platte leer bestätigt, geladenes Material passt zum Auftrag | M |
| DR-04 | Live-Status: Fortschritt, Restzeit, aktuelle Schicht, Temperaturen, aktive Lane | M |
| DR-05 | Steuerung: Pause, Fortsetzen, Abbrechen (mit Rückfrage) | M |
| DR-06 | Kamerabild (Snapshot, optional Stream) | S |
| DR-07 | Push-Benachrichtigungen: fertig, Fehler, Pause, Filament leer/Lane-Wechsel-Problem | S |
| DR-08 | Warteschlange: Aufträge vormerken, Reihenfolge ändern, nach „Platte geleert“ nächsten starten | K |
| DR-09 | Druckverlauf: Datum, Dauer, Ergebnis, Material, Einstellungen, Foto am Ende | S |
| DR-10 | Einfache Steuerung: Temperaturen setzen, Licht, Lüfter, Filament laden/entladen je Lane (AFC-Makros) | K |
| DR-11 | SDCP-Adapter für Centauri mit Stock-Firmware (Port 3030, HTTP-Upload + WebSocket-Start) | K |
| DR-12 | Home Assistant: Ereignisse per Webhook/MQTT senden (Druckstart, fertig, Fehler) | K |
| DR-13 | iOS Live Activity / Sperrbildschirm-Widget mit Fortschritt | K |

## 7. Profilverwaltung und Synchronisation

Die Desktop-Orca-Profile sind die Quelle der Wahrheit; der Server übernimmt sie und löst die Vererbung auf.

| ID | Anforderung | Prio |
| --- | --- | --- |
| PR-01 | Import der Benutzerprofile (machine, process, filament) aus dem Orca-Ordner des Macs (`~/Library/Application Support/OrcaSlicer/user/…`) | M |
| PR-02 | Sync automatisch per Syncthing oder Git in ein Server-Volume; alternativ Upload eines Preset-Bundles in der App | M |
| PR-03 | `inherits`-Ketten gegen die System-Presets der passenden Orca-Version auflösen, damit die CLI vollständige Profile bekommt | M |
| PR-04 | Kompatibilität prüfen: nur Filament- und Prozessprofile anzeigen, die zum gewählten Drucker und zur Düse passen | M |
| PR-05 | Anzeige in der App mit sprechenden Namen, Gruppierung nach Drucker/Material | M |
| PR-06 | Profile im Browser bearbeiten über linuxserver/orcaslicer; Änderungen landen im selben Volume | K |
| PR-07 | Versionierung: Profilstand je Druckauftrag speichern, damit alte Drucke reproduzierbar sind | S |
| PR-08 | Orca-Version des Servers fest pinnen und mit der Desktop-Version abgleichen (Warnung bei Abweichung) | S |

## 8. Server-Backend und API

Ein Orchestrator-Container stellt die einzige API für die App bereit; der Slice-Dienst ist intern.

**Endpunkte (Entwurf)**

| Bereich | Endpunkte |
| --- | --- |
| Modelle | `POST /models/import` (URL oder Datei), `GET /models`, `GET /models/{id}/files`, `GET /models/{id}/preview` |
| Printables | `GET /printables/search`, `GET /printables/{id}` |
| Profile | `GET /profiles?printer=&nozzle=`, `POST /profiles/sync` |
| Slicing | `POST /slice-jobs`, `GET /slice-jobs/{id}` (Status, Metadaten), `GET /slice-jobs/{id}/layers`, `DELETE /slice-jobs/{id}` |
| Drucker | `GET /printers`, `GET /printers/{id}/status` (inkl. Lanes), `POST /printers/{id}/print`, `POST /printers/{id}/pause\|resume\|cancel` |
| Verlauf | `GET /history`, `POST /history/{id}/reprint` |
| Live | `WS /events` (Slice-Fortschritt, Druckerstatus, Benachrichtigungen) |

**Anforderungen**

| ID | Anforderung | Prio |
| --- | --- | --- |
| BE-01 | Job-Warteschlange mit max. 1 gleichzeitigem Slice-Job (konfigurierbar) | M |
| BE-02 | Metadaten aus G-Code/3MF extrahieren (Zeit, Filament je Lane, Schichten, Thumbnail) | M |
| BE-03 | Schichtdaten für den Viewer in kompaktes Format umrechnen | S |
| BE-04 | Arrange/Kopien/Auto-Orient vor dem CLI-Aufruf | S |
| BE-05 | Speicherbereinigung: alte G-Codes nach X Tagen löschen, Modelle behalten | S |
| BE-06 | Push über APNs oder ntfy/Home Assistant (ohne bezahlten Developer Account kein APNs – siehe Risiken) | S |
| BE-07 | Veröffentlichung als Docker-Image mit Unraid-CA-Template | S |

## 9. Nicht-funktionale Anforderungen

| ID | Bereich | Anforderung |
| --- | --- | --- |
| NF-01 | Performance | Typisches Modell in ≤ 30 s geslict; App bleibt währenddessen bedienbar |
| NF-02 | Ressourcen | Slice-Container mit CPU- und RAM-Limit (Richtwert 4 Kerne, 4–8 GB), damit andere Unraid-Dienste nicht leiden |
| NF-03 | Sicherheit | Zugriff von außen nur per VPN (Tailscale/WireGuard); keine öffentliche Freigabe von Druckstart-Endpunkten |
| NF-04 | Sicherheit | API-Token je Gerät, im iOS-Schlüsselbund gespeichert; Moonraker-Keys nur auf dem Server |
| NF-05 | Sicherheit | Kein Druckstart ohne ausdrückliche Bestätigung in der App |
| NF-06 | Zuverlässigkeit | Verbindungsabbrüche zur App beeinflussen laufende Drucke nicht; Status wird nach Wiederverbindung nachgeladen |
| NF-07 | Wartbarkeit | Orca-Version gepinnt; Upgrade nur nach Test mit Referenzmodellen |
| NF-08 | Wartbarkeit | Printables- und Drucker-Anbindung als austauschbare Adapter |
| NF-09 | Datenschutz | Alles lokal; keine Cloud-Dienste außer optional Printables |
| NF-10 | Verteilung | App ohne bezahlten Apple-Account per Xcode/Sideloading installierbar (7-Tage-Signatur beachten) |
| NF-11 | Sprache | Deutsch zuerst, Englisch vorbereitet (Localizable Strings) |
| NF-12 | Bedienung | Kernablauf „Link teilen → drucken“ in ≤ 5 Schritten |

## 10. Risiken, offene Punkte und Phasen

**Risiken**

| Risiko | Auswirkung | Gegenmaßnahme |
| --- | --- | --- |
| Printables-GraphQL ändert sich oder wird gesperrt | Suche fällt aus | Share-Extension-Weg als Hauptpfad; Adapter kapseln; nur privater Gebrauch |
| Orca-CLI-Verhalten ändert sich zwischen Versionen | Slicing schlägt fehl oder weicht ab | Version pinnen, Referenzmodelle testen |
| Profilvererbung wird falsch aufgelöst | Falsche Temperaturen/Werte | Aufgelöste Profile gegen Desktop-Export prüfen; Werte in SL-03 anzeigen |
| CANVAS/AFC-Daten über Moonraker unvollständig | Kein automatisches Lane-Mapping | Manuelles Mapping als Fallback |
| Kein bezahlter Apple-Account | Kein APNs, Share Extension/Live Activity eingeschränkt, App läuft nach 7 Tagen ab | Push über ntfy oder Home Assistant; Neusignierung einplanen |
| Druckstart aus der Ferne bei belegter Platte | Schaden am Drucker | DR-03-Prüfung, Kamerabild vor Start |

**Offene Punkte**

- [ ] Liefert AFC unter COSMOS Lane-Material und -Farbe über Moonraker, und in welchem Format?
- [ ] Welche Startcode-Parameter (Nivellierung, Lane-Auswahl) unterstützt das COSMOS-Profil?
- [ ] Orca-Desktop oder ElegooSlicer als Profilquelle?
- [ ] Basis: AFKFelix/orca-slicer-api oder escalopa/orcaslicer-api?
- [ ] Name der App

**Phasen**

| Phase | Inhalt | Ergebnis |
| --- | --- | --- |
| 1 – Server-MVP | Slice-Dienst, Profilimport, Moonraker-Upload, Test per Kommandozeile | URL rein → Druck startet |
| 2 – App-MVP | Share Extension, Profil-/Material-/Platten-Auswahl, Zusammenfassung, Start, Status | Kernablauf am iPhone |
| 3 – Komfort | Printables-Suche, G-Code-Viewer, Mehrfarb-Mapping, Verlauf, Push | Bambu-Handy-Niveau |
| 4 – Extras | Warteschlange, Spoolman, Home Assistant, Live Activity, SDCP-Adapter | Ausbau |

**Quellen**

- [AFKFelix/orca-slicer-api](https://github.com/AFKFelix/orca-slicer-api)
- [escalopa/orcaslicer-api](https://github.com/escalopa/orcaslicer-api)
- [linuxserver/docker-orcaslicer](https://github.com/linuxserver/docker-orcaslicer)
- [fabprint (Arrange-Hinweis)](https://pypi.org/project/fabprint/0.1.130/)
- [SimplyPrint Cloud Slicer](https://simplyprint.io/features/slicer)
