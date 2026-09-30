// Printer settings: own OrcaSlicer printer profile (issue #2, spec PR-01/02).
import * as DocumentPicker from "expo-document-picker";
import { Stack, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Alert, Platform, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";

import { Banner, Button, Divider, Row, Screen, Section, tap } from "@/components/ui";
import type { Printer, PrinterProfile, UserProfile } from "@/lib/api";
import { useApp } from "@/lib/app";
import { useColors } from "@/lib/theme";

function confirmAsync(title: string, ok: string, cancel: string): Promise<boolean> {
  if (Platform.OS === "web") return Promise.resolve(globalThis.confirm?.(title) ?? true);
  return new Promise(resolve => Alert.alert(title, undefined, [
    { text: cancel, style: "cancel", onPress: () => resolve(false) },
    { text: ok, style: "destructive", onPress: () => resolve(true) },
  ], { cancelable: true, onDismiss: () => resolve(false) }));
}

export default function PrinterSettings() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const [printer, setPrinter] = useState<Printer | null>(null);
  const [current, setCurrent] = useState<PrinterProfile | null>(null);
  const [profiles, setProfiles] = useState<UserProfile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  useEffect(() => {
    if (!api) return;
    let alive = true;
    Promise.all([api.printers(), api.printerProfile(id), api.profiles()])
      .then(([ps, cur, list]) => {
        if (!alive) return;
        setPrinter(ps.find(p => p.id === id) ?? null);
        setCurrent(cur);
        setProfiles(list.filter(p => p.kind === "machine"));
      })
      .catch(e => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [api, id]);

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
      }
      setProfiles((await api.profiles()).filter(p => p.kind === "machine"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
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

      <Button title={t("uploadProfile")} icon="cloud-upload-outline" onPress={() => { tap(); upload(); }}
        loading={busy} disabled={!current} />
      {profiles.length ? (
        <Text style={{ color: c.sub, fontSize: 12, textAlign: "center", marginTop: 10 }}>{t("longPressDelete")}</Text>
      ) : null}
    </Screen>
  );
}
