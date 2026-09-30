// Slicing progress -> review -> explicit confirmation -> print / upload (spec 5, NF-05, DR-03).
import Ionicons from "@expo/vector-icons/Ionicons";
import * as Haptics from "expo-haptics";
import { useKeepAwake } from "expo-keep-awake";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, Switch, Text, View } from "react-native";

import { Banner, Button, Card, Divider, Empty, PickerSheet, Row, Screen, Section, Stat, tap } from "@/components/ui";
import { friendlyError, type Job, type PrinterKind, type PrinterStatus } from "@/lib/api";
import { useApp } from "@/lib/app";
import { getItem, setItem } from "@/lib/storage";
import { jobName, plateName, printTime, shortName } from "@/lib/format";
import { defaultSlots, fits, slots } from "@/lib/lanes";
import { translateLog, type T } from "@/lib/i18n";
import { useColors } from "@/lib/theme";

const BUSY: PrinterKind[] = ["active", "paused"];

function changedValues(t: T, o: Record<string, string>): string[] {
  const out: string[] = [];
  if (o.enable_support === "0") out.push(`${t("supports")}: ${t("supOff")}`);
  else if (o.enable_support === "1") out.push(`${t("supports")}: ${t(o.support_type?.startsWith("tree") ? "supTree" : "supNormal")}`);
  const brim = ({ auto_brim: "brimAuto", no_brim: "brimOff", outer_only: "brimOuter" } as const)[o.brim_type as "auto_brim"];
  if (brim) out.push(`${t("brim")}: ${t(brim)}`);
  if (o.sparse_infill_density) out.push(`${t("infill")}: ${o.sparse_infill_density.replace("%", " %")}`);
  if (o.wall_loops) out.push(`${t("walls")}: ${o.wall_loops}`);
  return out;
}

function confirmAsync(title: string, ok: string, cancel: string): Promise<boolean> {
  if (Platform.OS === "web") return Promise.resolve(globalThis.confirm?.(title) ?? true);
  return new Promise(resolve => Alert.alert(title, undefined, [
    { text: cancel, style: "cancel", onPress: () => resolve(false) },
    { text: ok, onPress: () => resolve(true) },
  ], { cancelable: true, onDismiss: () => resolve(false) }));
}

