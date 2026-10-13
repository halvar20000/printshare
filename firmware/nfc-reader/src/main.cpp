// PocketPrint3D NFC reader (step 3 of the NFC spools, server 0.38.0+): an ESP32 with a PN5180 at the spool holder
// reports the chip of the spool in its slot to POST <server>/api/reader/scan {"slot", "uid"} with the printer's reader
// key. Reads ISO 15693 (OpenPrintTag, ICODE stickers) and ISO 14443A (NTAG stickers, Bambu MIFARE tags) - the chip
// number only, byte order as Android reports it (the app links chips by the same number).
//
// First start: Wi-Fi "PocketPrint3D-NFC" opens a setup page (Wi-Fi, reader address + key from the app, slot).
// Hold BOOT for 3 s to open it again. Status page: http://<reader IP>/
#include <Arduino.h>
#include <HTTPClient.h>
#include <PN5180.h>
#include <PN5180ISO15693.h>
#include <Preferences.h>
#include <SPI.h>
#include <WebServer.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WiFiManager.h>

#include "certs.h"
#include "iso14443a.h"

#define FW_VERSION "1.0.0"
#ifndef BOOT_PIN
#define BOOT_PIN 0
#endif

PN5180ISO15693 nfc15693(PN_NSS, PN_BUSY, PN_RST);
PN5180TypeA nfc14443(PN_NSS, PN_BUSY, PN_RST);
Preferences prefs;
WebServer web(80);

String cfgUrl, cfgKey;
int cfgSlot = 0;

String candidate, reported, lastResult = "-", lastUid = "-";
int stable = 0;
unsigned long lastSeen = 0, lastFail = 0, bootHeld = 0;
bool readerOk = false;

// ---------- status LED (the S3 DevKit's RGB LED; nothing on boards without one) ----------
void led(uint8_t r, uint8_t g, uint8_t b) {
#ifdef RGB_BUILTIN
  neopixelWrite(RGB_BUILTIN, r, g, b);
#endif
}

// ---------- settings ----------
void loadConfig() {
  prefs.begin("pp3d", true);
  cfgUrl = prefs.getString("url", "");
  cfgKey = prefs.getString("key", "");
  cfgSlot = prefs.getInt("slot", 0);
  prefs.end();
}

void saveConfig(const String &url, const String &key, int slot) {
  prefs.begin("pp3d", false);
  prefs.putString("url", url);
  prefs.putString("key", key);
  prefs.putInt("slot", slot);
  prefs.end();
  cfgUrl = url; cfgKey = key; cfgSlot = slot;
}

void configPortal(bool force) {
  led(0, 0, 40);
  WiFiManager wm;
  char slotBuf[8];
  snprintf(slotBuf, sizeof slotBuf, "%d", cfgSlot);
  WiFiManagerParameter pUrl("url", "Reader address (from the app)", cfgUrl.c_str(), 200);
  WiFiManagerParameter pKey("key", "Reader key (pp3dr_...)", cfgKey.c_str(), 80);
  WiFiManagerParameter pSlot("slot", "Slot (0 = the only one; Bambu external 254)", slotBuf, 4);
  wm.addParameter(&pUrl);
  wm.addParameter(&pKey);
  wm.addParameter(&pSlot);
  wm.setTitle("PocketPrint3D NFC reader");
  wm.setConfigPortalTimeout(force ? 600 : 0);
  bool ok = force ? wm.startConfigPortal("PocketPrint3D-NFC") : wm.autoConnect("PocketPrint3D-NFC");
  String url = String(pUrl.getValue()); url.trim();
  String key = String(pKey.getValue()); key.trim();
  if (url.length() && !url.startsWith("http")) url = "http://" + url;
  if (url.length() && url.indexOf("/api/reader/scan") < 0) url += (url.endsWith("/") ? "" : "/") + String("api/reader/scan");
  saveConfig(url, key, atoi(pSlot.getValue()));
  if (!ok) ESP.restart();
}

// ---------- reading ----------
String hex(const uint8_t *b, int n) {
  static const char *d = "0123456789ABCDEF";
  String s;
  for (int i = 0; i < n; i++) { s += d[b[i] >> 4]; s += d[b[i] & 15]; }
  return s;
}

// one round: ISO 15693 first (OpenPrintTag), then ISO 14443A; "" = no chip
String readChip() {
  uint8_t uid[10];
  nfc15693.reset();
  nfc15693.setupRF();
  if (nfc15693.getInventory(uid) == ISO15693_EC_OK) return hex(uid, 8);   // as received = Android's NfcV id
  nfc14443.reset();
  nfc14443.setupRF();
  uint8_t n = nfc14443.readUid(uid);
  if (n == 4 || n == 7 || n == 10) return hex(uid, n);                     // UID0 first = Android's NfcA id
  return "";
}

