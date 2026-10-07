// One cloud spool (server 0.17.0): brand, name, material, colour, weights, location; copy, archive, delete.
// id "new" adds one; ?copy=<id> starts from an existing spool (a stack of identical spools). "From the database" fills
// the fields from SpoolmanDB (server 0.19.0): brand -> filament; "Read from NFC tag" from an OpenPrintTag spool
// (?tag=<json> when the review screen scanned a spool that has no entry yet).
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";

import { Banner, Button, Divider, PickerSheet, Row, Screen, Section, confirmAsync, tap } from "@/components/ui";
import type { FilamentPreset } from "@/lib/api";
import { cancelScan, nfcStatus, scanChip, scanSpool } from "@/lib/nfc";
import { tagLabel, type OpenPrintTag } from "@/lib/openprinttag";
import { useApp } from "@/lib/app";
import { CLOUD_SPOOLS, openSpoolman, type SpoolInput } from "@/lib/spoolman";
import { space, useColors } from "@/lib/theme";

const MATERIALS = ["PLA", "PLA+", "PETG", "ABS", "ASA", "TPU", "PA", "PC", "PLA-CF", "PETG-CF", "PA-CF", "PVA", "HIPS"];
const COLORS = ["#000000", "#FFFFFF", "#808080", "#C0C0C0", "#E53935", "#FB8C00", "#FDD835", "#43A047", "#1E88E5",
                "#8E24AA", "#6D4C41", "#F48FB1"];
const num = (v: string) => {
  const n = Number(v.replace(",", ".").trim());
  return v.trim() && Number.isFinite(n) && n >= 0 ? n : null;
};

