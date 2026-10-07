// Printer settings: own OrcaSlicer printer profile (issue #2, spec PR-01/02), uploaded or from an Orca Cloud share link (#7).
import * as DocumentPicker from "expo-document-picker";
import { Stack, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Text, TextInput, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";

import { Banner, Button, Divider, Row, Screen, Section, confirmAsync, tap } from "@/components/ui";
import type { Printer, PrinterProfile, UserProfile } from "@/lib/api";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

export default function PrinterSettings() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const [printer, setPrinter] = useState<Printer | null>(null);
  const [current, setCurrent] = useState<PrinterProfile | null>(null);
  const [allProfiles, setProfiles] = useState<UserProfile[]>([]);
  const profiles = allProfiles.filter(p => p.kind === "machine");
  const ownPresets = allProfiles.filter(p => p.kind === "process" || p.kind === "filament");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [orcaLink, setOrcaLink] = useState("");
  const [importing, setImporting] = useState(false);

  // on focus: presets synced from Orca Cloud on the next screen show up when coming back
  useFocusEffect(useCallback(() => {
    if (!api) return;
    let alive = true;
    Promise.all([api.printers(), api.printerProfile(id), api.profiles()])
      .then(([ps, cur, list]) => {
        if (!alive) return;
        setPrinter(ps.find(p => p.id === id) ?? null);
        setCurrent(cur);
        setProfiles(list);
      })
      .catch(e => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [api, id]));

  const use = async (file: string | null) => {
    if (!api) return;
    setBusy(true);
    setError("");
    setDone("");
    try {
      setCurrent(await api.setPrinterProfile(id, file));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const upload = async () => {
    if (!api) return;
    const res = await DocumentPicker.getDocumentAsync({ type: "*/*", copyToCacheDirectory: true, multiple: false });
    if (res.canceled || !res.assets?.[0]) return;
    const a = res.assets[0];
    setBusy(true);
    setError("");
    setDone("");
    try {
      const stored = await api.uploadProfile(a.uri, a.name);
      const machine = stored.find(p => p.kind === "machine");
      if (machine) {
        // the usual case: one printer preset -> use it for this printer right away (issue #2)
        setCurrent(await api.setPrinterProfile(id, machine.file));
        setDone(t("profileUploaded", { name: machine.name ?? machine.file, printer: printer?.name ?? id }));
      } else if (stored.length) {
        setDone(t("profileStoredOther", { names: stored.map(p => p.name ?? p.file).join(", ") }));
      }
      setProfiles(await api.profiles());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const importOrca = async () => {
    if (!api || !current) return;
    setImporting(true);
    setError("");
    setDone("");
    try {
      const r = await api.importOrcaCloud(orcaLink.trim());
      const lines = [t("orcaCloudDone", { bundle: r.bundle.name ?? "Orca Cloud", n: r.imported.length })];
      if (r.skipped.length) lines.push(t("orcaCloudSkipped", { n: r.skipped.length }));
      // one printer preset made for this printer's model: use it right away; several (nozzles, AFC …): the user picks
      const fitting = r.imported.filter(p => p.kind === "machine" && p.inherits === current.machine);
      if (fitting.length === 1) {
        setCurrent(await api.setPrinterProfile(id, fitting[0].file));
        lines.push(t("profileUploaded", { name: fitting[0].name ?? fitting[0].file, printer: printer?.name ?? id }));
      } else if (r.imported.some(p => p.kind === "machine")) {
        lines.push(t("orcaCloudChoose"));
      }
      setDone(lines.join(" "));
      setOrcaLink("");
      setProfiles(await api.profiles());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setImporting(false);
    }
  };

  const remove = async (p: UserProfile) => {
    if (!api || !(await confirmAsync(t("deleteProfileQ", { name: p.name ?? p.file }), t("del"), t("cancelBtn")))) return;
    try {
      await api.deleteProfile(p.file);
      setProfiles(list => list.filter(x => x.file !== p.file));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const describe = (p: UserProfile) => [p.inherits ? t("basedOn", { name: p.inherits }) : null,
    p.print_start ? t("ownStartCode") : null].filter(Boolean).join(" · ");
  const check = <Ionicons name="checkmark" size={22} color={c.accent} />;

  return (
    <Screen>
      <Stack.Screen options={{ title: printer?.name ?? "" }} />
      {error ? <Banner kind="error" text={error} /> : null}
      {done ? <Banner kind="ok" text={done} /> : null}

      <Section title={t("printerProfile")} footer={t("profileHelp")}>
        {current ? (
          <>
            <Row icon="cube-outline" label={t("useStandardProfile")}
              sub={[t("standardProfileSub", { name: current.machine }),
                current.machine_preset === "cosmos" && !current.machine_file ? t("builtInCosmos") : null,
                current.config_file ? t("configFile", { name: current.config_file }) : null].filter(Boolean).join(" · ")}
              right={!current.machine_file ? check : null}
              chevron={false} onPress={current.machine_file ? () => use(null) : undefined} />
            {profiles.map(p => (
              <View key={p.file}>
                <Divider />
                <Row icon="document-text-outline" label={p.name ?? p.file} sub={describe(p) || undefined}
                  right={current.machine_file === p.file ? check : null} chevron={false}
                  onPress={current.machine_file === p.file ? undefined : () => use(p.file)}
                  onLongPress={() => remove(p)} />
              </View>
            ))}
          </>
        ) : <ActivityIndicator color={c.accent} style={{ margin: 16 }} />}
      </Section>

      {ownPresets.length ? (
        <Section title={t("ownPresetsTitle")} footer={t("ownPresetsHelp")}>
          {ownPresets.map((p, i) => (
            <View key={p.file}>
              {i ? <Divider /> : null}
              <Row icon={p.kind === "filament" ? "color-fill-outline" : "speedometer-outline"} label={p.name ?? p.file}
                sub={[t.table.kindNames[p.kind] ?? p.kind, p.inherits ? t("basedOn", { name: p.inherits }) : null]
                  .filter(Boolean).join(" · ")}
                chevron={false} onLongPress={() => remove(p)} />
            </View>
          ))}
        </Section>
      ) : null}

      <Section title={t("orcaCloudTitle")} footer={t("orcaCloudHint")}>
        <TextInput value={orcaLink} onChangeText={setOrcaLink} placeholder="https://cloud.orcaslicer.com/b/…"
          placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} keyboardType="url"
          accessibilityLabel={t("orcaCloudTitle")}
          style={{ color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 }} />
        <Divider />
        <View style={{ padding: space }}>
          <Button kind="secondary" title={t("orcaCloudImport")} icon="cloud-download-outline"
            onPress={() => { tap(); importOrca(); }} loading={importing}
            disabled={!current || !/cloud\.orcaslicer\.com\/b\//.test(orcaLink)} />
        </View>
      </Section>

      <Section footer={t("orcaAccountSub")}>
        <Row icon="sync-outline" label={t("orcaAccountTitle")} onPress={() => router.push("/orca-account")} />
      </Section>

      <Button title={t("uploadProfile")} icon="cloud-upload-outline" onPress={() => { tap(); upload(); }}
        loading={busy} disabled={!current} />
      {allProfiles.length ? (
        <Text style={{ color: c.sub, fontSize: 12, textAlign: "center", marginTop: 10 }}>{t("longPressDelete")}</Text>
      ) : null}
    </Screen>
  );
}
