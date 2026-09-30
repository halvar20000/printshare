import Constants from "expo-constants";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Linking, Platform, Text, View } from "react-native";

import { Badge, Divider, Row, Screen, Section, Segmented } from "@/components/ui";
import type { Printer } from "@/lib/api";
import { useApp } from "@/lib/app";
import type { LangPref } from "@/lib/i18n";
import { useColors } from "@/lib/theme";

export default function Settings() {
  const { server, api, t, langPref, setLangPref, setServer } = useApp();
  const c = useColors();
  const router = useRouter();
  const [online, setOnline] = useState<boolean | null>(null);
  const [serverVersion, setServerVersion] = useState("");
  const [route, setRoute] = useState<"home" | "remote" | null>(null);
  const [printers, setPrinters] = useState<Printer[]>([]);

  useFocusEffect(useCallback(() => {
    if (!api) { setOnline(null); return; }
    api.printers().then(setPrinters).catch(() => setPrinters([]));
    api.info().then(i => { setOnline(true); setServerVersion(i.version); setRoute(api.route()); })
      .catch(() => { setOnline(false); setRoute(null); });
  }, [api]));

  const disconnect = () => {
    const run = () => setServer(null);
    if (Platform.OS === "web") { if (globalThis.confirm?.(t("disconnectQ"))) run(); return; }
    Alert.alert(t("disconnectQ"), undefined, [
      { text: t("cancelBtn"), style: "cancel" },
      { text: t("disconnect"), style: "destructive", onPress: run },
    ]);
  };

  return (
    <Screen>
      <Section title={t("server")}>
        <Row icon="server-outline" label={server ? server.url.replace(/^https?:\/\//, "") : t("notConnected")}
          sub={server && serverVersion ? [`PrintShare ${serverVersion}`, route ? t(route === "home" ? "routeHome" : "routeRemote") : null]
            .filter(Boolean).join(" · ") : undefined}
          right={server ? <Badge text={online === false ? t("offline") : online ? t("connected") : "…"}
            kind={online === false ? "error" : online ? "ok" : "neutral"} /> : null} />
        {server?.remoteUrl ? <><Divider /><Row icon="globe-outline" label={t("remoteUrl")}
          sub={server.remoteUrl.replace(/^https?:\/\//, "")} /></> : null}
        <Divider />
        <Row icon="qr-code-outline" label={server ? t("changeServer") : t("connectNow")} onPress={() => router.push("/connect")} />
        {server ? <><Divider /><Row icon="log-out-outline" label={t("disconnect")} danger onPress={disconnect} /></> : null}
      </Section>

      {server && printers.length ? (
        <Section title={t("tabPrinters")}>
          {printers.map((p, i) => (
            <View key={p.id}>
              {i ? <Divider /> : null}
              <Row icon="print-outline" label={p.name} sub={t("printerProfile")}
                onPress={() => router.push({ pathname: "/printer/[id]", params: { id: p.id } })} />
            </View>
          ))}
        </Section>
      ) : null}

      <Section title={t("language")}>
        <View style={{ padding: 12 }}>
          <Segmented<LangPref> values={["auto", "de", "en"]} value={langPref} onChange={setLangPref}
            labels={{ auto: t("langAuto"), de: "Deutsch", en: "English" }} />
        </View>
      </Section>

      <Section title={t("about")} footer={t("aboutText")}>
        <Row icon="information-circle-outline" label={t("version")} value={Constants.expoConfig?.version ?? "–"} />
        <Divider />
        <Row icon="logo-github" label={t("sourceCode")} onPress={() => Linking.openURL("https://github.com/halvar20000/printshare")} />
      </Section>
      <Text style={{ color: c.sub, textAlign: "center", fontSize: 12 }}>PrintShare · MIT</Text>
    </Screen>
  );
}
