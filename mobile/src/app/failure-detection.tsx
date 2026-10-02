// AI failure detection (server 0.23.0, own servers): Obico's ML API on the user's server checks camera pictures while
// printing. The server tests the setting (the ML API must fetch and check a test picture) before saving it.
import { useEffect, useState } from "react";
import { ActivityIndicator, Text, TextInput, View } from "react-native";

import { Banner, Button, Divider, Row, Screen, Section, Segmented, confirmAsync } from "@/components/ui";
import type { FailureConfig } from "@/lib/api";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

type Sens = "low" | "medium" | "high";
type Act = "notify" | "pause";

export default function FailureDetectionScreen() {
  const { api, server, t } = useApp();
  const c = useColors();
  const [cfg, setCfg] = useState<FailureConfig | null>(null);
  const [mlUrl, setMlUrl] = useState("");
  const [token, setToken] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [sens, setSens] = useState<Sens>("medium");
  const [action, setAction] = useState<Act>("notify");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  useEffect(() => {
    if (!api) return;
    api.failureConfig().then(x => {
      setCfg(x); setMlUrl(x.ml_url ?? ""); setSens(x.sensitivity); setAction(x.action);
      setServerUrl(x.server_url ?? server?.url ?? "");
    }).catch(e => { setError((e as Error).message); setCfg({ configured: false } as FailureConfig); });
  }, [api, server?.url]);

  const save = async () => {
    if (!api) return;
    setBusy(true); setError(""); setDone("");
    try {
      const r = await api.setFailureConfig({ ml_url: mlUrl.trim(), ...(token.trim() ? { ml_token: token.trim() } : {}),
        server_url: serverUrl.trim(), sensitivity: sens, action });
      setCfg(r); setToken(""); setDone(t("failureOk"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!api || !(await confirmAsync(t("failureRemove") + "?", t("del"), t("cancelBtn")))) return;
    try {
      const r = await api.removeFailureConfig();
      setCfg(x => (x ? { ...x, configured: r.configured } : x));
      setDone("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!cfg) return <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />;
  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  return (
    <Screen footer={<Button title={t("save")} icon="checkmark" onPress={save} loading={busy}
      disabled={!mlUrl.trim() || !serverUrl.trim()} />}>
      {error ? <Banner kind="error" text={error} /> : null}
      {done ? <Banner kind="ok" text={done} /> : null}
      <Section title={t("failureTitle")} footer={t("failureHint")}>
        <TextInput value={mlUrl} onChangeText={setMlUrl} placeholder="http://192.168.1.10:3333" placeholderTextColor={c.sub}
          autoCapitalize="none" autoCorrect={false} keyboardType="url" accessibilityLabel={t("failureMl")} style={input} />
        <Divider />
        <TextInput value={token} onChangeText={setToken} secureTextEntry autoCapitalize="none" autoCorrect={false}
          placeholder={cfg.token_set ? t("failureTokenKept") : t("failureToken")} placeholderTextColor={c.sub}
          accessibilityLabel={t("failureToken")} style={input} />
        <Divider />
        <View style={{ paddingHorizontal: space, paddingTop: 10 }}>
          <Text style={{ color: c.sub, fontSize: 13 }}>{t("failureServer")}</Text>
        </View>
        <TextInput value={serverUrl} onChangeText={setServerUrl} placeholder="http://192.168.1.10:8484" placeholderTextColor={c.sub}
          autoCapitalize="none" autoCorrect={false} keyboardType="url" accessibilityLabel={t("failureServer")} style={input} />
      </Section>
      <Section title={t("failureSensitivity")}>
        <View style={{ padding: 12 }}>
          <Segmented<Sens> values={["low", "medium", "high"]} value={sens} onChange={setSens}
            labels={{ low: t("sensLow"), medium: t("sensMedium"), high: t("sensHigh") }} />
        </View>
      </Section>
      <Section title={t("failureAction")} footer={t("failureNote")}>
        <View style={{ padding: 12 }}>
          <Segmented<Act> values={["notify", "pause"]} value={action} onChange={setAction}
            labels={{ notify: t("actionNotify"), pause: t("actionPause") }} />
        </View>
      </Section>
      {cfg.configured ? (
        <Section>
          <Row icon="trash-outline" label={t("failureRemove")} danger onPress={remove} />
        </Section>
      ) : null}
    </Screen>
  );
}
