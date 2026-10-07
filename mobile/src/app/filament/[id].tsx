// Filament per slot (server 0.37.0): load / unload and what is in each AMS tray or on the external spool holder.
// Loading and unloading heat the nozzle and move filament - only when no print runs, after a confirmation.
// A spool can be assigned to a slot (NFC scan of an OpenPrintTag or from the list; stored on this phone): the slot is set
// to the spool's material and colour, and the print screen proposes and books that spool for the slot by itself.
import { Stack, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";

import { Badge, Banner, Button, Divider, PickerSheet, Row, Screen, Section, confirmAsync } from "@/components/ui";
import { errorText, type FilamentInfo, type Lane, type ReaderKey, type SlotSpools } from "@/lib/api";
import { useApp } from "@/lib/app";
import { cancelScan, identifyChip, nfcStatus, scanChip } from "@/lib/nfc";
import { loadSlotSpools, loadSpoolmanUrl, openSpoolman, setSlotSpool, spoolLabel, type Spool } from "@/lib/spoolman";
import { space, useColors } from "@/lib/theme";

// common filament colours for the quick choice; any other with the hex field
const SWATCHES = ["#FFFFFF", "#000000", "#8A8A8A", "#E02020", "#FF7A00", "#FFD000", "#3CB043", "#0078BF", "#1E3A8A",
  "#7B3FA0", "#FF69B4", "#8B5A2B", "#F5DEB3", "#C0C0C0", "#D4AF37", "#00B5B8"];

export default function FilamentScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const { api, server, t } = useApp();
  const c = useColors();
  const [info, setInfo] = useState<FilamentInfo | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [done, setDone] = useState("");
  const [edit, setEdit] = useState<Lane | null>(null);
  const [material, setMaterial] = useState<string | null>(null);
  const [color, setColor] = useState("#FFFFFF");
  const [pickMaterial, setPickMaterial] = useState(false);
  // spools: own Spoolman or the cloud account's (Settings → Spoolman); which spool sits in which slot
  const [spools, setSpools] = useState<Spool[] | null>(null);
  const [hasSpools, setHasSpools] = useState(false);
  const [slotSpools, setSlotSpools] = useState<Record<string, number>>({});
  const [spoolFor, setSpoolFor] = useState<Lane | null>(null);
  // a chip nobody linked yet (scanned by the phone or seen by a reader at the printer): "which spool is this?"
  const [linkFor, setLinkFor] = useState<{ lane: Lane; uid: string } | null>(null);
  const [scans, setScans] = useState<SlotSpools["scans"]>({});
  const [reader, setReader] = useState<(ReaderKey & { key?: string }) | null>(null);
  const hasNfc = useMemo(() => nfcStatus() !== "none", []);

  const load = useCallback(() => {
    api?.filamentInfo(id).then(i => { setInfo(i); setError(""); }).catch(e => setError(errorText(t, e)));
  }, [api, id, t]);
  useFocusEffect(useCallback(() => {
    if (server) {
      loadSlotSpools(server, id, api).then(setSlotSpools);
      api?.slotSpools(id).then(r => setScans(r.scans)).catch(() => setScans({}));
      api?.readerKey(id).then(setReader).catch(() => setReader(null));
      loadSpoolmanUrl(server).then(url => {
        setHasSpools(!!url);
        if (url) openSpoolman(server, url).spools().then(setSpools).catch(() => setSpools([]));
      });
    }
  }, [server, id, api]));
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

  /** Put a spool into a slot: remembered on this phone, and the printer's slot gets the spool's material and colour. */
  const assign = async (l: Lane, spool: Spool | null) => {
    if (!server || l.tool == null) return;
    const r = await setSlotSpool(server, id, l.tool, spool?.id ?? null, api);
    setSlotSpools(r.slots);
    if (!spool) { setDone(t("slotSpoolCleared", { slot: slotName(l) })); return; }
    if (r.printerSet) { setDone(t("slotSpoolSet", { slot: slotName(l), spool: spoolLabel(spool) })); setTimeout(load, 1500); return; }
    const m = info?.materials.find(x => x.name.toUpperCase() === (spool.material ?? "").toUpperCase()
      || x.type === (spool.material ?? "").toUpperCase());
    const col = (spool.color ?? "").replace(/^#?/, "#");
    if (info?.set && m && /^#[0-9A-Fa-f]{6}/.test(col)) {
      run(`set:${l.tool}`, { action: "set", slot: l.tool, material: m.name, color: col.slice(0, 7) },
        t("slotSpoolSet", { slot: slotName(l), spool: spoolLabel(spool) }));
    } else {
      setDone(t("slotSpoolSet", { slot: slotName(l), spool: spoolLabel(spool) }));
    }
  };
  const pickSpool = async (l: Lane, v: string) => {
    setSpoolFor(null);
    if (v === "none") return assign(l, null);
    if (v === "nfc") {
      setBusy(`nfc:${l.tool}`);
      setError("");
      setDone(t("nfcHold"));
      try {
        const chip = await scanChip(t);
        const hit = await identifyChip(api, chip, spools ?? []);
        setDone("");
        if (hit) { await assign(l, hit); return; }
        if (chip.tag && !spools?.length) { setError(t("slotSpoolNoMatch", { material: chip.tag.materialType ?? "?" })); return; }
        setLinkFor({ lane: l, uid: chip.uid });            // unknown chip: link it to a spool now
      } catch (e) {
        setDone("");
        if ((e as Error).message) setError((e as Error).message);
      } finally {
        setBusy("");
      }
      return;
    }
    const sp = spools?.find(s => String(s.id) === v);
    if (sp) await assign(l, sp);
  };

  /** Link an unknown chip to a spool - from now on the phone and the readers know it - and put the spool in the slot. */
  const linkChip = async (v: string) => {
    const target = linkFor;
    setLinkFor(null);
    const sp = spools?.find(s => String(s.id) === v);
    if (!target || !sp || !api) return;
    try {
      await api.linkSpoolTag(target.uid, sp.id);
      await assign(target.lane, sp);
      api.slotSpools(id).then(r => setScans(r.scans)).catch(() => {});
    } catch (e) {
      setError(errorText(t, e));
    }
  };
  const newReaderKey = async () => {
    if (!api) return;
    if (reader?.enabled && !(await confirmAsync(t("readerKeyRenewQ"), t("readerKeyNew"), t("cancelBtn")))) return;
    try { setReader(await api.createReaderKey(id)); } catch (e) { setError(errorText(t, e)); }
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
                  {(() => {
                    const scan = l.tool != null ? scans[String(l.tool)] : undefined;
                    return scan && scan.spool == null ? (
                      <Pressable onPress={() => setLinkFor({ lane: l, uid: scan.uid })} accessibilityRole="button">
                        <Text style={{ color: c.accent, fontSize: 13 }}>{t("readerUnknownChip")}</Text>
                      </Pressable>
                    ) : null;
                  })()}
                  {(() => {
                    const sp = l.tool != null ? spools?.find(s => s.id === slotSpools[String(l.tool)]) : undefined;
                    return sp ? <Text style={{ color: c.sub, fontSize: 13 }}>
                      {t("slotSpool", { spool: spoolLabel(sp) })}{sp.remaining_g != null ? ` · ${Math.round(sp.remaining_g)} g` : ""}</Text> : null;
                  })()}
                </View>
                {l.in_toolhead ? <Badge text={t("filamentInHead")} kind="accent" /> : null}
              </View>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, paddingHorizontal: space, paddingBottom: 12 }}>
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
                {hasSpools ? (
                  <Button kind="secondary" title={t("slotSpoolBtn")} icon="disc-outline" style={{ flex: 1 }}
                    disabled={!!busy} loading={busy === `nfc:${l.tool}`} onPress={() => setSpoolFor(l)} />
                ) : null}
              </View>
            </View>
          ))}
        </Section>
      ) : null}

      {info?.supported && reader ? (
        <Section title={t("readerTitle")} footer={reader.key ? t("readerKeyHint") : t("readerHint")}>
          <Row icon="radio-outline" label={reader.enabled ? t("readerOn") : t("readerOff")}
            value={reader.enabled ? t("readerKeyNew") : t("readerKeyCreate")} onPress={newReaderKey} />
          {reader.key ? (
            <View style={{ paddingHorizontal: space, paddingBottom: space, gap: 6 }}>
              <Text style={{ color: c.sub, fontSize: 13 }}>{t("readerUrl")}</Text>
              <Text selectable style={{ color: c.text, fontSize: 14 }}>{reader.url}</Text>
              <Text style={{ color: c.sub, fontSize: 13 }}>{t("readerKey")}</Text>
              <Text selectable style={{ color: c.text, fontSize: 14, fontWeight: "600" }}>{reader.key}</Text>
            </View>
          ) : null}
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

      <PickerSheet visible={!!spoolFor} title={spoolFor ? t("slotSpoolTitle", { slot: slotName(spoolFor) }) : ""}
        value={spoolFor?.tool != null && slotSpools[String(spoolFor.tool)] != null ? String(slotSpools[String(spoolFor.tool)]) : "none"}
        searchLabel={t("search")} closeLabel="OK"
        choices={[
          ...(hasNfc ? [{ value: "nfc", label: t("slotSpoolScan") }] : []),
          { value: "none", label: t("slotSpoolNone") },
          ...(spools ?? []).map(s => ({ value: String(s.id), label: `${spoolLabel(s)}${s.remaining_g != null ? ` · ${Math.round(s.remaining_g)} g` : ""}`,
                                         group: s.material ?? "?" })),
        ]}
        onPick={v => { const l = spoolFor; if (l) pickSpool(l, v); }} onClose={() => { setSpoolFor(null); cancelScan(); }} />
      <PickerSheet visible={!!linkFor} title={linkFor ? t("linkChipTitle", { slot: slotName(linkFor.lane) }) : ""} value={null}
        searchLabel={t("search")} closeLabel="OK"
        choices={(spools ?? []).map(s => ({ value: String(s.id), label: `${spoolLabel(s)}${s.remaining_g != null ? ` · ${Math.round(s.remaining_g)} g` : ""}`,
                                             group: s.material ?? "?" }))}
        onPick={linkChip} onClose={() => setLinkFor(null)} />
      <PickerSheet visible={pickMaterial} title={t("material")} value={material} searchLabel={t("search")} closeLabel="OK"
        choices={(info?.materials ?? []).map(m => ({ value: m.name, label: `${m.name}  ·  ${m.temp_min}–${m.temp_max} °C` }))}
        onPick={setMaterial} onClose={() => setPickMaterial(false)} />
    </Screen>
  );
}
