// Own OrcaSlicer presets from an Orca Cloud account (server 0.42.0, issue #7). Orca Cloud lets apps read a user's synced
// presets after a pairing (code confirmed in the Orca Cloud settings); each app needs an "app ID" (client_id) from the
// Orca Cloud team. PocketPrint3D has none yet, so the user enters one (unless the server sets it). The server keeps the
// tokens and pulls the presets now and then on the chosen schedule (server 0.45.0: every 1/6/24 h or only by hand, and
// before a print is prepared); they then show up like uploaded presets.
import * as Clipboard from "expo-clipboard";
import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Linking, Switch, Text, TextInput, View } from "react-native";

import { Banner, Button, Divider, Row, Screen, Section, confirmAsync, tap } from "@/components/ui";
import { errorText, type OrcaAccount } from "@/lib/api";
import { useApp } from "@/lib/app";
import { ago } from "@/lib/format";
import { space, useColors } from "@/lib/theme";

export default function OrcaAccountScreen() {
  const { api, t } = useApp();
  const c = useColors();
  const [st, setSt] = useState<OrcaAccount | null>(null);
  const [idInput, setIdInput] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  const load = useCallback(() => {
    api?.orcaAccount().then(s => { setSt(s); setIdInput(v => v || (s.client_id_from === "user" ? s.client_id ?? "" : "")); })
      .catch(e => setError(errorText(t, e)));
  }, [api, t]);
  useFocusEffect(load);
  // while a pairing waits for the user's OK in Orca Cloud: follow it
  const waiting = !!st?.pending && !st.pending.error;
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [waiting, load]);

  const act = async (key: string, fn: () => Promise<OrcaAccount | void>, message = "") => {
    setBusy(key); setError(""); setDone("");
    try {
      const r = await fn();
      if (r) setSt(r);
      if (message) setDone(message);
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setBusy("");
    }
  };
  const saveId = () => api && act("id", () => api.setOrcaClientId(idInput.trim() || null), t("orcaIdSaved"));
  const connect = () => api && act("connect", async () => {
    const r = await api.connectOrca();
    const url = r.pending?.verification_uri_complete ?? r.pending?.verification_uri;
    if (url) Linking.openURL(url).catch(() => {});
    return r;
  });
  const sync = () => api && act("sync", async () => {
    const r = await api.syncOrca();
    setDone(t("orcaSynced", { n: r.count }));
    return r;
  });
  const schedule = (body: { interval_h?: number; on_prepare?: boolean }) => api && act("schedule", () => api.setOrcaSchedule(body));
  const disconnect = async () => {
    if (!api || !(await confirmAsync(t("orcaDisconnectQ"), t("orcaDisconnect"), t("cancelBtn")))) return;
    const remove = await confirmAsync(t("orcaRemovePresetsQ"), t("del"), t("orcaKeepPresets"));
    act("off", () => api.disconnectOrca(remove), t("orcaDisconnected"));
  };

  if (!st) return error ? <Screen><Banner kind="error" text={error} /></Screen>
    : <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />;
  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  const p = st.pending;
  const fromServer = st.client_id_from === "server";
  return (
    <Screen>
      {error ? <Banner kind="error" text={error} /> : null}
      {done ? <Banner kind="ok" text={done} /> : null}
      {st.last_error && !error ? <Banner kind="warn" text={st.last_error} /> : null}
      <Text style={{ color: c.sub, fontSize: 15, marginBottom: 16, marginHorizontal: 4 }}>{t("orcaAccountIntro")}</Text>

      <Section title={t("orcaIdTitle")} footer={fromServer ? t("orcaIdServer") : t("orcaIdHint")}>
        {fromServer ? <Row icon="key-outline" label={t("orcaIdTitle")} value={st.client_id ?? ""} /> : (
          <>
            <TextInput value={idInput} onChangeText={v => { setIdInput(v); setDone(""); }} placeholder="oc_app_…"
              placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} accessibilityLabel={t("orcaIdTitle")}
              style={input} />
            <Divider />
            <View style={{ padding: space }}>
              <Button kind="secondary" title={t("save")} icon="checkmark" onPress={() => { tap(); saveId(); }}
                loading={busy === "id"} disabled={idInput.trim() === (st.client_id ?? "")} />
            </View>
          </>
        )}
      </Section>

      {p ? (
        <Section title={t("orcaPairTitle")} footer={p.error ? undefined : t("orcaPairHint")}>
          {p.error ? <View style={{ padding: space }}>
            <Text style={{ color: c.danger, fontSize: 15 }}>
              {p.error === "denied" ? t("orcaPairDenied") : p.error === "expired" ? t("orcaPairExpired") : p.error}</Text>
          </View> : (
            <View style={{ padding: space, alignItems: "center" }}>
              <Text selectable style={{ color: c.text, fontSize: 34, fontWeight: "800", letterSpacing: 3 }}>{p.user_code}</Text>
              <View style={{ flexDirection: "row", alignItems: "center", marginTop: 8 }}>
                <ActivityIndicator color={c.accent} />
                <Text style={{ color: c.sub, marginLeft: 8 }}>{t("orcaPairWaiting")}</Text>
              </View>
              <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
                <Button kind="secondary" title={t("orcaCopyCode")} icon="copy-outline"
                  onPress={() => { tap(); Clipboard.setStringAsync(p.user_code); }} />
                {p.verification_uri ? <Button kind="secondary" title={t("orcaOpen")} icon="open-outline"
                  onPress={() => Linking.openURL(p.verification_uri_complete ?? p.verification_uri!)} /> : null}
              </View>
            </View>
          )}
        </Section>
      ) : null}

      {st.connected ? (
        <Section title={t("orcaAccountTitle")}>
          <Row icon="checkmark-circle-outline" label={t("orcaConnected")}
            sub={st.last_sync ? t("orcaLastSync", { when: ago(t, st.last_sync), n: st.count }) : undefined} />
          {st.skipped.length ? <>
            <Divider />
            <Row icon="alert-circle-outline" label={t("orcaSkipped", { n: st.skipped.length })}
              sub={st.skipped.slice(0, 4).map(s => s.name).join(", ")} />
          </> : null}
          <Divider />
          <Row icon="sync-outline" label={t("orcaSyncNow")} onPress={busy ? undefined : sync}
            right={busy === "sync" ? <ActivityIndicator /> : undefined} />
          <Divider />
          <Row icon="log-out-outline" label={t("orcaDisconnect")} danger onPress={disconnect} />
        </Section>
      ) : null}
      {st.connected && st.interval_h !== undefined ? (      // older servers have no schedule
        <Section title={t("orcaScheduleTitle")} footer={t("orcaOnPrepareHint")}>
          {(st.intervals ?? [0, 1, 6, 24]).map((h, i) => (
            <View key={h}>
              {i ? <Divider /> : null}
              <Row icon="time-outline" label={t(`orcaEvery${h}` as "orcaEvery6")}
                onPress={busy || h === st.interval_h ? undefined : () => { tap(); schedule({ interval_h: h }); }}
                right={h === st.interval_h ? <Text style={{ color: c.accent, fontSize: 17 }}>✓</Text> : undefined} />
            </View>
          ))}
          <Divider />
          <Row icon="construct-outline" label={t("orcaOnPrepare")}
            right={<Switch value={!!st.on_prepare} disabled={!!busy} trackColor={{ true: c.accent, false: c.track }}
              onValueChange={v => { tap(); schedule({ on_prepare: v }); }} />} />
        </Section>
      ) : null}
      {st.connected ? null : (
        <Button title={t(p ? "orcaConnectAgain" : "orcaConnect")} icon="link-outline" onPress={() => { tap(); connect(); }}
          loading={busy === "connect"} disabled={!st.client_id} />
      )}
    </Screen>
  );
}