export default function SpoolForm() {
  const { id, copy, tag: tagParam } = useLocalSearchParams<{ id: string; copy?: string; tag?: string }>();
  const isNew = id === "new";
  const { server, api, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const [loaded, setLoaded] = useState(isNew && !copy);
  const [vendor, setVendor] = useState("");
  const [name, setName] = useState("");
  const [material, setMaterial] = useState("PLA");
  const [color, setColor] = useState("#000000");
  const [weight, setWeight] = useState("1000");
  const [remaining, setRemaining] = useState("");
  const [location, setLocation] = useState("");
  const [comment, setComment] = useState("");
  const [spoolWeight, setSpoolWeight] = useState<number | null>(null);    // empty spool, from the database
  const [density, setDensity] = useState<number | null>(null);
  const [sheet, setSheet] = useState<"brand" | "filament" | null>(null);
  const [brands, setBrands] = useState<{ name: string; count: number }[] | null>(null);
  const [brand, setBrand] = useState<string | null>(null);
  const [presets, setPresets] = useState<FilamentPreset[] | null>(null);
  const [dbError, setDbError] = useState("");
  const [scanning, setScanning] = useState(false);
  const [nfcInfo, setNfcInfo] = useState("");
  const hasNfc = useMemo(() => nfcStatus() !== "none", []);

  const applyTag = (tg: Partial<OpenPrintTag>) => {
    setVendor(tg.brand ?? ""); setName(tg.name ?? ""); setMaterial(tg.materialType ?? "");
    if (tg.color) setColor(tg.color);
    if (tg.fullWeight) setWeight(String(tg.fullWeight));
    if (tg.remainingWeight != null) setRemaining(String(Math.round(tg.remainingWeight * 10) / 10));
    setSpoolWeight(tg.emptySpoolWeight ?? null);
    setDensity(tg.density ?? null);
    if (tg.location) setLocation(tg.location);
  };
  const readTag = async () => {
    tap();
    setScanning(true); setDbError(""); setNfcInfo("");
    try {
      const tg = await scanSpool(t);
      applyTag(tg);
      setNfcInfo(t("nfcFilled", { tag: tagLabel(tg as OpenPrintTag) }));
    } catch (e) {
      if ((e as Error).message) setDbError((e as Error).message);
    } finally {
      setScanning(false);
    }
  };
  /** Link a chip on this spool (sticker, Bambu tag, OpenPrintTag): from then on the app and readers know the spool. */
  const [linking, setLinking] = useState(false);
  const linkChip = async () => {
    if (!api) return;
    tap();
    setLinking(true); setDbError(""); setNfcInfo(t("nfcHold"));
    try {
      const chip = await scanChip(t);
      await api.linkSpoolTag(chip.uid, Number(id));
      setNfcInfo(t("nfcChipLinked", { uid: chip.uid }));
    } catch (e) {
      setNfcInfo("");
      if ((e as Error).message) setDbError((e as Error).message);
    } finally {
      setLinking(false);
    }
  };
  const [tagApplied, setTagApplied] = useState(false);
  if (tagParam && !tagApplied) {           // from the review screen: a scanned spool that isn't in the list yet
    setTagApplied(true);
    try { applyTag(JSON.parse(tagParam)); } catch { /* ignore */ }
  }
  const [archived, setArchived] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const from = isNew ? copy : id;
    if (!server || !from) return;
    openSpoolman(server, CLOUD_SPOOLS).spools(true).then(list => {
      const s = list.find(x => String(x.id) === from);
      if (s) {
        setVendor(s.vendor ?? ""); setName(s.name ?? ""); setMaterial(s.material ?? ""); setColor(s.color ?? "#000000");
        setWeight(s.filament_g != null ? String(s.filament_g) : "");
        setLocation(s.location ?? ""); setComment(isNew ? "" : s.comment ?? "");
        if (!isNew) {
          setRemaining(s.remaining_g != null ? String(Math.round(s.remaining_g * 10) / 10) : "");
          setArchived(s.archived);
        }
      }
      setLoaded(true);
    }).catch(e => { setError((e as Error).message); setLoaded(true); });
  }, [server, id, copy, isNew]);

  useEffect(() => {
    if (!api || sheet !== "brand" || brands) return;
    api.filamentBrands().then(setBrands).catch(e => { setDbError((e as Error).message); setSheet(null); });
  }, [api, sheet, brands]);
  useEffect(() => {
    if (!api || !brand) return;
    api.filamentPresets(brand).then(setPresets).catch(e => { setDbError((e as Error).message); setSheet(null); });
  }, [api, brand]);
  const presetChoices = useMemo(() => (presets ?? []).map((p, i) => ({
    value: String(i), label: p.name || p.material, group: p.material,
    sub: [p.weights.map(w => `${w.weight} g`).join(" / "), p.extruder_temp ? `${p.extruder_temp} °C` : null, p.finish]
      .filter(Boolean).join(" · "),
  })), [presets]);
  const applyPreset = (p: FilamentPreset) => {
    setVendor(brand ?? ""); setName(p.name); setMaterial(p.material);
    if (p.color_hex) setColor(`#${p.color_hex.replace("#", "").slice(0, 6).toUpperCase()}`);
    const w = p.weights[0];
    if (w?.weight) setWeight(String(w.weight));
    setSpoolWeight(w?.spool_weight ?? null);
    setDensity(p.density);
  };

  const hex = /^#?[0-9A-Fa-f]{6}$/.test(color.trim()) ? `#${color.trim().replace("#", "").toUpperCase()}` : null;
  const valid = !!hex && (weight.trim() === "" || num(weight) != null) && (remaining.trim() === "" || num(remaining) != null);

  const save = async (extra: Partial<SpoolInput> = {}) => {
    if (!server) return;
    setBusy(true);
    setError("");
    const body: SpoolInput = {
      filament: { vendor: vendor.trim() || null, name: name.trim() || null, material: material.trim() || null,
                  color_hex: hex, weight: num(weight), ...(density ? { density } : {}) },
      ...(spoolWeight != null ? { spool_weight: spoolWeight } : {}),
      location: location.trim() || null, comment: comment.trim() || null, ...extra,
    };
    if (remaining.trim()) body.remaining_weight = num(remaining);
    try {
      const sm = openSpoolman(server, CLOUD_SPOOLS);
      await (isNew ? sm.create(body) : sm.update(Number(id), body));
      router.back();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!server || !(await confirmAsync(t("spoolDeleteQ", { id }), t("del"), t("cancelBtn")))) return;
    try {
      await openSpoolman(server, CLOUD_SPOOLS).remove(Number(id));
      router.back();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  // label on the left, so it stays visible once the field is filled in
  const field = (label: string, value: string, set: (v: string) => void, opts: object = {}, placeholder = "") => (
    <View style={{ flexDirection: "row", alignItems: "center", paddingLeft: space }}>
      <Text style={{ color: c.text, fontSize: 16, width: 120 }}>{label}</Text>
      <TextInput value={value} onChangeText={set} placeholder={placeholder} placeholderTextColor={c.sub}
        accessibilityLabel={label} style={[input, { flex: 1, paddingLeft: 8 }]} autoCorrect={false} {...opts} />
    </View>
  );
  const chip = (selected: boolean) => ({ paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999,
    backgroundColor: selected ? c.accent : c.input });
  if (!loaded) return <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />;
  return (
    <Screen footer={<Button title={t("save")} icon="checkmark" onPress={() => save()} loading={busy} disabled={!valid} />}>
      <Stack.Screen options={{ title: isNew ? t("spoolNew") : t("spoolEdit", { id }) }} />
      {error ? <Banner kind="error" text={error} /> : null}
      {dbError ? <Banner kind="warn" text={dbError} /> : null}
      {nfcInfo ? <Banner kind="ok" icon="radio-outline" text={nfcInfo} /> : null}
      {scanning ? <Banner kind="info" icon="radio-outline" text={t("nfcHold")} /> : null}

      <Section footer={t("spoolDbHint")}>
        <Row icon="library-outline" label={t("spoolFromDb")} value={brand ?? undefined}
          onPress={() => { tap(); setDbError(""); setSheet("brand"); }} />
        {hasNfc ? (
          <>
            <Divider />
            {scanning
              ? <Row icon="close-circle-outline" label={t("nfcCancel")} onPress={() => { tap(); cancelScan(); }} />
              : <Row icon="radio-outline" label={t("nfcRead")} onPress={readTag} />}
          </>
        ) : null}
      </Section>

      <Section>
        {field(t("spoolVendor"), vendor, setVendor, { maxLength: 64 }, "Elegoo")}
        <Divider />
        {field(t("spoolName"), name, setName, { maxLength: 64 }, "Rapid PLA+ Black")}
      </Section>

      <Section title={t("spoolMaterial")}>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, padding: 12 }}>
          {MATERIALS.map(m => (
            <Pressable key={m} onPress={() => { tap(); setMaterial(m); }} style={chip(material === m)}
              accessibilityRole="radio" accessibilityState={{ selected: material === m }}>
              <Text style={{ color: material === m ? "#fff" : c.text, fontSize: 14 }}>{m}</Text>
            </Pressable>
          ))}
        </View>
        <Divider />
        {field(t("spoolOther"), material, setMaterial, { maxLength: 64, autoCapitalize: "characters" })}
      </Section>

      <Section title={t("spoolColor")}>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, padding: 12 }}>
          {COLORS.map(col => (
            <Pressable key={col} onPress={() => { tap(); setColor(col); }} accessibilityLabel={col} accessibilityRole="radio"
              accessibilityState={{ selected: hex === col }}
              style={{ width: 34, height: 34, borderRadius: 17, backgroundColor: col, borderWidth: hex === col ? 3 : 1,
                borderColor: hex === col ? c.accent : c.line }} />
          ))}
        </View>
        <Divider />
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          <View style={{ flex: 1 }}>{field("Hex", color, setColor, { autoCapitalize: "characters", maxLength: 7 }, "#RRGGBB")}</View>
          <View style={{ width: 26, height: 26, borderRadius: 13, marginRight: space, backgroundColor: hex ?? c.track,
            borderWidth: 1, borderColor: c.line }} />
        </View>
      </Section>

      <Section footer={t("spoolRemainingHint")}>
        <Row label={t("spoolWeight")} right={<TextInput value={weight} onChangeText={setWeight} keyboardType="decimal-pad"
          accessibilityLabel={t("spoolWeight")} placeholder="1000" placeholderTextColor={c.sub}
          style={{ color: c.text, fontSize: 16, minWidth: 80, textAlign: "right" }} />} />
        <Divider />
        <Row label={t("spoolRemaining")} right={<TextInput value={remaining} onChangeText={setRemaining} keyboardType="decimal-pad"
          accessibilityLabel={t("spoolRemaining")} placeholder={weight || "–"} placeholderTextColor={c.sub}
          style={{ color: c.text, fontSize: 16, minWidth: 80, textAlign: "right" }} />} />
      </Section>

      <Section>
        {field(t("spoolLocation"), location, setLocation, { maxLength: 64 })}
        <Divider />
        {field(t("spoolComment"), comment, setComment, { maxLength: 1024, multiline: true })}
      </Section>

      {!isNew ? (
        <Section>
          {hasNfc ? (
            <>
              <Row icon="radio-outline" label={t("nfcLinkChip")} sub={t("nfcLinkChipSub")} onPress={linking ? undefined : linkChip}
                right={linking ? <Button kind="plain" title={t("nfcCancel")} onPress={() => cancelScan()} /> : undefined} />
              <Divider />
            </>
          ) : null}
          <Row icon="copy-outline" label={t("spoolCopy")}
            onPress={() => router.replace({ pathname: "/spool/[id]", params: { id: "new", copy: id } })} />
          <Divider />
          <Row icon="archive-outline" label={t(archived ? "spoolUnarchive" : "spoolArchive")}
            onPress={() => save({ archived: !archived })} />
          <Divider />
          <Row icon="trash-outline" label={t("spoolDelete")} danger onPress={remove} />
        </Section>
      ) : null}
      <PickerSheet visible={sheet === "brand"} title={t("spoolVendor")} value={brand} searchLabel={t("search")} closeLabel="OK"
        choices={(brands ?? []).map(b => ({ value: b.name, label: b.name, sub: t("spoolDbCount", { n: b.count }) }))}
        onPick={v => { setBrand(v); setPresets(null); setTimeout(() => setSheet("filament"), 50); }}
        onClose={() => setSheet(s => (s === "brand" ? null : s))} />
      <PickerSheet visible={sheet === "filament" && !!presets} title={brand ?? ""} value={null} searchLabel={t("search")}
        closeLabel="OK" choices={presetChoices}
        onPick={v => { const p = presets?.[Number(v)]; if (p) applyPreset(p); }} onClose={() => setSheet(null)} />
      {(sheet === "brand" && !brands) || (sheet === "filament" && !presets) ? <ActivityIndicator color={c.accent} /> : null}
    </Screen>
  );
}
