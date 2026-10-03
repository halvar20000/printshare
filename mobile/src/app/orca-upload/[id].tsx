// Cloud: send from OrcaSlicer on the computer (docs/WEB.md step 3). OrcaSlicer's physical printer "Octo/Klipper" uploads
// to PocketPrint3D with this printer's key: the G-code becomes a job here and its spool is booked.
import * as Clipboard from "expo-clipboard";
import { Stack, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { Banner, Button, Divider, Row, Screen, Section, confirmAsync } from "@/components/ui";
import { errorText } from "@/lib/api";
import { useApp } from "@/lib/app";
import { ago } from "@/lib/format";
import { space, useColors } from "@/lib/theme";

type State = { enabled: boolean; url: string; created?: number; last_used?: number | null };

export default function OrcaUpload() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const [state, setState] = useState<State | null>(null);
  const [key, setKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");

  const load = useCallback(() => {
    if (!api) return;
    api.orcaUpload(id).then(setState).catch(e => setError(errorText(t, e)));
  }, [api, id, t]);
  useEffect(load, [load]);

  const create = async () => {
    if (!api) return;
    if (state?.enabled && !(await confirmAsync(t("orcaRenewQ"), t("orcaRenew"), t("cancelBtn")))) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.createOrcaUpload(id);
      setKey(r.key);
      setState({ enabled: true, url: r.url, created: Date.now() / 1000, last_used: null });
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!api || !(await confirmAsync(t("orcaOffQ"), t("orcaOff"), t("cancelBtn")))) return;
    try {
      await api.deleteOrcaUpload(id);
      setKey(null);
      load();
    } catch (e) {
      setError(errorText(t, e));
    }
  };
  const copy = async (what: string, value: string) => {
    await Clipboard.setStringAsync(value);
    setCopied(what);
    setTimeout(() => setCopied(""), 2000);
  };

  const mono = { color: c.text, fontSize: 15, fontFamily: "monospace" as const, padding: space, paddingTop: 0 };
  return (
    <Screen>
      <Stack.Screen options={{ title: t("orcaTitle") }} />
      <Text style={{ color: c.sub, fontSize: 15, lineHeight: 21, marginBottom: 16 }}>{t("orcaIntro", { printer: name ?? id })}</Text>
      {error ? <Banner kind="error" text={error} /> : null}
      {!state ? <ActivityIndicator color={c.accent} /> : null}

      <Section title={t("orcaWhyTitle")} footer={t("orcaWhyNot")}>
        <Text style={{ color: c.text, fontSize: 15, lineHeight: 22, padding: space }}>{t("orcaWhy")}</Text>
      </Section>

      {state && (key || state.enabled) ? (
        <Section title={t("orcaAccess")} footer={key ? t("orcaKeyOnce") : undefined}>
          <Row icon="link-outline" label={t("orcaUrl")} value={copied === "url" ? t("copied") : undefined}
            onPress={() => copy("url", state.url)} />
          <Text selectable style={mono}>{state.url}</Text>
          <Divider />
          {key ? (
            <>
              <Row icon="key-outline" label={t("orcaKey")} value={copied === "key" ? t("copied") : undefined}
                onPress={() => copy("key", key)} />
              <Text selectable style={mono}>{key}</Text>
            </>
          ) : (
            <Row icon="key-outline" label={t("orcaKey")}
              sub={[t("orcaKeySet"), state.last_used ? t("orcaLastUsed", { v: ago(t, state.last_used) }) : t("orcaNeverUsed")].join(" · ")} />
          )}
        </Section>
      ) : null}

      {state ? (
        <Section title={t("orcaSteps")}>
          <Text style={{ color: c.text, fontSize: 15, lineHeight: 23, padding: space }}>{t("orcaHowTo")}</Text>
        </Section>
      ) : null}
      {state ? <Text style={{ color: c.sub, fontSize: 13, lineHeight: 19, marginTop: -8, marginBottom: 20, marginHorizontal: 16 }}>
        {t("orcaPrintNote")}</Text> : null}

      {state ? (
        <View style={{ gap: 10 }}>
          <Button title={t(state.enabled ? "orcaRenew" : "orcaCreate")} icon="key-outline" onPress={create} loading={busy}
            kind={state.enabled ? "secondary" : "primary"} />
          {state.enabled ? <Button kind="danger" title={t("orcaOff")} icon="close-circle-outline" onPress={remove} /> : null}
        </View>
      ) : null}
    </Screen>
  );
}
