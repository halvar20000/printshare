# Beginner audit of the Android app (2026-10-02)

Product principle (CLAUDE.md): *simple by default, powerful when you want it*. This audit walks the path of a
newcomer (e.g. from Reddit) through the Android app in cloud mode – first start → login → add printer → find a model →
prepare → print – and lists every point where someone without technical knowledge might stop. Screens were recorded
in the web build against the real server (cloud mode); the same applies to the iOS app where it has the same flow.

## Status
- **Step 1 done (2026-10-02, Android app):** 2, 3, 4, 5, 6, 7 (order + automatic name; model preselection comes with
  discovery), 8, 10. Welcome screen with "Kostenlos anmelden" + small "Eigener Server? (für Fortgeschrittene)" link;
  card "Erster Schritt: Drucker hinzufügen" on the home screen while a cloud account has no printer; the plate check is
  now the confirmation dialog of "Drucken" ("Ist die Druckplatte leer und PLA geladen? …"), no hidden switch;
  `errorText()`/`friendlyError()` translate the LAN and newer server messages; settings group Spoolman, Manyfold and
  failure detection under "Erweitert"; cloud "Über" text no longer says "no cloud".
- **Step 2 done (2026-10-02):** 1 – "Drucker hinzufügen" searches the Wi-Fi by itself (Centauri by SDCP UDP, Klipper/COSMOS,
  PrusaLink, OctoPrint by a short HTTP probe of the /24); one tap fills type, address (and COSMOS, name). The form opens
  only after a pick or "Adresse selbst eingeben". Native module `mobile/modules/lan-discovery` (Android).
- Open: 9, P3; model preselection for Prusa/OctoPrint (their API needs the password/key first).

## P1 – people get stuck here

| # | Where | Today | Proposal |
|---|---|---|---|
| 1 | Add printer | The **IP address** has to be typed (hint: "steht im Netzwerk-Menü des Druckers"). | **Find printers on the Wi-Fi automatically**: Centauri by UDP broadcast (`M99999`, port 3000), Klipper/PrusaLink/OctoPrint by mDNS (`_moonraker._tcp`, `_octoprint._tcp`, `_http._tcp` with Prusa TXT). List "Centauri Carbon · 192.168.…" → one tap. Typing the address stays as "Adresse selbst eingeben". |
| 2 | After login | Home screen "Was möchtest du drucken?" although there is **no printer yet**; nothing says what to do first. | Right after the first login: "Drucker hinzufügen" as the next step (onboarding), and a card on the home screen while no printer exists. |
| 3 | First start | "Noch nicht verbunden – Verbinde die App einmalig mit deinem PocketPrint3D-**Server**" + "Server verbinden". "Server" scares newcomers. | Welcome screen: "Kostenlos anmelden – nur mit deiner E-Mail" as the big button; "Eigener Server (für Fortgeschrittene)" as a small link. |
| 4 | Review screen | **"Drucken" is greyed out** until the switch "Die Druckplatte ist leer …" is on – the switch is **below the visible area**, so it is not clear why printing doesn't work. | Keep the safety check, but where it is seen: tapping "Drucken" asks "Ist die Druckplatte leer und PLA geladen?" (or the switch right above the button, or a hint on the disabled button). |
| 5 | Error messages | Messages from the printer connections (24 in `lib/lan/*`, e.g. "printer not reachable on the Wi-Fi", "OctoPrint rejected the API key") and newer server messages (Spoolman, Manyfold, Orca Cloud, MakerWorld, failure detection) appear **in English inside the German app**. | Error codes or keys instead of English sentences for the LAN code; extend `friendlyError` for the server messages; each message says what to do next. |

## P2 – understandable, but technical

| # | Where | Today | Proposal |
|---|---|---|---|
| 6 | Wording | "Slicen" (prepare button), "1 von 30 Slices heute", "Geänderte Werte: keine – Profilwerte", "Nur hochladen", "Server" in cloud texts ("Auf dem Server ist kein Drucker eingerichtet", "Server ändern"). | "Druck berechnen", "1 von 30 Drucken heute", "Eigene Änderungen: keine", "Nur an den Drucker senden", cloud texts without "Server". |
| 7 | Add printer form | Name first (grey example "Centauri Carbon" looks filled in, "Speichern" stays grey), "Drucker-…" label cut off, printer-model list with ~1000 entries. | Order: type → find on Wi-Fi → name filled in automatically; model preselected from what was found; full label. |
| 8 | Settings | "Spoolman – nicht verbunden" as its own section (unknown name, sounds like an error); own-server settings next to each other. | "Filament-Spulen" with a neutral "optional"; advanced things (Spoolman, Manyfold, failure detection, profiles) grouped under **"Erweitert"**. |
| 9 | Prepare | Supports "Aus / Normal / Baum" without a hint when they are needed; build plate preselected without explanation. | Short hints ("Stützen brauchst du bei Überhängen – im 3D-Bild zu sehen"; "Welche Platte liegt im Drucker?"). |
| 10 | Home screen | "Safari oder Chrome", "aus Dateien / iCloud" on Android. | Platform-specific wording ("aus dem Browser", "aus deinen Dateien"). |

## P3 – nice to have

| # | Where | Proposal |
|---|---|---|
| 11 | Help | A "Hilfe" entry: where to find the printer's address, the PrusaLink password, what the cloud does, what to do if the printer isn't found. |
| 12 | OctoPrint | OctoPrint's app-key approval flow ("Application Keys" plugin): the app asks, the user clicks "Allow" in OctoPrint – no key copying. |
| 13 | Remote access | Later, with the bridge: a guided, optional step ("Auch unterwegs drucken?"). |

## What already works well for beginners
- Login with an e-mail code (no password), cloud as the preselected tab.
- Search with suggestions, MakerWorld card, Printables login in the app.
- Prepare screen with 3D view; review with time, filament and 2D/3D preview.
- Printer card: clear state, temperatures, pause/cancel.
- Invisible extras: preview images on the printer screen, Klipper times, material library.
