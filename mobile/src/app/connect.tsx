// Onboarding: pair with the PrintShare server by QR code, deep link or manual entry.
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Platform, Text, TextInput, View } from "react-native";

import { Banner, Button, Card, Divider, Screen, Section } from "@/components/ui";
import { useApp } from "@/lib/app";
import { checkServer } from "@/lib/pairing";
import { space, useColors } from "@/lib/theme";

export default function Connect() {
  const { t, server, setServer } = useApp();
  const c = useColors();
  const router = useRouter();
  const params = useLocalSearchParams<{ url?: string; token?: string }>();
  const [url, setUrl] = useState(params.url ?? server?.url ?? "");
  const [token, setToken] = useState(params.token ?? server?.token ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const auto = useRef(false);

  const connect = async (u = url, tk = token) => {
    setBusy(true);
    setError("");
    try {
      await setServer(await checkServer({ url: u, token: tk }, t));
      if (router.canDismiss()) router.dismissAll();
      else router.replace("/");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // opened from a pairing link: connect right away
  useEffect(() => {
    if (params.url && !auto.current) {
      auto.current = true;
      setUrl(params.url);
      setToken(params.token ?? "");
      connect(params.url, params.token ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.url, params.token]);

  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  const mono = Platform.select({ ios: "Menlo", default: "monospace" });
  return (
    <Screen>
      <Text style={{ color: c.sub, fontSize: 16, lineHeight: 22, marginBottom: 20 }}>{t("connectSub")}</Text>
      {error ? <Banner kind="error" text={error} /> : null}

      {Platform.OS !== "web" ? (
        <>
          <Button title={t("scanQr")} icon="qr-code-outline" onPress={() => router.push("/scan")} />
          <Text style={{ color: c.sub, fontSize: 13, marginTop: 12, marginHorizontal: 4 }}>{t("scanHelp")}</Text>
          <Card style={{ padding: 12, marginTop: 6, marginBottom: 28 }}>
            <Text selectable style={{ color: c.text, fontFamily: mono, fontSize: 12 }}>
              docker exec printshare printshare pair --url http://SERVER-IP:8484
            </Text>
          </Card>
        </>
      ) : null}

      <Section title={t("manual")}>
        <TextInput value={url} onChangeText={setUrl} placeholder={`${t("serverUrl")} – http://192.168.1.10:8484`}
          placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} keyboardType="url"
          accessibilityLabel={t("serverUrl")} style={input} />
        <Divider />
        <TextInput value={token} onChangeText={setToken} placeholder={t("token")} placeholderTextColor={c.sub}
          autoCapitalize="none" autoCorrect={false} secureTextEntry accessibilityLabel={t("token")} style={input}
          onSubmitEditing={() => connect()} returnKeyType="go" />
      </Section>
      <View>
        <Button title={busy ? t("connecting") : t("connect")} icon="link" onPress={() => connect()}
          loading={busy} disabled={!url.trim()} />
      </View>
    </Screen>
  );
}
