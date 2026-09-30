// Printer control (issue #5): temperatures with history, fans, light and print speed.
// Anything that could spoil a running print needs an explicit confirmation (NF-05).
import { Stack, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, Switch, Text, View, useWindowDimensions } from "react-native";

import { TempChart } from "@/components/tempchart";
import {
  Banner, Button, Card, Divider, PickerSheet, Row, Screen, Section, Segmented, confirmAsync, tap,
} from "@/components/ui";
import { ApiError, type Controls, type PrinterStatus, type TempHistory } from "@/lib/api";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

type Kind = "heater" | "fan" | "light" | "speed";
const FAN_STEPS = [0, 25, 50, 75, 100];
const HIGH = { nozzle: 260, bed: 100, chamber: 50 } as Record<string, number>;
const PRESETS = { preheatPla: { nozzle: 210, bed: 60 }, preheatPetg: { nozzle: 240, bed: 80 }, coolDown: { nozzle: 0, bed: 0 } };

export default function Control() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const { width } = useWindowDimensions();
  const [caps, setCaps] = useState<Controls | null>(null);
  const [status, setStatus] = useState<PrinterStatus | null>(null);
  const [history, setHistory] = useState<TempHistory | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [picker, setPicker] = useState<string | null>(null);

  const loadStatus = useCallback(() => {
    if (!api) return;
    api.status(id).then(s => { setStatus(s); setError(""); }).catch(e => setError((e as Error).message));
  }, [api, id]);
  const loadHistory = useCallback(() => {
    api?.temperatures(id).then(setHistory).catch(() => {});
  }, [api, id]);

  useFocusEffect(useCallback(() => {
    if (!api) return;
    api.controls(id).then(setCaps).catch(e => setError((e as Error).message));
    loadStatus();
    loadHistory();
    const s = setInterval(loadStatus, 3000);
    const h = setInterval(loadHistory, 10000);
    return () => { clearInterval(s); clearInterval(h); };
  }, [api, id, loadStatus, loadHistory]));

  const printing = status?.kind === "active" || status?.kind === "paused";
  const heaterName = (h: string) => t.table.heaterNames[h] ?? h;

  /** Send one or more changes; asks first when a print runs or a temperature is unusually high. */
  const apply = async (key: string, changes: { kind: Kind; id: string; value: number | boolean }[]) => {
    if (!api) return;
    const risky = changes.some(ch => ch.kind === "heater" || (ch.kind === "fan" && ch.value === 0));
    const high = changes.find(ch => ch.kind === "heater" && typeof ch.value === "number" && ch.value >= (HIGH[ch.id] ?? 999));
    let confirm = false;
    if (printing && risky) {
      if (!(await confirmAsync(t("confirmDuringPrint"), t("change"), t("cancelBtn")))) return;
      confirm = true;
    } else if (high) {
      if (!(await confirmAsync(t("confirmHigh", { name: heaterName(high.id), v: String(high.value) }),
        t("change"), t("cancelBtn"), false))) return;
    }
    setBusy(key);
    try {
      for (const ch of changes) {
        try {
          await api.adjust(id, ch.kind, ch.id, ch.value, confirm);
        } catch (e) {
          // the print started after our last status poll: ask now instead of failing
          if (!(e instanceof ApiError && e.status === 409) || confirm) throw e;
          if (!(await confirmAsync(t("confirmDuringPrint"), t("change"), t("cancelBtn")))) return;
          confirm = true;
          await api.adjust(id, ch.kind, ch.id, ch.value, true);
        }
      }
      setError("");
      loadStatus();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  if (!caps && !error) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.bg }}>
        <Stack.Screen options={{ title: name ?? t("control") }} />
        <ActivityIndicator />
      </View>
    );
  }

  const heaters = caps?.heaters ?? [];
  const shown = Object.keys(status?.heaters ?? {});
  for (const h of heaters) if (!shown.includes(h.id)) shown.push(h.id);
  const canHeat = (h: string) => heaters.some(x => x.id === h);
  const hasNozzleBed = canHeat("nozzle") && canHeat("bed");
  const pickHeater = heaters.find(h => h.id === picker);
  const low = pickHeater?.id === "nozzle" ? 150 : 30;       // below that nobody sets a target
  const choices = pickHeater ? [
    { value: "0", label: t("off") },
    ...Array.from({ length: Math.floor((pickHeater.max - low) / 5) + 1 }, (_, i) => low + i * 5)
      .map(v => ({ value: String(v), label: `${v} °C` })),
  ] : [];

  const speed = caps?.speed;
  const speedValues = speed?.modes ?? (speed ? [50, 75, 100, 125, 150].filter(v => v >= (speed.min ?? 10) && v <= (speed.max ?? 300)) : []);
  const speedLabels = Object.fromEntries(speedValues.map(v => [String(v), speed?.modes ? t.table.speedModes[v] ?? `${v} %` : `${v} %`]));

  return (
    <Screen>
      <Stack.Screen options={{ title: name ?? t("control") }} />
      {error ? <View style={{ marginBottom: space }}><Banner kind="error" text={error} /></View> : null}
      {printing ? <View style={{ marginBottom: space }}><Banner kind="warn" icon="warning-outline" text={t("printRunningHint")} /></View> : null}

      {shown.length ? (
        <Section title={t("temperatures")}>
          {shown.map((h, i) => {
            const st = status?.heaters?.[h];
            const actual = st?.actual != null ? `${Math.round(st.actual)} °C` : "–";
            const target = st?.target ? ` → ${Math.round(st.target)} °C` : "";
            return (
              <View key={h}>
                {i ? <Divider /> : null}
                <Row icon={h === "nozzle" ? "flame-outline" : h === "bed" ? "square-outline" : "cube-outline"}
                  label={heaterName(h)} value={actual + target}
                  sub={canHeat(h) ? null : t("sensorOnly")}
                  onPress={canHeat(h) ? () => setPicker(h) : undefined}
                  right={busy === `heater:${h}` ? <ActivityIndicator style={{ marginLeft: 8 }} /> : undefined} />
              </View>
            );
          })}
          {hasNozzleBed ? (
            <>
              <Divider />
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, padding: 12 }}>
                {(Object.keys(PRESETS) as (keyof typeof PRESETS)[]).map(k => (
                  <Button key={k} kind="secondary" title={t(k)}
                    icon={k === "coolDown" ? "snow-outline" : undefined} loading={busy === k}
                    style={{ flexGrow: 1, flexBasis: k === "coolDown" ? "100%" : "40%" }}
                    onPress={() => apply(k, [
                      { kind: "heater", id: "nozzle", value: PRESETS[k].nozzle },
                      { kind: "heater", id: "bed", value: PRESETS[k].bed }])} />
                ))}
              </View>
            </>
          ) : null}
        </Section>
      ) : null}

      {shown.length ? (
        <Card style={{ marginBottom: 24, paddingTop: 8 }}>
          <TempChart series={history?.series ?? {}} width={Math.min(width, 640) - 2 * space} />
        </Card>
      ) : null}

      {caps?.fans.length ? (
        <Section title={t("fans")}>
          {caps.fans.map((f, i) => {
            const cur = status?.fans?.[f.id];
            return (
              <View key={f.id}>
                {i ? <Divider /> : null}
                <View style={{ paddingHorizontal: space, paddingVertical: 12 }}>
                <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 8 }}>
                  <Text style={{ color: c.text, fontSize: 16 }}>{t.table.fanNames[f.id] ?? f.id}</Text>
                  <Text style={{ color: c.sub, fontSize: 15 }}>{cur != null ? `${cur} %` : "–"}</Text>
                </View>
                <View style={{ flexDirection: "row", gap: 6 }}>
                  {FAN_STEPS.map(v => {
                    const on = cur != null && Math.abs(cur - v) < 5;
                    return (
                      <Pressable key={v} disabled={!!busy} accessibilityRole="button" accessibilityState={{ selected: on }}
                        onPress={() => { tap(); apply(`fan:${f.id}`, [{ kind: "fan", id: f.id, value: v }]); }}
                        style={({ pressed }) => ({ flex: 1, alignItems: "center", paddingVertical: 8, borderRadius: 10,
                          backgroundColor: on ? c.accent : c.input, opacity: pressed ? 0.7 : 1 })}>
                        <Text style={{ color: on ? "#fff" : c.text, fontSize: 14, fontWeight: on ? "600" : "400" }}>
                          {v ? `${v}` : t("off")}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
                </View>
              </View>
            );
          })}
        </Section>
      ) : null}

      {caps?.lights.length ? (
        <Section title={t("lights")}>
          {caps.lights.map((l, i) => (
            <View key={l.id}>
              {i ? <Divider /> : null}
              <Row icon="bulb-outline" label={t.table.lightNames[l.id] ?? l.id}
                right={<Switch value={!!status?.lights?.[l.id]} disabled={busy === `light:${l.id}`}
                  onValueChange={v => apply(`light:${l.id}`, [{ kind: "light", id: l.id, value: v }])} />} />
            </View>
          ))}
        </Section>
      ) : null}

      {speedValues.length ? (
        <Section title={t("speedTitle")}>
          <View style={{ padding: 12 }}>
            <Segmented<string> values={speedValues.map(String)}
              value={status?.speed != null ? String(status.speed) : null} labels={speedLabels}
              onChange={v => apply("speed", [{ kind: "speed", id: "speed", value: Number(v) }])} />
          </View>
        </Section>
      ) : null}

      <PickerSheet visible={!!pickHeater} title={pickHeater ? `${heaterName(pickHeater.id)} · ${t("setTarget")}` : ""}
        choices={choices} value={pickHeater && status?.heaters?.[pickHeater.id]?.target != null
          ? String(Math.round(status.heaters[pickHeater.id].target ?? 0)) : null}
        onPick={v => { const h = picker!; apply(`heater:${h}`, [{ kind: "heater", id: h, value: Number(v) }]); }}
        onClose={() => setPicker(null)} searchLabel={t("search")} closeLabel="OK" />
    </Screen>
  );
}
