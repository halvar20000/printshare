import Constants from "expo-constants";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Linking, Platform, Switch, Text, View } from "react-native";

import { Badge, Divider, Row, Screen, Section, Segmented, confirmAsync, tap } from "@/components/ui";
import { WEB_APP, type Me, type Printer } from "@/lib/api";
import { useApp } from "@/lib/app";
import type { LangPref } from "@/lib/i18n";
import { CLOUD_SPOOLS, loadSpoolmanUrl } from "@/lib/spoolman";
import { loadTimelapseAlways, saveTimelapseAlways, serverTimelapseAlways } from "@/lib/timelapse";
import { useColors } from "@/lib/theme";

export default function Settings() {
  const { server, api, t, langPref, setLangPref, setServer } = useApp();
  const c = useColors();
  const router = useRouter();
  const [online, setOnline] = useState<boolean | null>(null);
  const [serverVersion, setServerVersion] = useState("");
  const [route, setRoute] = useState<"home" | "remote" | null>(null);
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [spoolman, setSpoolman] = useState<string | null>(null);
  // "always make a time-lapse" (server 0.40.0); `tlOld` = own server without the setting
  const [tlAlways, setTlAlways] = useState(false);
  const [tlOld, setTlOld] = useState(false);
  const [tlError, setTlError] = useState("");
  const cloud = !!server?.cloud;

  useFocusEffect(useCallback(() => {
    if (!api) { setOnline(null); return; }
    api.printers().then(setPrinters).catch(() => setPrinters([]));
    if (server?.cloud) api.me().then(setMe).catch(() => setMe(null));
    if (server) loadSpoolmanUrl(server).then(setSpoolman);
    if (server) {
      setTlError("");
      loadTimelapseAlways(server).then(setTlAlways);
      if (api) serverTimelapseAlways(api, server).then(v => {
        setTlOld(v === "old");
        if (typeof v === "boolean") { setTlAlways(v); saveTimelapseAlways(server, v); }
      });
    }
    api.info().then(i => { setOnline(true); setServerVersion(i.version); setRoute(api.route()); })
      .catch(() => { setOnline(false); setRoute(null); });
  }, [api, server]));

  const disconnect = () => {
    const run = () => setServer(null);
    if (Platform.OS === "web") { if (globalThis.confirm?.(t("disconnectQ"))) run(); return; }
    Alert.alert(t("disconnectQ"), undefined, [
      { text: t("cancelBtn"), style: "cancel" },
      { text: t("disconnect"), style: "destructive", onPress: run },
    ]);
  };

  const logout = async () => {
    if (!api || !(await confirmAsync(t("logoutQ"), t("logout"), t("cancelBtn")))) return;
    await api.logout().catch(() => {});        // offline: the session just stays unused
    await setServer(null);
  };
  const deleteAccount = async () => {
    if (!api || !(await confirmAsync(t("deleteAccountQ"), t("deleteAccount"), t("cancelBtn")))) return;
    if (!(await confirmAsync(t("deleteAccountQ2"), t("deleteAccount"), t("cancelBtn")))) return;
    try {
      await api.deleteAccount();
      await setServer(null);
    } catch (e) {
      Alert.alert(t("deleteAccount"), (e as Error).message);
    }
  };

  const setTimelapseAlways = async (on: boolean) => {
    if (!server) return;
    tap();
    setTlAlways(on);
    setTlError("");
    let value = on;
    if (!cloud && !tlOld && api) {
      try {
        value = (await api.setTimelapseConfig(on)).always;
      } catch (e) {
        if ((e as { status?: number }).status === 404) setTlOld(true);
        else { setTlAlways(!on); setTlError((e as Error).message); return; }
      }
    }
    setTlAlways(value);
    await saveTimelapseAlways(server, value);
  };
  const timelapseSection = (
    <Section title={t("timelapseTitle")}
      footer={tlError || t(cloud ? "timelapseAlwaysSubCloud" : tlOld ? "timelapseAlwaysOld" : "timelapseAlwaysSub")}>
      <Row icon="film-outline" label={t("timelapseAlways")}
        right={<Switch value={tlAlways} onValueChange={setTimelapseAlways} trackColor={{ true: c.accent, false: c.track }}
          accessibilityLabel={t("timelapseAlways")} />} />
    </Section>
  );

  const spoolsRow = (
    <Row icon="disc-outline" label={t("spoolman")} sub={spoolman === CLOUD_SPOOLS ? t("spoolsCloudOn") : spoolman ?? t("spoolmanSub")}
      value={spoolman ? undefined : t("spoolsOptional")} onPress={() => router.push("/spoolman")} />
  );

  if (cloud && server) {
    return (
      <Screen>
        <Section title={t("account")}>
          <Row icon="cloud-outline" label={t("modeCloud")} sub={server.email}
            right={<Badge text={online === false ? t("offline") : online ? t("connected") : "…"}
              kind={online === false ? "error" : online ? "ok" : "neutral"} />} />
          {me ? <><Divider /><Row icon="layers-outline" label={t("slicesToday", { used: me.limits.slices_today,
            limit: me.limits.slices_per_day })} /></> : null}
          <Divider />
          <Row icon="swap-horizontal-outline" label={t("changeAccount")} onPress={() => router.push("/connect")} />
          <Divider />
          <Row icon="log-out-outline" label={t("logout")} onPress={logout} />
        </Section>

        <Section title={t("tabPrinters")}>
          {printers.map((p, i) => (
            <View key={p.id}>
              {i ? <Divider /> : null}
              <Row icon="print-outline" label={p.name} sub={t.table.printerTypes[p.type] ?? p.type}
                onPress={() => router.push({ pathname: "/cloud-printer/[id]", params: { id: p.id } })} />
            </View>
          ))}
          {printers.length ? <Divider /> : null}
          <Row icon="add-circle-outline" label={t("addPrinter")}
            onPress={() => router.push({ pathname: "/cloud-printer/[id]", params: { id: "new" } })} />
        </Section>

        <Section title={t("language")}>
          <View style={{ padding: 12 }}>
            <Segmented<LangPref> values={["auto", "de", "en"]} value={langPref} onChange={setLangPref}
              labels={{ auto: t("langAuto"), de: "Deutsch", en: "English" }} />
          </View>
        </Section>

        {timelapseSection}

        <Section title={t("advanced")}>
          <Row icon="git-network-outline" label={t("bridgesTitle")} sub={t("bridgesSub")}
            onPress={() => router.push("/bridges")} />
          <Divider />
          {spoolsRow}
        </Section>

        <Section title={t("about")} footer={t(WEB_APP ? "aboutTextCloudWeb" : "aboutTextCloud")}>
          <Row icon="information-circle-outline" label={t("version")} value={Constants.expoConfig?.version ?? "–"} />
          <Divider />
          <Row icon="shield-checkmark-outline" label="pocketprint3d.com/privacy" onPress={() => Linking.openURL("https://pocketprint3d.com/privacy/")} />
          <Divider />
          <Row icon="logo-github" label={t("sourceCode")} onPress={() => Linking.openURL("https://github.com/halvar20000/printshare")} />
        </Section>
        <Section>
          <Row icon="trash-outline" label={t("deleteAccount")} danger onPress={deleteAccount} />
        </Section>
        <Text style={{ color: c.sub, textAlign: "center", fontSize: 12 }}>PocketPrint3D · MIT</Text>
      </Screen>
    );
  }

  return (
    <Screen>
      <Section title={t("server")}>
        <Row icon="server-outline" label={server ? server.url.replace(/^https?:\/\//, "") : t("notConnected")}
          sub={server && serverVersion ? [`PocketPrint3D ${serverVersion}`, route ? t(route === "home" ? "routeHome" : "routeRemote") : null]
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

      {server ? timelapseSection : null}

      {server ? (
        <Section title={t("advanced")}>
          {spoolsRow}
          <Divider />
          <Row icon="library-outline" label={t("manyfoldTitle")} sub={t("manyfoldSub")}
            onPress={() => router.push("/manyfold")} />
          <Divider />
          <Row icon="eye-outline" label={t("failureTitle")} sub={t("failureSub")}
            onPress={() => router.push("/failure-detection")} />
        </Section>
      ) : null}

      <Section title={t("about")} footer={t("aboutText")}>
        <Row icon="information-circle-outline" label={t("version")} value={Constants.expoConfig?.version ?? "–"} />
        <Divider />
        <Row icon="logo-github" label={t("sourceCode")} onPress={() => Linking.openURL("https://github.com/halvar20000/printshare")} />
      </Section>
      <Text style={{ color: c.sub, textAlign: "center", fontSize: 12 }}>PocketPrint3D · MIT</Text>
    </Screen>
  );
}