export default function JobScreen() {
  const { id, slots: slotsParam } = useLocalSearchParams<{ id: string; slots?: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const [job, setJob] = useState<Job | null>(null);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [plateOk, setPlateOk] = useState(false);
  const [sending, setSending] = useState<"print" | "upload" | null>(null);
  const [printerNames, setPrinterNames] = useState<Record<string, string>>({});
  const [levelingDefault, setLevelingDefault] = useState<Record<string, boolean | null>>({});
  const [leveling, setLeveling] = useState<boolean | null>(null);
  const [pstatus, setPstatus] = useState<PrinterStatus | "offline" | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [startedAt] = useState(() => Date.now());

  const working = job?.state === "slicing" || job?.state === "running" || job?.state === "sending";
  useKeepAwake(working ? "job" : undefined, { suppressDeactivateWarnings: true });

  const load = useCallback(async () => {
    if (!api) return null;
    try {
      const j = await api.job(id);
      setJob(j);
      setLoadError("");
      return j;
    } catch (e) {
      setLoadError((e as Error).message);
      return null;
    }
  }, [api, id]);

  // poll while the server is working
  useEffect(() => {
    let alive = true, timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const j = await load();
      if (!alive) return;
      if (!j || ["slicing", "running", "sending"].includes(j.state)) timer = setTimeout(tick, 1000);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [load, sending]);

  useEffect(() => {
    if (!working) return;
    const iv = setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(iv);
  }, [working, startedAt]);

  useEffect(() => {
    api?.printers().then(ps => {
      setPrinterNames(Object.fromEntries(ps.map(p => [p.id, p.name])));
      setLevelingDefault(Object.fromEntries(ps.map(p => [p.id, p.leveling ?? null])));
    }).catch(() => {});
  }, [api]);

  // DR-03: is the printer free?
  const printerId = job?.result?.printer ?? job?.printer;

  // DO-01: bed leveling per print, only for printers that can switch it; last choice per printer
  const canLevel = printerId != null && levelingDefault[printerId] != null;
  useEffect(() => {
    if (!printerId || !canLevel) return;
    getItem(`ps_level_${printerId}`).then(v => setLeveling(v === "1" ? true : v === "0" ? false : null));
  }, [printerId, canLevel]);
  const levelingOn = canLevel ? (leveling ?? levelingDefault[printerId!] ?? true) : null;
  const changeLeveling = (v: boolean) => {
    tap();
    setLeveling(v);
    if (printerId) setItem(`ps_level_${printerId}`, v ? "1" : "0");
  };
  const refreshPrinter = useCallback(() => {
    if (!api || !printerId) return;
    api.status(printerId).then(setPstatus).catch(() => setPstatus("offline"));
  }, [api, printerId]);
  useEffect(() => {
    if (job?.state !== "sliced" && job?.state !== "uploaded") return;
    refreshPrinter();
    const iv = setInterval(refreshPrinter, 10000);
    return () => clearInterval(iv);
  }, [job?.state, refreshPrinter]);

  // Lane selection (issue #6): which slot of the printer prints each filament of the model;
  // the slots chosen while preparing (issue #12) are the default, changeable without re-slicing.
  const printerLanes = useMemo(() => slots(pstatus && pstatus !== "offline" ? pstatus.lanes : []), [pstatus]);
  const colours = useMemo(() => {
    const r = job?.result;
    if (!r) return [];
    return r.filaments && r.filaments.length > 1 ? r.filaments
      : [{ index: 1, color: null as string | null, preset: r.profiles?.filament ?? "", grams: r.filament_g }];
  }, [job?.result]);
  const [laneChoice, setLaneChoice] = useState<Record<number, number>>(() => {
    try { return slotsParam ? JSON.parse(slotsParam) : {}; } catch { return {}; }
  });
  const [laneSheet, setLaneSheet] = useState<number | null>(null);
  const laneFor = useMemo(() => {
    const known = Object.fromEntries(Object.entries(laneChoice)
      .filter(([, tool]) => printerLanes.some(l => l.tool === tool)).map(([k, v]) => [Number(k), v]));
    return defaultSlots(colours, printerLanes, known);
  }, [colours, printerLanes, laneChoice]);
  const laneWarnings = useMemo(() => {
    const out: { text: string; blocking: boolean }[] = [];
    for (const c of colours) {
      const lane = printerLanes.find(l => l.tool === laneFor[c.index]);
      if (!lane) continue;
      const what = colours.length > 1 ? t("colorN", { n: c.index }) : t("lane");
      if (!lane.loaded) out.push({ text: t("laneEmptyWarn", { what, lane: lane.slot }), blocking: true });
      else if (!fits(c.preset, lane)) {
        out.push({ text: t("laneMaterialWarn", { what, want: shortName(c.preset), lane: lane.slot, have: lane.material ?? "" }),
          blocking: false });
      }
    }
    return out;
  }, [colours, printerLanes, laneFor, t]);

  const send = async (start: boolean) => {
    if (!api || !job) return;
    const pname = printerNames[printerId ?? ""] ?? printerId ?? "";
    if (start && !(await confirmAsync(t("confirmStartQ", { printer: pname }), t("start"), t("cancelBtn")))) return;
    setActionError("");
    setSending(start ? "print" : "upload");
    try {
      await api.send(job.id, start, start && levelingOn != null ? levelingOn : undefined,
        printerLanes.length ? laneFor : undefined);
      let j: Job | null = null;
      for (let i = 0; i < 600; i++) {
        await new Promise(r => setTimeout(r, 1000));
        j = await api.job(job.id);
        if (j.state !== "sending") break;
      }
      if (j) setJob(j);
      if (j?.error) setActionError(friendlyError(t, 0, j.error));
      else if (Platform.OS !== "web") Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    } catch (e) {
      setActionError((e as Error).message);
      refreshPrinter();
    } finally {
      setSending(null);
    }
  };

  const editSettings = () => {
    if (!job) return;
    const r = job.request;
    router.replace({ pathname: "/prepare", params: {
      link: r.link,
      fileName: r.link.startsWith("upload:") ? job.result?.source_file ?? undefined : undefined,
      edit: JSON.stringify({ printer: r.printer ?? job.printer, file: r.file, options: r.options,
        name: job.result?.source_file, slots: printerLanes.length ? laneFor : undefined }),
    } });
  };

  const del = async () => {
    if (!api || !job) return;
    if (!(await confirmAsync(t("deleteJobQ"), t("del"), t("cancelBtn")))) return;
    try {
      await api.deleteJob(job.id);
      router.back();
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  if (!job) {
    return (
      <View style={{ flex: 1, backgroundColor: c.bg, justifyContent: "center" }}>
        {loadError ? <Empty icon="cloud-offline-outline" title={loadError}>
          <Button title={t("tryAgain")} kind="secondary" onPress={load} />
        </Empty> : <ActivityIndicator color={c.accent} size="large" />}
      </View>
    );
  }

  const r = job.result;
  const name = jobName(r?.source_file, job.request.link);

  // ---------- slicing ----------
  if (job.state === "slicing" || job.state === "running") {
    const last = job.log.length ? translateLog(t, job.log[job.log.length - 1]) : t("slicing");
    return (
      <Screen footer={<Button kind="secondary" title={t("keepRunning")} onPress={() => router.back()} />}>
        <View style={{ alignItems: "center", paddingVertical: 40 }}>
          <ActivityIndicator size="large" color={c.accent} />
          <Text style={{ color: c.text, fontSize: 22, fontWeight: "700", marginTop: 20 }}>{t("slicing")}</Text>
          <Text style={{ color: c.sub, fontSize: 15, marginTop: 6, textAlign: "center" }}>{name}</Text>
          <Text style={{ color: c.sub, fontSize: 15, marginTop: 18 }}>{last}</Text>
          <Text style={{ color: c.sub, fontSize: 13, marginTop: 4 }}>{elapsed} s · {t("slicingSub")}</Text>
        </View>
        <Card style={{ padding: 16 }}>
          {job.log.map((l, i) => (
            <View key={i} style={{ flexDirection: "row", alignItems: "center", paddingVertical: 4 }}>
              <Ionicons name={i < job.log.length - 1 ? "checkmark-circle" : "ellipse-outline"} size={18}
                color={i < job.log.length - 1 ? c.ok : c.accent} style={{ marginRight: 10 }} />
              <Text style={{ color: c.text, fontSize: 15, flex: 1 }}>{translateLog(t, l)}</Text>
            </View>
          ))}
        </Card>
      </Screen>
    );
  }

  // ---------- error (SL-04) ----------
  if (job.state === "error") {
    return (
      <Screen footer={<>
        <Button title={t("editSettings")} icon="options-outline" onPress={editSettings} />
        <Button kind="plain" title={t("deleteJob")} onPress={del} />
      </>}>
        <Empty icon="alert-circle-outline" title={t("errorTitle")} sub={friendlyError(t, 0, job.error ?? "")} />
        <Pressable onPress={() => { tap(); setShowLog(v => !v); }} style={{ alignSelf: "center" }}>
          <Text style={{ color: c.accent, fontSize: 15 }}>{t("showDetails")}</Text>
        </Pressable>
        {showLog ? <Card style={{ padding: 14, marginTop: 12 }}>
          <Text style={{ color: c.sub, fontSize: 13, fontFamily: Platform.select({ ios: "Menlo", default: "monospace" }) }}>
            {[...job.log, job.error].filter(Boolean).join("\n")}
          </Text>
        </Card> : null}
      </Screen>
    );
  }

  // ---------- review / sent ----------
  const p = r?.profiles ?? {};
  const changed = changedValues(t, r?.overrides ?? {});
  const pname = printerNames[printerId ?? ""] ?? printerId ?? "";
  const done = job.state === "started";
  const kind = pstatus === "offline" ? "offline" : pstatus?.kind;
  const busy = !!kind && BUSY.includes(kind as PrinterKind);
  const canPrint = plateOk && !busy && kind !== "offline" && !sending && !laneWarnings.some(w => w.blocking);
  const laneLabel = (tool?: number) => {
    const l = printerLanes.find(x => x.tool === tool);
    if (!l) return "–";
    return [l.slot, l.loaded ? l.material : t("laneEmpty")].filter(Boolean).join(" · ");
  };

  const footer = done ? (
    <>
      <Button title={t("toPrinter")} icon="print-outline" onPress={() => router.navigate("/printers")} />
      <Button kind="secondary" title={t("camera")} icon="videocam-outline"
        onPress={() => printerId && router.push({ pathname: "/camera/[id]", params: { id: printerId, name: printerNames[printerId] } })} />
      <Button kind="secondary" title={t("newModel")} onPress={() => router.navigate("/")} />
    </>
  ) : (
    <>
      <Button title={t("print")} icon="play" onPress={() => send(true)} disabled={!canPrint}
        loading={sending === "print" || job.state === "sending"} />
      {job.state !== "uploaded" ? (
        <Button kind="secondary" title={t("uploadOnly")} icon="cloud-upload-outline" onPress={() => send(false)}
          disabled={!!sending || job.state === "sending"} loading={sending === "upload"} />
      ) : null}
    </>
  );

  return (
    <Screen footer={footer}>
      {done || job.state === "uploaded" ? (
        <View style={{ alignItems: "center", paddingVertical: 20 }}>
          <Ionicons name={done ? "checkmark-circle" : "cloud-done"} size={64} color={c.ok} />
          <Text style={{ color: c.text, fontSize: 22, fontWeight: "700", marginTop: 10 }}>{t(done ? "startedTitle" : "uploadedTitle")}</Text>
          <Text style={{ color: c.sub, fontSize: 15, marginTop: 6, textAlign: "center" }}>{t(done ? "startedSub" : "uploadedSub")}</Text>
        </View>
      ) : (
        <Text style={{ color: c.text, fontSize: 28, fontWeight: "800", marginBottom: 4 }}>{t("reviewTitle")}</Text>
      )}
      <Text style={{ color: c.sub, fontSize: 15, marginBottom: 16 }} numberOfLines={2}>{name}</Text>

      {actionError ? <Banner kind="error" text={actionError} /> : null}

      <View style={{ flexDirection: "row", gap: 10, marginBottom: 22 }}>
        <Stat label={t("printTime")} value={printTime(r?.print_time)} />
        <Stat label={t("filament")} value={r?.filament_g != null ? `${r.filament_g.toFixed(1)} g` : "–"}
          sub={r?.filament_m != null ? `${r.filament_m} m` : undefined} />
        <Stat label={t("layers")} value={r?.layers != null ? String(r.layers) : "–"} />
      </View>

      <Button kind="secondary" title={t("showPreview")} icon="layers-outline" style={{ marginBottom: 22 }}
        onPress={() => router.push({ pathname: "/preview/[id]", params: { id: job.id } })} />

      {!done && printerLanes.length ? (
        <Section title={t("lanes")} footer={t("lanesHint")}>
          {colours.map((col, i) => {
            const lane = printerLanes.find(l => l.tool === laneFor[col.index]);
            return (
              <View key={col.index}>
                {i ? <Divider /> : null}
                <Row label={colours.length > 1 ? t("colorN", { n: col.index }) : t("lane")}
                  sub={shortName(col.preset)} value={laneLabel(laneFor[col.index])}
                  onPress={() => setLaneSheet(col.index)}
                  right={<View style={{ flexDirection: "row", marginLeft: 8, gap: 4 }}>
                    {col.color ? <View style={{ width: 14, height: 14, borderRadius: 7, backgroundColor: col.color,
                      borderWidth: 1, borderColor: c.line }} /> : null}
                    <View style={{ width: 22, height: 22, borderRadius: 11, backgroundColor: lane?.color || c.track,
                      borderWidth: 1, borderColor: c.line }} />
                  </View>} />
              </View>
            );
          })}
        </Section>
      ) : null}
      {!done ? laneWarnings.map(w => <Banner key={w.text} kind={w.blocking ? "error" : "warn"} text={w.text} />) : null}
      {laneSheet != null ? (
        <PickerSheet visible title={colours.length > 1 ? t("colorN", { n: laneSheet }) : t("lane")}
          choices={printerLanes.map(l => ({ value: String(l.tool), label: laneLabel(l.tool ?? undefined),
            sub: [l.filament, l.in_toolhead ? t("laneInToolhead") : null, `T${l.tool}`].filter(Boolean).join(" · ") }))}
          value={laneFor[laneSheet] != null ? String(laneFor[laneSheet]) : null}
          onPick={v => setLaneChoice(p => ({ ...p, [laneSheet]: Number(v) }))}
          onClose={() => setLaneSheet(null)} searchLabel={t("search")} closeLabel="OK" />
      ) : null}

      {r?.filaments && r.filaments.length > 1 ? (
        <Section title={t("colors")}>
          {r.filaments.map((f, i) => (
            <View key={f.index}>
              {i ? <Divider /> : null}
              <Row label={t("colorN", { n: f.index })} sub={shortName(f.preset)}
                value={f.grams != null ? `${f.grams.toFixed(1)} g` : "–"}
                right={<View style={{ width: 22, height: 22, borderRadius: 11, backgroundColor: f.color ?? c.track,
                  marginLeft: 10, borderWidth: 1, borderColor: c.line }} />} />
            </View>
          ))}
        </Section>
      ) : null}

      <Section title={t("details")}>
        <Row label={t("printer")} value={pname} />
        <Divider />
        <Row label={t("material")} value={shortName(p.filament)} />
        <Divider />
        <Row label={t("quality")} value={shortName(p.process)} />
        <Divider />
        <Row label={t("plate")} value={plateName(t, p.bed_type)} />
        <Divider />
        <Row label={t("changed")} sub={changed.length ? changed.join(" · ") : t("changedNone")} />
      </Section>

      {!done ? (
        <>
          {busy ? <Banner kind="warn" text={t("printerBusy", { printer: pname })} /> : null}
          {kind === "offline" ? <Banner kind="error" text={t("printerOffline", { printer: pname })} /> : null}
          <Card style={{ padding: 16, flexDirection: "row", alignItems: "center" }}>
            <Text style={{ color: c.text, fontSize: 16, flex: 1, lineHeight: 22 }}>
              {t("confirmPlate", { material: shortName(p.filament) || t("filament") })}
            </Text>
            <Switch value={plateOk} onValueChange={v => { tap(); setPlateOk(v); }} trackColor={{ true: c.accent, false: c.track }}
              accessibilityLabel={t("confirmPlate", { material: shortName(p.filament) })} />
          </Card>
          {levelingOn != null ? (
            <Card style={{ padding: 16, flexDirection: "row", alignItems: "center", marginTop: 10 }}>
              <View style={{ flex: 1 }}>
                <Text style={{ color: c.text, fontSize: 16, lineHeight: 22 }}>{t("leveling")}</Text>
                <Text style={{ color: c.sub, fontSize: 13, marginTop: 2 }}>{t("levelingSub")}</Text>
              </View>
              <Switch value={levelingOn} onValueChange={changeLeveling} trackColor={{ true: c.accent, false: c.track }}
                accessibilityLabel={t("leveling")} />
            </Card>
          ) : null}
          <Button kind="plain" title={t("editSettings")} icon="options-outline" onPress={editSettings} style={{ marginTop: 12 }} />
        </>
      ) : null}
      <Button kind="plain" title={t("deleteJob")} onPress={del} style={{ marginTop: 4 }} />
    </Screen>
  );
}