// ---------- reporting ----------
bool report(const String &uid) {
  if (cfgUrl.isEmpty() || cfgKey.isEmpty() || WiFi.status() != WL_CONNECTED) { lastResult = "not set up / no Wi-Fi"; return false; }
  HTTPClient http;
  WiFiClientSecure tls;
  WiFiClient plain;
  bool https = cfgUrl.startsWith("https://");
  if (https) tls.setCACert(ROOT_CA);
  if (!(https ? http.begin(tls, cfgUrl) : http.begin(plain, cfgUrl))) { lastResult = "bad address"; return false; }
  http.setTimeout(15000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", "Bearer " + cfgKey);
  http.setUserAgent("PocketPrint3D-NFC/" FW_VERSION);
  int code = http.POST("{\"slot\":" + String(cfgSlot) + ",\"uid\":\"" + uid + "\"}");
  String body = code > 0 ? http.getString() : http.errorToString(code);
  http.end();
  lastResult = String(code) + " " + body.substring(0, 160);
  Serial.printf("report %s -> %s\n", uid.c_str(), lastResult.c_str());
  if (code == 200) {
    bool known = body.indexOf("\"known\":true") >= 0;
    known ? led(0, 40, 0) : led(40, 30, 0);          // green = spool known, yellow = new chip: link it in the app
    return true;
  }
  led(40, 0, 0);
  return code == 400 || code == 401 || code == 403;   // wrong key / slot: retrying won't help
}

// ---------- status page ----------
void page() {
  String h = "<!doctype html><meta name=viewport content='width=device-width'><title>PocketPrint3D NFC</title>"
             "<body style='font-family:sans-serif;max-width:560px;margin:20px auto;padding:0 16px'>"
             "<h2>PocketPrint3D NFC reader</h2><table cellpadding=4>";
  h += "<tr><td>Version</td><td>" FW_VERSION "</td></tr>";
  h += "<tr><td>PN5180</td><td>" + String(readerOk ? "found" : "NOT FOUND - check the wiring") + "</td></tr>";
  h += "<tr><td>Reports to</td><td>" + (cfgUrl.isEmpty() ? String("-") : cfgUrl) + "</td></tr>";
  h += "<tr><td>Slot</td><td>" + String(cfgSlot) + "</td></tr>";
  h += "<tr><td>Chip now</td><td>" + (reported.isEmpty() ? String("none") : reported) + "</td></tr>";
  h += "<tr><td>Last chip</td><td>" + lastUid + "</td></tr>";
  h += "<tr><td>Last answer</td><td>" + lastResult + "</td></tr></table>";
  h += "<p style='color:#666'>Settings: hold the BOOT button for 3 seconds, then join the Wi-Fi \"PocketPrint3D-NFC\".</p>";
  web.send(200, "text/html; charset=utf-8", h);
}

void setup() {
  Serial.begin(115200);
  pinMode(BOOT_PIN, INPUT_PULLUP);
  led(0, 0, 40);
  loadConfig();
  SPI.begin(PN_SCK, PN_MISO, PN_MOSI, PN_NSS);
  nfc15693.begin();
  nfc15693.reset();
  uint8_t ver[2] = {0, 0};
  nfc15693.readEEprom(FIRMWARE_VERSION, ver, sizeof ver);
  readerOk = ver[1] != 0 && ver[1] != 0xFF;
  Serial.printf("PocketPrint3D NFC %s, PN5180 firmware %d.%d %s\n", FW_VERSION, ver[1], ver[0], readerOk ? "" : "(not found!)");
  WiFi.mode(WIFI_STA);
  configPortal(cfgUrl.isEmpty() || cfgKey.isEmpty());
  web.on("/", page);
  web.begin();
  Serial.printf("Wi-Fi %s, IP %s, reporting slot %d to %s\n", WiFi.SSID().c_str(), WiFi.localIP().toString().c_str(),
                cfgSlot, cfgUrl.c_str());
  led(0, 0, 0);
}

void loop() {
  web.handleClient();
  // BOOT held 3 s: settings again
  if (digitalRead(BOOT_PIN) == LOW) {
    if (!bootHeld) bootHeld = millis();
    else if (millis() - bootHeld > 3000) { configPortal(true); bootHeld = 0; }
  } else bootHeld = 0;

  String uid = readChip();
  unsigned long now = millis();
  if (uid.length()) {
    lastSeen = now;
    lastUid = uid;
    stable = uid == candidate ? stable + 1 : 1;
    candidate = uid;
    // the same chip twice in a row, not reported yet (retry a failed report after 10 s)
    if (stable >= 2 && uid != reported && (!lastFail || now - lastFail > 10000)) {
      if (report(uid)) { reported = uid; lastFail = 0; } else lastFail = now;
    }
  } else if (now - lastSeen > 4000 && reported.length()) {
    reported = ""; candidate = ""; stable = 0;   // spool taken out: the next one (or the same again) is reported
    led(0, 0, 0);
  }
  delay(250);
}
