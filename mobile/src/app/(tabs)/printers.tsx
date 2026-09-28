// Live status and control of every printer (DR-04, DR-05, DR-06).
import Ionicons from "@expo/vector-icons/Ionicons";
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Linking, Platform, RefreshControl, Text, View } from "react-native";

import { Badge, Banner, Button, Card, Empty, ProgressBar, Screen } from "@/components/ui";
import type { Printer, PrinterStatus } from "@/lib/api";
import { useApp } from "@/lib/app";
import { duration, temp } from "@/lib/format";
import { space, useColors } from "@/lib/theme";

type Entry = { printer: Printer; status: PrinterStatus | null; error?: string };

export default function Printers() {
  const { api, t } = useApp();
  const c = useColors();
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [acting, setActing] = useState<string>("");

  const load = useCallback(async () => {
    if (!api) return;
    try {
      const ps = await api.printers();
      const list = await Promise.all(ps.map(async p => {
        try { return { printer: p, status: await api.status(p.id) }; }
        catch (e) { return { printer: p, status: null, error: (e as Error).message }; }
      }));
      setEntries(list);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [api]);

  useFocusEffect(useCallback(() => {
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, [load]));

  const control = async (p: Printer, action: "pause" | "resume" | "cancel") => {
    if (!api) return;
    const run = async () => {
      setActing(`${p.id}:${action}`);
      try { await api.control(p.id, action); }
      catch (e) { setError((e as Error).message); }
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
      {entries && !entries.length ? <Empty icon="print-outline" title={t("noPrinters")} /> : null}
      {(entries ?? []).map(({ printer: p, status: s }) => {
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
            ) : (
              <Text style={{ color: c.sub, fontSize: 15 }}>{t("errPrinterOffline")}</Text>
            )}
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
            {s?.camera ? (
              <Button kind="plain" title={t("camera")} icon="videocam-outline" onPress={() => Linking.openURL(s.camera!)}
                style={{ marginTop: 6 }} />
            ) : null}
          </Card>
        );
      })}
    </Screen>
  );
}
