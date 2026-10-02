// Onboarding: log in to the PocketPrint3D cloud by e-mail code, or pair an own server by QR code, deep link or
// manual entry.
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Platform, Text, TextInput, View } from "react-native";

import { Banner, Button, Card, Divider, Screen, Section, Segmented } from "@/components/ui";
import { CLOUD_URL, cloudLogin, cloudRequestCode, WEB_APP } from "@/lib/api";
import { useApp } from "@/lib/app";
import { checkServer } from "@/lib/pairing";
import { space, useColors } from "@/lib/theme";

export default function Connect() {
  const { t, server, setServer } = useApp();
  const c = useColors();
  const router = useRouter();
  const params = useLocalSearchParams<{ url?: string; token?: string; remote?: string; mode?: string }>();
  const [url, setUrl] = useState(params.url ?? server?.url ?? "");
  const [remote, setRemote] = useState(params.remote ?? server?.remoteUrl ?? "");
  const [token, setToken] = useState(params.token ?? server?.token ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const auto = useRef(false);
  const [mode, setMode] = useState<"cloud" | "own">(!WEB_APP && (params.url || params.mode === "own" || (server && !server.cloud)) ? "own" : "cloud");
  const [email, setEmail] = useState(server?.email ?? "");
  const [code, setCode] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);

  const done = () => {
    if (router.canDismiss()) router.dismissAll();
    else router.replace("/");
  };
  const requestCode = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await cloudRequestCode(t, email);
      setSentTo(r.email);
      setCode("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const login = async () => {
    if (!sentTo) return;
    setBusy(true);
    setError("");
    try {
      const r = await cloudLogin(t, sentTo, code);
      await setServer({ url: CLOUD_URL, token: r.token ?? "", cloud: true, email: r.user.email });
      done();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const connect = async (u = url, tk = token, r = remote) => {
    setBusy(true);
    setError("");
    try {
      await setServer(await checkServer({ url: u, token: tk, remoteUrl: r }, t));
      done();
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
      setRemote(params.remote ?? "");
      connect(params.url, params.token ?? "", params.remote ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.url, params.token, params.remote]);

  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  const mono = Platform.select({ ios: "Menlo", default: "monospace" });
  return (
    <Screen>
      {!WEB_APP ? (
        // the web app on app.pocketprint3d.com is the cloud only (an own server has its own web page)
        <View style={{ marginBottom: 20 }}>
          <Segmented<"cloud" | "own"> values={["cloud", "own"]} value={mode} onChange={m => { setMode(m); setError(""); }}
            labels={{ cloud: t("modeCloud"), own: t("modeOwn") }} />
        </View>
      ) : null}
      {error ? <Banner kind="error" text={error} /> : null}

      {mode === "cloud" ? (
        <>
          <Text style={{ color: c.sub, fontSize: 16, lineHeight: 22, marginBottom: 20 }}>{t(WEB_APP ? "cloudIntroWeb" : "cloudIntro")}</Text>
          {!sentTo ? (
            <>
              <Section title={t("email")}>
                <TextInput value={email} onChangeText={setEmail} placeholder="name@example.com" placeholderTextColor={c.sub}
                  autoCapitalize="none" autoCorrect={false} keyboardType="email-address" autoComplete="email"
                  textContentType="emailAddress" accessibilityLabel={t("email")} style={input}
                  onSubmitEditing={requestCode} returnKeyType="send" />
              </Section>
              <Button title={t("sendCode")} icon="mail-outline" onPress={requestCode} loading={busy}
                disabled={!email.includes("@")} />
            </>
          ) : (
            <>
              <Text style={{ color: c.text, fontSize: 16, lineHeight: 22, marginBottom: 16 }}>{t("codeSent", { email: sentTo })}</Text>
              <Section title={t("code")}>
                <TextInput value={code} onChangeText={v => setCode(v.replace(/\D/g, "").slice(0, 6))} placeholder="123456"
                  placeholderTextColor={c.sub} keyboardType="number-pad" autoComplete="one-time-code"
                  textContentType="oneTimeCode" maxLength={6} accessibilityLabel={t("code")}
                  style={[input, { fontSize: 24, letterSpacing: 8, textAlign: "center" }]}
                  onSubmitEditing={login} returnKeyType="go" autoFocus />
              </Section>
              <Button title={t("login")} icon="log-in-outline" onPress={login} loading={busy} disabled={code.length !== 6} />
              <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
                <Button kind="plain" title={t("otherEmail")} onPress={() => { setSentTo(null); setError(""); }} style={{ flex: 1 }} />
                <Button kind="plain" title={t("resendCode")} onPress={requestCode} disabled={busy} style={{ flex: 1 }} />
              </View>
            </>
          )}
          <Text style={{ color: c.sub, fontSize: 13, lineHeight: 18, marginTop: 20, marginHorizontal: 4 }}>{t("cloudPrivacy")}</Text>
        </>
      ) : null}

      {mode === "own" ? <Text style={{ color: c.sub, fontSize: 16, lineHeight: 22, marginBottom: 20 }}>{t("connectSub")}</Text> : null}
      {mode === "own" && Platform.OS !== "web" ? (
        <>
          <Button title={t("scanQr")} icon="qr-code-outline" onPress={() => router.push("/scan")} />
          <Text style={{ color: c.sub, fontSize: 13, marginTop: 12, marginHorizontal: 4 }}>{t("scanHelp")}</Text>
          <Card style={{ padding: 12, marginTop: 6, marginBottom: 8 }}>
            <Text selectable style={{ color: c.text, fontFamily: mono, fontSize: 12 }}>
              docker exec PrintShare printshare pair --url http://SERVER-IP:8484
            </Text>
          </Card>
          <Text style={{ color: c.sub, fontSize: 13, marginBottom: 28, marginHorizontal: 4 }}>{t("pairCmdHint")}</Text>
        </>
      ) : null}

      {mode === "own" ? (<>
      <Section title={t("manual")}>
        <TextInput value={url} onChangeText={setUrl} placeholder={`${t("serverUrl")} – http://192.168.1.10:8484`}
          placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} keyboardType="url"
          accessibilityLabel={t("serverUrl")} style={input} />
        <Divider />
        <TextInput value={remote} onChangeText={setRemote} placeholder={`${t("remoteUrl")} – http://100.x.y.z:8484`}
          placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} keyboardType="url"
          accessibilityLabel={t("remoteUrl")} style={input} />
        <Divider />
        <TextInput value={token} onChangeText={setToken} placeholder={t("token")} placeholderTextColor={c.sub}
          autoCapitalize="none" autoCorrect={false} secureTextEntry accessibilityLabel={t("token")} style={input}
          onSubmitEditing={() => connect()} returnKeyType="go" />
      </Section>
      <Text style={{ color: c.sub, fontSize: 13, lineHeight: 18, marginTop: -12, marginBottom: 20, marginHorizontal: 16 }}>
        {t("remoteHint")}
      </Text>
      <View>
        <Button title={busy ? t("connecting") : t("connect")} icon="link" onPress={() => connect()}
          loading={busy} disabled={!url.trim()} />
      </View>
      </>) : null}
    </Screen>
  );
}
