// Own Manyfold library (server 0.21.0, own servers only): address + API key; the server checks them before saving.
// Its models then show up as a search source in "Entdecken".
import { useEffect, useState } from "react";
import { ActivityIndicator, Linking, Text, TextInput, View } from "react-native";

import { Banner, Button, Divider, Row, Screen, Section, confirmAsync } from "@/components/ui";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

export default function ManyfoldScreen() {
  const { api, t } = useApp();
  const c = useColors();
  const [loaded, setLoaded] = useState(false);
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [state, setState] = useState<{ configured: boolean; url: string | null; token_set: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  useEffect(() => {
    if (!api) return;
    api.manyfoldConfig()
      .then(s => { setState(s); setUrl(s.url ?? ""); setLoaded(true); })
      .catch(e => { setError((e as Error).message); setLoaded(true); });
  }, [api]);

  const save = async () => {
    if (!api) return;
    setBusy(true); setError(""); setDone("");
    try {
      const r = await api.setManyfold(url.trim(), key.trim() || undefined);
      setState({ configured: true, url: r.url, token_set: true });
      setKey("");
      setDone(t("manyfoldOk", { n: r.models }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!api || !(await confirmAsync(t("manyfoldRemoveQ"), t("del"), t("cancelBtn")))) return;
    try {
      const r = await api.removeManyfold();
      setState(s => (s ? { ...s, configured: r.configured, token_set: false } : s));
      setDone("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!loaded) return <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />;
  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  return (
    <Screen footer={<Button title={t("save")} icon="checkmark" onPress={save} loading={busy}
      disabled={!url.trim() || (!key.trim() && !state?.token_set)} />}>
      {error ? <Banner kind="error" text={error} /> : null}
      {done ? <Banner kind="ok" text={done} /> : null}
      <Section title={t("manyfoldAddress")} footer={t("manyfoldHint")}>
        <TextInput value={url} onChangeText={setUrl} placeholder="http://192.168.1.20:3214" placeholderTextColor={c.sub}
          autoCapitalize="none" autoCorrect={false} keyboardType="url" accessibilityLabel={t("manyfoldAddress")} style={input} />
        <Divider />
        <TextInput value={key} onChangeText={setKey} secureTextEntry autoCapitalize="none" autoCorrect={false}
          placeholder={state?.token_set ? t("manyfoldKeyKept") : t("manyfoldKey")} placeholderTextColor={c.sub}
          accessibilityLabel={t("manyfoldKey")} style={input} />
      </Section>
      {state?.configured ? (
        <Section>
          <Row icon="trash-outline" label={t("manyfoldRemove")} danger onPress={remove} />
        </Section>
      ) : null}
      <View style={{ paddingHorizontal: 16 }}>
        <Text style={{ color: c.accent, fontSize: 14 }} onPress={() => Linking.openURL("https://manyfold.app")}>manyfold.app</Text>
      </View>
    </Screen>
  );
}
