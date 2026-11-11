// Pairing code for another phone (issue #10): QR code with the server's address(es) and access token. Own servers only.
// Was on the classic web page alone until 0.53.0. The QR is hidden until asked for - it holds the token.
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, TextInput, View } from "react-native";
import { SvgXml } from "react-native-svg";

import { Banner, Button, Divider, Screen, Section, tap } from "@/components/ui";
import type { Pairing } from "@/lib/api";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

export default function PairAppScreen() {
  const { api, t } = useApp();
  const c = useColors();
  const [url, setUrl] = useState<string | null>(null);
  const [remote, setRemote] = useState("");
  const [code, setCode] = useState<Pairing | null>(null);
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const asked = useRef(0);

  // first: the server's own guess (PRINTSHARE_URL, HA server_url, else this page's address)
  useEffect(() => {
    if (!api) return;
    api.pairing().then(p => { setCode(p); setUrl(p.url); setRemote(p.remote_url ?? ""); })
      .catch(e => setError((e as Error).message));
  }, [api]);

  // edited addresses: ask again after a short pause; a stale code is cleared on an error
  useEffect(() => {
    if (!api || url === null || (code && url === code.url && remote === (code.remote_url ?? ""))) return;
    const n = ++asked.current;
    const timer = setTimeout(() => {
      api.pairing(url.trim(), remote.trim())
        .then(p => { if (n === asked.current) { setCode(p); setError(""); } })
        .catch(e => { if (n === asked.current) { setCode(null); setError((e as Error).message); } });
    }, 500);
    return () => clearTimeout(timer);
  }, [api, url, remote]); // eslint-disable-line react-hooks/exhaustive-deps

  if (url === null && !error) return <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />;
  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  const warnings = code?.warnings ?? [];
  return (
    <Screen>
      {error ? <Banner kind="error" text={error} /> : null}
      {warnings.includes("localhost") ? <Banner kind="warn" text={t("pairLocalhost")} /> : null}
      {warnings.includes("ingress") ? <Banner kind="warn" text={t("pairIngress")} /> : null}
      <Section title={t("pairAppTitle")} footer={t("pairAppHint")}>
        <TextInput value={url ?? ""} onChangeText={setUrl} placeholder={t("pairUrl")} placeholderTextColor={c.sub}
          autoCapitalize="none" autoCorrect={false} keyboardType="url" accessibilityLabel={t("pairUrl")} style={input} />
        <Divider />
        <TextInput value={remote} onChangeText={setRemote} placeholder={t("pairRemote")} placeholderTextColor={c.sub}
          autoCapitalize="none" autoCorrect={false} keyboardType="url" accessibilityLabel={t("pairRemote")} style={input} />
      </Section>
      <Button title={show ? t("pairHide") : t("pairShow")} icon={show ? "eye-off-outline" : "qr-code-outline"}
        kind={show ? "secondary" : "primary"} disabled={!code} onPress={() => { tap(); setShow(s => !s); }} />
      {show && code ? (
        <View style={{ marginTop: 22, alignItems: "center", gap: 14 }}>
          <View style={{ backgroundColor: "#fff", padding: 8, borderRadius: 12, width: 280, height: 280 }}>
            <SvgXml xml={code.svg} width="100%" height="100%" />
          </View>
          <Text selectable style={{ color: c.sub, fontSize: 13, textAlign: "center", paddingHorizontal: space }}>
            {t("pairManual", { url: code.url, token: code.token,
              remote: code.remote_url ? t("pairManualRemote", { remote: code.remote_url }) : "" })}
          </Text>
        </View>
      ) : null}
    </Screen>
  );
}
