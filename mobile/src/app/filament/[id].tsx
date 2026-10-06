// Filament per slot (server 0.37.0): load / unload and what is in each AMS tray or on the external spool holder.
// Loading and unloading heat the nozzle and move filament - only when no print runs, after a confirmation.
import { Stack, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";

import { Badge, Banner, Button, Divider, PickerSheet, Row, Screen, Section, confirmAsync } from "@/components/ui";
import { errorText, type FilamentInfo, type Lane } from "@/lib/api";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

// common filament colours for the quick choice; any other with the hex field
const SWATCHES = ["#FFFFFF", "#000000", "#8A8A8A", "#E02020", "#FF7A00", "#FFD000", "#3CB043", "#0078BF", "#1E3A8A",
  "#7B3FA0", "#FF69B4", "#8B5A2B", "#F5DEB3", "#C0C0C0", "#D4AF37", "#00B5B8"];

export default function FilamentScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const [info, setInfo] = useState<FilamentInfo | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [done, setDone] = useState("");
  const [edit, setEdit] = useState<Lane | null>(null);
  const [material, setMaterial] = useState<string | null>(null);
  const [color, setColor] = useState("#FFFFFF");
  const [pickMaterial, setPickMaterial] = useState(false);

  const load = useCallback(() => {
    api?.filamentInfo(id).then(i => { setInfo(i); setError(""); }).catch(e => setError(errorText(t, e)));
  }, [api, id, t]);
  useFocusEffect(useCallback(() => {
    load();
    const timer = setInterval(load, 4000);          // follow loading / unloading as it happens
    return () => clearInterval(timer);
  }, [load]));

  const slotName = (l: Lane) => (l.tool === 254 ? t("filamentExternal") : `${t("filamentSlot")} ${l.id}`);
  const tempFor = (l: Lane | null) => info?.materials.find(m => m.type === l?.material || m.name === l?.material)?.load_temp
    ?? info?.materials[0]?.load_temp ?? 220;

  const run = async (key: string, body: Parameters<NonNullable<typeof api>["filamentAction"]>[1], message: string) => {
    if (!api) return;
    setBusy(key);
    setDone("");
    try {
      await api.filamentAction(id, body);
      setDone(message);
      setError("");
      setTimeout(load, 1500);
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setBusy("");
    }
  };

  const loadSlot = async (l: Lane) => {
    const temp = tempFor(l);
    if (!(await confirmAsync(t("filamentLoadQ", { slot: slotName(l), temp: String(temp) }), t("filamentLoad"), t("cancelBtn"), false))) return;
    run(`load:${l.tool}`, { action: "load", slot: l.tool ?? undefined, confirm: true }, t("filamentLoading", { slot: slotName(l) }));
  };
  const unload = async () => {
    const inHead = info?.slots.find(l => l.in_toolhead) ?? null;
    const temp = tempFor(inHead);
    if (!(await confirmAsync(t("filamentUnloadQ", { temp: String(temp) }), t("filamentUnload"), t("cancelBtn"), false))) return;
    run("unload", { action: "unload", confirm: true }, t("filamentUnloading"));
  };
  const openEdit = (l: Lane) => {
    setEdit(l);
    setMaterial(info?.materials.find(m => m.type === l.material || m.name === l.material)?.name ?? null);
    setColor(l.color ?? "#FFFFFF");
  };
  const save = () => {
    if (!edit || !material) return;
    run(`set:${edit.tool}`, { action: "set", slot: edit.tool ?? undefined, material, color }, t("filamentSaved", { slot: slotName(edit) }));
    setEdit(null);
  };

  if (!info && !error) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.bg }}>
        <Stack.Screen options={{ title: t("filamentTitle") }} />
        <ActivityIndicator />
      </View>
    );
  }
  const validColor = /^#[0-9A-Fa-f]{6}$/.test(color);

  return (
    <Screen>
      <Stack.Screen options={{ title: name ? `${t("filamentTitle")} · ${name}` : t("filamentTitle") }} />
      {error ? <View style={{ marginBottom: space }}><Banner kind="error" text={error} /></View> : null}
      {done ? <View style={{ marginBottom: space }}><Banner kind="ok" text={done} /></View> : null}
      {info && !info.supported ? <Banner kind="info" text={t("filamentUnsupported")} /> : null}
      {info?.busy ? <View style={{ marginBottom: space }}><Banner kind="warn" icon="warning-outline" text={t("filamentBusy")} /></View> : null}

      {info?.supported ? (
        <Section title={t("filamentSlots")} footer={t("filamentHint")}>
          {info.slots.map((l, i) => (
            <View key={`${l.unit}-${l.id}`}>
              {i ? <Divider /> : null}
              <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space, paddingVertical: 12, gap: 12 }}>
                <View style={{ width: 28, height: 28, borderRadius: 14, borderWidth: 1, borderColor: c.line,
                               backgroundColor: l.color ?? "transparent" }} />
                <View style={{ flex: 1 }}>
                  <Text style={{ color: c.text, fontSize: 16, fontWeight: "600" }}>
                    {slotName(l)} · {l.material ?? (l.loaded ? t("filamentUnknown") : t("filamentEmpty"))}</Text>
                  {l.filament ? <Text style={{ color: c.sub, fontSize: 13 }}>{l.filament}</Text> : null}
                </View>
                {l.in_toolhead ? <Badge text={t("filamentInHead")} kind="accent" /> : null}
              </View>
              <View style={{ flexDirection: "row", gap: 8, paddingHorizontal: space, paddingBottom: 12 }}>
                {info.load && !l.in_toolhead && l.loaded ? (
                  <Button kind="secondary" title={t("filamentLoad")} icon="arrow-down-circle-outline" style={{ flex: 1 }}
                    disabled={info.busy || !!busy} loading={busy === `load:${l.tool}`} onPress={() => loadSlot(l)} />
                ) : null}
                {info.unload && l.in_toolhead ? (
                  <Button kind="secondary" title={t("filamentUnload")} icon="arrow-up-circle-outline" style={{ flex: 1 }}
                    disabled={info.busy || !!busy} loading={busy === "unload"} onPress={unload} />
                ) : null}
                {info.set ? (
                  <Button kind="secondary" title={t("filamentEdit")} icon="color-palette-outline" style={{ flex: 1 }}
                    disabled={!!busy} loading={busy === `set:${l.tool}`} onPress={() => openEdit(l)} />
                ) : null}
              </View>
            </View>
          ))}
        </Section>
      ) : null}

      {edit ? (
        <Section title={t("filamentEditTitle", { slot: slotName(edit) })}>
          <Row icon="flask-outline" label={t("material")} value={material ?? t("chooseModel")} onPress={() => setPickMaterial(true)} />
          <Divider />
          <View style={{ padding: space, gap: 12 }}>
            <Text style={{ color: c.sub, fontSize: 13 }}>{t("filamentColor")}</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
              {SWATCHES.map(s => (
                <Pressable key={s} onPress={() => setColor(s)} accessibilityLabel={s}
                  style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: s, borderWidth: color.toUpperCase() === s ? 3 : 1,
                           borderColor: color.toUpperCase() === s ? c.accent : c.line }} />
              ))}
            </View>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <View style={{ width: 28, height: 28, borderRadius: 14, borderWidth: 1, borderColor: c.line,
                             backgroundColor: validColor ? color : "transparent" }} />
              <TextInput value={color} onChangeText={v => setColor(v.startsWith("#") ? v : `#${v}`)} maxLength={7}
                autoCapitalize="characters" autoCorrect={false} accessibilityLabel={t("filamentColor")}
                style={{ flex: 1, color: c.text, fontSize: 16, paddingVertical: 8 }} />
            </View>
            <Button title={t("save")} icon="checkmark" onPress={save} disabled={!material || !validColor} />
            <Button kind="plain" title={t("cancelBtn")} onPress={() => setEdit(null)} />
          </View>
        </Section>
      ) : null}

      <PickerSheet visible={pickMaterial} title={t("material")} value={material} searchLabel={t("search")} closeLabel="OK"
        choices={(info?.materials ?? []).map(m => ({ value: m.name, label: `${m.name}  ·  ${m.temp_min}–${m.temp_max} °C` }))}
        onPick={setMaterial} onClose={() => setPickMaterial(false)} />
    </Screen>
  );
}
