// "Open in PocketPrint3D" from a CAD program (SolidCraft, server 0.48.0): the CAD program uploads the model with this
// key and opens the prepare page in the browser. Own servers use their access token, the cloud one key per account.
import * as Clipboard from "expo-clipboard";
import { Stack } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { Banner, Button, Divider, Row, Screen, Section, confirmAsync } from "@/components/ui";
import { ImportKey, errorText } from "@/lib/api";
import { useApp } from "@/lib/app";
import { ago } from "@/lib/format";
import { space, useColors } from "@/lib/theme";

export default function ImportKeyScreen() {
  const { api, t } = useApp();
  const c = useColors();
  const [state, setState] = useState<ImportKey | null>(null);
  const [key, setKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");

  const load = useCallback(() => {
    if (!api) return;
    api.importKey().then(setState).catch(e => setError(errorText(t, e)));
  }, [api, t]);
  useEffect(load, [load]);

  const create = async () => {
    if (!api) return;
    if (state?.enabled && !state.server_token && !(await confirmAsync(t("orcaRenewQ"), t("orcaRenew"), t("cancelBtn")))) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.createImportKey();
      setKey(r.key);
      setState({ ...r, created: Date.now() / 1000, last_used: null });
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!api || !(await confirmAsync(t("importOffQ"), t("orcaOff"), t("cancelBtn")))) return;
    try {
      await api.deleteImportKey();
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
  const own = !!state?.server_token;
  const showAccess = state && (key !== null || (state.enabled && !own));
  return (
    <Screen>
      <Stack.Screen options={{ title: t("importTitle") }} />
      <Text style={{ color: c.sub, fontSize: 15, lineHeight: 21, marginBottom: 16 }}>{t("importIntro")}</Text>
      {error ? <Banner kind="error" text={error} /> : null}
      {!state ? <ActivityIndicator color={c.accent} /> : null}

      {showAccess ? (
        <Section title={t("importAccess")} footer={key && !own ? t("orcaKeyOnce") : undefined}>
          <Row icon="link-outline" label={t("importUrl")} value={copied === "url" ? t("copied") : undefined}
            onPress={() => copy("url", state.url)} />
          <Text selectable style={mono}>{state.url}</Text>
          <Divider />
          {key !== null ? (
            <>
              <Row icon="key-outline" label={t("orcaKey")} value={copied === "key" ? t("copied") : undefined}
                onPress={key ? () => copy("key", key) : undefined} />
              <Text selectable style={mono}>{key || t("importNoKey")}</Text>
            </>
          ) : (
            <Row icon="key-outline" label={t("orcaKey")}
              sub={[t("orcaKeySet"), state.last_used ? t("orcaLastUsed", { v: ago(t, state.last_used) }) : t("orcaNeverUsed")].join(" · ")} />
          )}
        </Section>
      ) : null}

      {state ? (
        <Section title={t("importSteps")}>
          <Text style={{ color: c.text, fontSize: 15, lineHeight: 23, padding: space }}>{t("importHowTo")}</Text>
        </Section>
      ) : null}

      {state ? (
        <View style={{ gap: 10 }}>
          {own ? (key === null ? <Button title={t("importShowToken")} icon="key-outline" onPress={create} loading={busy} /> : null) : (
            <Button title={t(state.enabled ? "orcaRenew" : "orcaCreate")} icon="key-outline" onPress={create} loading={busy}
              kind={state.enabled ? "secondary" : "primary"} />
          )}
          {state.enabled && !own ? <Button kind="danger" title={t("orcaOff")} icon="close-circle-outline" onPress={remove} /> : null}
        </View>
      ) : null}
    </Screen>
  );
}
