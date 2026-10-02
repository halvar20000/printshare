// One cloud spool (server 0.17.0): brand, name, material, colour, weights, location; copy, archive, delete.
// id "new" adds one; ?copy=<id> starts from an existing spool (a stack of identical spools).
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";

import { Banner, Button, Divider, Row, Screen, Section, confirmAsync, tap } from "@/components/ui";
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
  const { id, copy } = useLocalSearchParams<{ id: string; copy?: string }>();
  const isNew = id === "new";
  const { server, t } = useApp();
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

  const hex = /^#?[0-9A-Fa-f]{6}$/.test(color.trim()) ? `#${color.trim().replace("#", "").toUpperCase()}` : null;
  const valid = !!hex && (weight.trim() === "" || num(weight) != null) && (remaining.trim() === "" || num(remaining) != null);

  const save = async (extra: Partial<SpoolInput> = {}) => {
    if (!server) return;
    setBusy(true);
    setError("");
    const body: SpoolInput = {
      filament: { vendor: vendor.trim() || null, name: name.trim() || null, material: material.trim() || null,
                  color_hex: hex, weight: num(weight) },
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
          <Row icon="copy-outline" label={t("spoolCopy")}
            onPress={() => router.replace({ pathname: "/spool/[id]", params: { id: "new", copy: id } })} />
          <Divider />
          <Row icon="archive-outline" label={t(archived ? "spoolUnarchive" : "spoolArchive")}
            onPress={() => save({ archived: !archived })} />
          <Divider />
          <Row icon="trash-outline" label={t("spoolDelete")} danger onPress={remove} />
        </Section>
      ) : null}
    </Screen>
  );
}
