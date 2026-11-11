// Bridge mode of this own server (docs/BRIDGE.md, server 0.25.0): reached from anywhere through PocketPrint3D Cloud.
// Was on the classic web page alone until 0.53.0. The code is entered in the app with a cloud account.
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Switch, Text, View } from "react-native";

import { Banner, Divider, Row, Screen, Section, confirmAsync, tap } from "@/components/ui";
import type { ServerBridge } from "@/lib/api";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

export default function ServerBridgeScreen() {
  const { api, t } = useApp();
  const c = useColors();
  const [st, setSt] = useState<ServerBridge | null>(null);
  const [error, setError] = useState("");

  // refreshed every 3 s while the screen is open: the code changes, the connection comes up after pairing
  useFocusEffect(useCallback(() => {
    if (!api) return;
    let alive = true;
    const load = () => api.serverBridge().then(s => { if (alive) { setSt(s); setError(""); } })
      .catch(e => { if (alive) setError((e as Error).message); });
    load();
    const timer = setInterval(load, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, [api]));

  const toggle = async (on: boolean) => {
    if (!api) return;
    tap();
    try { setSt(await api.setServerBridge(on)); } catch (e) { setError((e as Error).message); }
  };
  const reset = async () => {
    if (!api || !(await confirmAsync(t("serverBridgeResetQ", { account: st?.account ?? "" }), t("serverBridgeReset"),
      t("cancelBtn")))) return;
    try { setSt(await api.resetServerBridge()); } catch (e) { setError((e as Error).message); }
  };

  if (!st && !error) return <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />;
  const state = !st || !st.enabled ? t("serverBridgeOff")
    : st.state === "pairing" ? null
    : st.state === "connected" ? t("serverBridgeConnected", { account: st.account ?? "" })
    : st.state === "error" || st.error ? t("serverBridgeError", { error: st.error ?? "" })
    : t("serverBridgeConnecting", { cloud: (st.cloud ?? "").replace(/^https?:\/\//, "") });
  return (
    <Screen>
      {error ? <Banner kind="error" text={error} /> : null}
      <Section title={t("serverBridgeTitle")} footer={t("serverBridgeHint")}>
        <Row icon="git-network-outline" label={t("serverBridgeOn")}
          right={<Switch value={!!st?.enabled} onValueChange={toggle} trackColor={{ true: c.accent, false: c.track }}
            accessibilityLabel={t("serverBridgeOn")} />} />
        {state ? <><Divider />
          <Text style={{ color: st?.state === "error" ? c.danger : c.sub, fontSize: 15, padding: space }}>{state}</Text></> : null}
      </Section>
      {st?.enabled && st.state === "pairing" && st.code ? (
        <Section>
          <View style={{ padding: space, alignItems: "center", gap: 10 }}>
            <Text selectable style={{ color: c.text, fontSize: 34, fontWeight: "700", letterSpacing: 4,
              fontVariant: ["tabular-nums"] }}>{st.code}</Text>
            <Text style={{ color: c.sub, fontSize: 14, textAlign: "center" }}>
              {t("serverBridgePairing", { min: Math.max(1, Math.ceil((st.code_expires_in ?? 0) / 60)) })}
            </Text>
          </View>
        </Section>
      ) : null}
      {st?.enabled && st.paired ? (
        <Section>
          <Row icon="swap-horizontal-outline" label={t("serverBridgeReset")} onPress={reset} />
        </Section>
      ) : null}
    </Screen>
  );
}
