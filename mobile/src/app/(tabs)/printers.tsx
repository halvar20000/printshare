// Live status and control of every printer (DR-04, DR-05, DR-06); details in control/[id] (issue #5).
import Ionicons from "@expo/vector-icons/Ionicons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, RefreshControl, Text, View } from "react-native";

import { BookingCard, bookedText } from "@/components/bookings";
import { CameraImage } from "@/components/camera";
import { WatchInfo } from "@/components/watch";

import { Badge, Banner, Button, Card, Empty, ProgressBar, Screen } from "@/components/ui";
import { errorText, type Printer, type PrinterStatus } from "@/lib/api";
import { useApp } from "@/lib/app";
import { duration, temp } from "@/lib/format";
import { NoAddressError, printerControl, printerStatus } from "@/lib/printerAccess";
import { slots } from "@/lib/lanes";
import { settleBookings, type Booking } from "@/lib/spoolman";
import { space, useColors } from "@/lib/theme";

type Entry = { printer: Printer; status: PrinterStatus | null; error?: string; noAddress?: boolean };

export default function Printers() {
  const { api, server, t } = useApp();
  const cloud = !!server?.cloud;
  const c = useColors();
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [acting, setActing] = useState<string>("");
  const [cams, setCams] = useState<Record<string, boolean>>({});
  const [starting, setStarting] = useState<Record<string, number>>({});   // issue #9: switched on at (ms)
  const [now, setNow] = useState(() => Date.now());
  // Spoolman (MA-07): prints that ended are booked; unclear ones wait for the user's decision
  const [openBookings, setOpenBookings] = useState<Booking[]>([]);
  const [booked, setBooked] = useState<{ text: string; at: number }[]>([]);
  const router = useRouter();

  // which printers have a camera (asked once per visit, not with every status refresh)
  useFocusEffect(useCallback(() => {
    if (!api) return;
    let alive = true;
    api.printers().then(ps => ps.forEach(p => api.cameraInfo(p.id)
      .then(i => { if (alive) setCams(c => ({ ...c, [p.id]: i.available })); })
      .catch(() => {}))).catch(() => {});
    return () => { alive = false; };
  }, [api]));

  const load = useCallback(async () => {
    if (!api) return;
    try {
      const ps = await api.printers();
      const list = await Promise.all(ps.map(async p => {
        // cloud: the app asks the printer itself on the home Wi-Fi
        try { return { printer: p, status: await printerStatus(api, server!, p) }; }
        catch (e) { return { printer: p, status: null, error: errorText(t, e), noAddress: e instanceof NoAddressError }; }
      }));
      setEntries(list);
      setNow(Date.now());
      setError("");
      const res = await settleBookings(server!, Object.fromEntries(list.map(e => [e.printer.id, e.status])));
      setOpenBookings(res.open);
      if (res.booked.length) setBooked(b => [...b, ...res.booked.map(x => ({ text: bookedText(t, x), at: Date.now() }))]);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [api, server, t]);

  useFocusEffect(useCallback(() => {
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, [load]));

  const powerOn = async (p: Printer) => {
    if (!api) return;
    setActing(`${p.id}:power`);
    try {
      await api.setPower(p.id, true);
      setStarting(st => ({ ...st, [p.id]: Date.now() }));
    } catch (e) { setError((e as Error).message); }
    finally { setActing(""); setTimeout(load, 3000); }
  };

  const muteWatch = async (p: Printer) => {
    if (!api) return;
    setActing(`${p.id}:mute`);
    try { await api.muteWatch(p.id); } catch (e) { setError((e as Error).message); }
    finally { setActing(""); setTimeout(load, 500); }
  };

  const control = async (p: Printer, action: "pause" | "resume" | "cancel") => {
    if (!api) return;
    const run = async () => {
      setActing(`${p.id}:${action}`);
      try { await printerControl(api, server!, p, action); }
      catch (e) { setError(errorText(t, e)); }
      finally { setActing(""); setTimeout(load, 800); }
    };
    if (action !== "cancel") return run();
    const q = t("cancelPrintQ", { printer: p.name });
    if (Platform.OS === "web") { if (globalThis.confirm?.(q)) run(); return; }
    Alert.alert(t("cancelPrint"), q, [
      { text: t("cancelBtn"), style: "cancel" },
      { text: t("cancelPrint"), style: "destructive", onPress: run },
    ]);
  };

  return (
    <Screen refreshControl={<RefreshControl refreshing={refreshing} tintColor={c.accent}
      onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
      {error ? <Banner kind="error" text={error} /> : null}
      {booked.filter(b => now - b.at < 60000).map(b => <Banner key={b.at + b.text} kind="ok" icon="disc-outline" text={b.text} />)}
      {server ? openBookings.map(b => <BookingCard key={b.id} server={server} booking={b} onDone={load} />) : null}
      {entries && !entries.length ? (
        <Empty icon="print-outline" title={t("noPrinters")} sub={cloud ? t("noPrintersCloud") : undefined}>
          {cloud ? <Button title={t("addPrinter")} icon="add" onPress={() => router.push({ pathname: "/cloud-printer/[id]", params: { id: "new" } })} /> : null}
        </Empty>
      ) : null}
      {(entries ?? []).map(({ printer: p, status: s, noAddress }) => {
        const kind = s ? s.kind : "offline";
        const busy = kind === "active" || kind === "paused";
        let label = t.table.printerKinds[kind];
        const raw = (s?.state ?? "").toLowerCase();
        if (kind === "active" && raw && raw !== "printing") label += ` · ${t.table.rawStates[raw] ?? raw}`;
        const badge = kind === "offline" || kind === "error" ? "error" : kind === "paused" ? "warn" : busy ? "accent" : "ok";
        const pct = s?.progress ?? 0;
        // printers that report it (PrusaLink, OctoPrint) know better than the estimate from progress
        const left = !busy ? null : s?.time_remaining_s != null ? s.time_remaining_s
          : s?.print_duration_s && pct > 1 ? (s.print_duration_s * (100 - pct)) / pct : null;
        return (
          <Card key={p.id} style={{ padding: space, marginBottom: 16 }}>
            <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 12 }}>
              <Ionicons name="print" size={24} color={c.accent} style={{ marginRight: 10 }} />
              <Text style={{ color: c.text, fontSize: 19, fontWeight: "700", flex: 1 }} numberOfLines={1}>{p.name}</Text>
              <Badge text={label} kind={badge} />
            </View>
            {busy && s ? (
              <>
                <Text style={{ color: c.text, fontSize: 15, marginBottom: 8 }} numberOfLines={1}>{s.file ?? "–"}</Text>
                <ProgressBar value={pct} />
                <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 6 }}>
                  <Text style={{ color: c.text, fontWeight: "600" }}>{pct.toFixed(0)} %</Text>
                  <Text style={{ color: c.sub }}>
                    {[s.layers ? `${t("layer")} ${s.layer ?? "–"}/${s.layers}` : null,
                      left ? `${t("remaining")} ~${duration(left)}` : null].filter(Boolean).join(" · ")}
                  </Text>
                </View>
              </>
            ) : null}
            {s ? (
              <View style={{ flexDirection: "row", gap: 24, marginTop: busy ? 14 : 0 }}>
                <View><Text style={{ color: c.sub, fontSize: 13 }}>{t("nozzle")}</Text>
                  <Text style={{ color: c.text, fontSize: 16, fontWeight: "600" }}>{temp(s.nozzle, s.nozzle_target)}</Text></View>
                <View><Text style={{ color: c.sub, fontSize: 13 }}>{t("bed")}</Text>
                  <Text style={{ color: c.text, fontSize: 16, fontWeight: "600" }}>{temp(s.bed, s.bed_target)}</Text></View>
              </View>
            ) : noAddress ? (
              <>
                <Text style={{ color: c.sub, fontSize: 15 }}>{t("needLanAddress")}</Text>
                <Button kind="secondary" title={t("lanAddress")} icon="wifi-outline" style={{ marginTop: 12 }}
                  onPress={() => router.push({ pathname: "/cloud-printer/[id]", params: { id: p.id } })} />
              </>
            ) : (
              <Text style={{ color: c.sub, fontSize: 15 }}>{t(cloud ? "errPrinterOfflineLan" : "errPrinterOffline")}</Text>
            )}
            {s?.lanes?.length ? (
              // filament lanes of an AFC unit (CANVAS on COSMOS), spec MA-02
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 14 }}>
                {slots(s.lanes).map(l => (
                  <View key={l.id} style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 6,
                    borderRadius: 999, backgroundColor: c.input, opacity: l.loaded ? 1 : 0.5,
                    borderWidth: l.in_toolhead ? 2 : 0, borderColor: c.accent }}>
                    <View style={{ width: 14, height: 14, borderRadius: 7, backgroundColor: l.color || c.track, marginRight: 6,
                      borderWidth: 1, borderColor: c.line }} />
                    <Text style={{ color: c.text, fontSize: 13 }}>
                      {`${l.slot} · ${l.loaded ? l.material ?? "?" : t("laneEmpty")}`}
                    </Text>
                  </View>
                ))}
              </View>
            ) : null}
            {s?.watch ? (
              <WatchInfo printer={p.id} watch={s.watch} busy={acting} onMute={() => muteWatch(p)}
                onPause={() => control(p, "pause")} />
            ) : null}
            {busy ? (
              <View style={{ flexDirection: "row", gap: 10, marginTop: 16 }}>
                {kind === "paused"
                  ? <Button title={t("resume")} icon="play" onPress={() => control(p, "resume")} style={{ flex: 1 }}
                      loading={acting === `${p.id}:resume`} />
                  : <Button kind="secondary" title={t("pause")} icon="pause" onPress={() => control(p, "pause")} style={{ flex: 1 }}
                      loading={acting === `${p.id}:pause`} />}
                <Button kind="danger" title={t("cancelBtn")} icon="stop" onPress={() => control(p, "cancel")} style={{ flex: 1 }}
                  loading={acting === `${p.id}:cancel`} />
              </View>
            ) : null}
            {!s && p.power ? (
              // issue #9: printer off -> switch its smart plug on; it needs ~30-60 s to answer
              now - (starting[p.id] ?? 0) < 120000 ? (
                <View style={{ flexDirection: "row", alignItems: "center", marginTop: 14 }}>
                  <ActivityIndicator color={c.accent} />
                  <Text style={{ color: c.sub, fontSize: 15, marginLeft: 10 }}>{t("powerStarting")}</Text>
                </View>
              ) : (
                <>
                  {starting[p.id] ? <Text style={{ color: c.sub, fontSize: 14, marginTop: 10 }}>{t("powerSlow")}</Text> : null}
                  <Button title={t("powerOn")} icon="power" style={{ marginTop: 14 }} onPress={() => powerOn(p)}
                    loading={acting === `${p.id}:power`} />
                </>
              )
            ) : null}
            {s && !cloud ? (
              <Button kind="secondary" title={t("control")} icon="options-outline" style={{ marginTop: 14 }}
                onPress={() => router.push({ pathname: "/control/[id]", params: { id: p.id, name: p.name } })} />
            ) : null}
            {cams[p.id] ? (
              <Pressable onPress={() => router.push({ pathname: "/camera/[id]", params: { id: p.id, name: p.name } })}
                accessibilityRole="button" accessibilityLabel={t("camera")} style={{ marginTop: 14 }}>
                <CameraImage printer={p.id} width={640} intervalMs={5000}
                  style={{ width: "100%", aspectRatio: 16 / 9, borderRadius: 12 }} />
                <View style={{ position: "absolute", right: 8, bottom: 8, flexDirection: "row", alignItems: "center",
                  backgroundColor: "rgba(0,0,0,0.55)", borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 }}>
                  <Ionicons name="expand-outline" size={14} color="#fff" />
                  <Text style={{ color: "#fff", fontSize: 12, marginLeft: 4 }}>{t("camera")}</Text>
                </View>
              </Pressable>
            ) : null}
          </Card>
        );
      })}
    </Screen>
  );
}
