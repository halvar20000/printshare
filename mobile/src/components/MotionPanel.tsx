// Moving the printer by hand (server 0.43.0): home, jog pad for X/Y/Z, extrude/retract, load/unload, motors off and
// the printer's own macros (Klipper). Part of the printer's control page; everything is locked while a print runs.
import Ionicons from "@expo/vector-icons/Ionicons";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { Banner, Button, Divider, Row, Section, Segmented, confirmAsync, tap } from "@/components/ui";
import { errorText, type Api, type Motion, type MotionAction } from "@/lib/api";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

const EXTRUDE_STEPS = [5, 10, 25, 50];
const HOT_ENOUGH = 170;            // °C - firmware refuses to extrude colder (Klipper min_extrude_temp)

type Props = {
  api: Api; id: string; caps: Motion; printing: boolean; nozzle: number | null;
  /** heat the nozzle for extruding (the page's own heater change, with its checks) */
  onHeat: () => void;
};

export function MotionPanel({ api, id, caps, printing, nozzle, onHeat }: Props) {
  const { t } = useApp();
  const c = useColors();
  const steps = caps.jog?.steps ?? [];
  const [step, setStep] = useState<number>(steps.includes(10) ? 10 : steps[0] ?? 1);
  const [amount, setAmount] = useState(10);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  const run = async (key: string, body: MotionAction, ask?: string) => {
    if (ask && !(await confirmAsync(ask, t("motionGo"), t("cancelBtn"), false))) return;
    tap();
    setBusy(key); setError(""); setDone("");
    try {
      await api.motion(id, { ...body, confirm: !!ask });
      if (body.action !== "jog") setDone(t("motionDone"));
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setBusy("");
    }
  };
  const off = printing || !!busy;
  const jog = (axis: string, dir: 1 | -1) => run(`jog:${axis}${dir}`, { action: "jog", axis, distance: dir * step });

  const pad = (axis: string, dir: 1 | -1, icon: keyof typeof Ionicons.glyphMap, label: string) => {
    const can = caps.jog?.axes.includes(axis);
    return (
      <Pressable disabled={off || !can} onPress={() => jog(axis, dir)} accessibilityRole="button"
        accessibilityLabel={`${axis} ${dir > 0 ? "+" : "−"}${step} mm`}
        style={({ pressed }) => ({ width: 64, height: 56, borderRadius: 12, alignItems: "center", justifyContent: "center",
          backgroundColor: pressed ? c.accent : c.input, opacity: off || !can ? 0.4 : 1 })}>
        {busy === `jog:${axis}${dir}` ? <ActivityIndicator /> : <>
          <Ionicons name={icon} size={20} color={c.text} />
          <Text style={{ color: c.text, fontSize: 12, fontWeight: "600" }}>{label}</Text>
        </>}
      </Pressable>
    );
  };
  const cold = nozzle != null && nozzle < HOT_ENOUGH;

  return (
    <>
      {error ? <View style={{ marginBottom: space }}><Banner kind="error" text={error} /></View> : null}
      {done ? <View style={{ marginBottom: space }}><Banner kind="ok" text={done} /></View> : null}

      {caps.home.length || caps.jog ? (
        <Section title={t("motionTitle")} footer={t("motionHint")}>
          {caps.home.length ? (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, padding: 12 }}>
              {caps.home.map(a => (
                <Button key={a} kind="secondary" icon="home-outline" title={a === "XYZ" ? t("homeAll") : `${t("home")} ${a}`}
                  style={{ flexGrow: 1, flexBasis: a === "XYZ" ? "100%" : "28%" }} loading={busy === `home:${a}`}
                  disabled={off} onPress={() => run(`home:${a}`, { action: "home", axis: a })} />
              ))}
            </View>
          ) : null}
          {caps.jog ? (
            <>
              <Divider />
              <View style={{ padding: 12 }}>
                <Segmented<string> values={steps.map(String)} value={String(step)}
                  labels={Object.fromEntries(steps.map(s => [String(s), `${s} mm`]))} onChange={v => setStep(Number(v))} />
                <View style={{ flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 28, marginTop: 14 }}>
                  <View style={{ alignItems: "center", gap: 6 }}>
                    {pad("Y", 1, "arrow-up", "Y+")}
                    <View style={{ flexDirection: "row", gap: 6 }}>
                      {pad("X", -1, "arrow-back", "X−")}
                      <View style={{ width: 64, height: 56, alignItems: "center", justifyContent: "center" }}>
                        <Text style={{ color: c.sub, fontSize: 13 }}>X / Y</Text>
                      </View>
                      {pad("X", 1, "arrow-forward", "X+")}
                    </View>
                    {pad("Y", -1, "arrow-down", "Y−")}
                  </View>
                  <View style={{ alignItems: "center", gap: 6 }}>
                    {pad("Z", 1, "chevron-up", "Z+")}
                    <View style={{ width: 64, height: 56, alignItems: "center", justifyContent: "center" }}>
                      <Text style={{ color: c.sub, fontSize: 13 }}>Z</Text>
                    </View>
                    {pad("Z", -1, "chevron-down", "Z−")}
                  </View>
                </View>
              </View>
            </>
          ) : null}
          {caps.motors_off ? (
            <>
              <Divider />
              <Row icon="power-outline" label={t("motorsOff")} sub={t("motorsOffSub")}
                onPress={off ? undefined : () => run("motors_off", { action: "motors_off" })}
                right={busy === "motors_off" ? <ActivityIndicator /> : undefined} />
            </>
          ) : null}
        </Section>
      ) : null}

      {caps.extrude || caps.load || caps.unload ? (
        <Section title={t("extruderTitle")} footer={caps.extrude ? t("extrudeHint", { t: HOT_ENOUGH }) : undefined}>
          {caps.extrude ? (
            <View style={{ padding: 12 }}>
              {cold ? (
                <View style={{ marginBottom: 10 }}>
                  <Banner kind="warn" text={t("extrudeCold", { t: Math.round(nozzle ?? 0) })} />
                  <Button kind="secondary" icon="flame-outline" title={t("extrudeHeat")} disabled={off}
                    style={{ marginTop: 8 }} onPress={onHeat} />
                </View>
              ) : null}
              <Segmented<string> values={EXTRUDE_STEPS.map(String)} value={String(amount)}
                labels={Object.fromEntries(EXTRUDE_STEPS.map(s => [String(s), `${s} mm`]))}
                onChange={v => setAmount(Number(v))} />
              <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
                <Button kind="secondary" icon="arrow-up" title={t("retract")} style={{ flex: 1 }} disabled={off}
                  loading={busy === "retract"} onPress={() => run("retract", { action: "extrude", distance: -amount })} />
                <Button kind="secondary" icon="arrow-down" title={t("extrude")} style={{ flex: 1 }} disabled={off}
                  loading={busy === "extrude"} onPress={() => run("extrude", { action: "extrude", distance: amount })} />
              </View>
            </View>
          ) : null}
          {caps.load ? (
            <>
              {caps.extrude ? <Divider /> : null}
              <Row icon="enter-outline" label={t("motionLoad")} onPress={off ? undefined
                : () => run("load", { action: "load" }, t("motionLoadQ"))}
                right={busy === "load" ? <ActivityIndicator /> : undefined} />
            </>
          ) : null}
          {caps.unload ? (
            <>
              {caps.extrude || caps.load ? <Divider /> : null}
              <Row icon="exit-outline" label={t("motionUnload")} onPress={off ? undefined
                : () => run("unload", { action: "unload" }, t("motionUnloadQ"))}
                right={busy === "unload" ? <ActivityIndicator /> : undefined} />
            </>
          ) : null}
        </Section>
      ) : null}

      {caps.macros.length ? (
        <Section title={t("macrosTitle")} footer={t("macrosHint")}>
          {caps.macros.map((m, i) => (
            <View key={m}>
              {i ? <Divider /> : null}
              <Row icon="play-circle-outline" label={m}
                onPress={off ? undefined : () => run(`macro:${m}`, { action: "macro", macro: m }, t("macroQ", { m }))}
                right={busy === `macro:${m}` ? <ActivityIndicator /> : undefined} />
            </View>
          ))}
        </Section>
      ) : null}
    </>
  );
}
