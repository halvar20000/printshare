// Smart plug for one printer through Home Assistant (issue #9, server 0.12.0; "switch on when needed" 0.46.0).
// Own servers only. Was on the classic web page alone until 0.53.0. The token is write-only: empty = keep the stored one.
import { Stack, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Switch, TextInput, View } from "react-native";

import { Banner, Button, Divider, PickerSheet, Row, Screen, Section, confirmAsync, tap } from "@/components/ui";
import type { PowerConfig, PowerSettings } from "@/lib/api";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

export default function PowerSettingsScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const [name, setName] = useState("");
  const [cfg, setCfg] = useState<PowerConfig | null>(null);
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [entity, setEntity] = useState("");
  const [autoOn, setAutoOn] = useState(false);
  const [entities, setEntities] = useState<{ entity: string; name: string; state: string | null }[]>([]);
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState<"" | "load" | "test" | "save">("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  useEffect(() => {
    if (!api) return;
    api.printers().then(ps => setName(ps.find(p => p.id === id)?.name ?? id)).catch(() => {});
    api.powerConfig(id).then(r => {
      setCfg(r); setUrl(r.url ?? ""); setEntity(r.entity ?? ""); setAutoOn(!!r.auto_on);
    }).catch(e => setError((e as Error).message));
  }, [api, id]);

  const body = (): PowerSettings => ({ url: url.trim(), entity: entity.trim(), auto_on: autoOn,
    ...(token.trim() ? { token: token.trim() } : {}) });
  const run = async (kind: "load" | "test" | "save", fn: () => Promise<void>) => {
    tap(); setBusy(kind); setError(""); setDone("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  };
  const load = () => run("load", async () => {
    const list = await api!.powerEntities(id, body());
    setEntities(list);
    setDone(t("plugLoaded", { n: list.length }));
    if (list.length) setPicking(true);
  });
  const test = () => run("test", async () => {
    const r = await api!.testPower(id, body());
    if (r.ok) setDone(t("plugOk", { name: r.name || entity, state: t.table.powerStates[r.state ?? ""] ?? r.state ?? "" }));
    else setError(r.error ?? "");
  });
  const save = () => run("save", async () => {
    const r = await api!.setPowerConfig(id, body());
    setCfg(r); setToken(""); setDone(t("plugSaved"));
  });
  const remove = async () => {
    if (!api || !(await confirmAsync(t("plugRemoveQ", { printer: name }), t("del"), t("cancelBtn")))) return;
    try {
      const r = await api.deletePowerConfig(id);
      setCfg(r); setEntity(""); setUrl(r.url ?? ""); setAutoOn(false); setDone("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!cfg && !error) return <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />;
  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  const supervisor = !!cfg?.addon && !url.trim();
  const current = entities.find(e => e.entity === entity);
  return (
    <Screen footer={<Button title={t("save")} icon="checkmark" onPress={save} loading={busy === "save"}
      disabled={!entity.trim() || (!supervisor && !url.trim())} />}>
      <Stack.Screen options={{ title: name ? `${t("plugTitle")} · ${name}` : t("plugTitle") }} />
      {error ? <Banner kind="error" text={error} /> : null}
      {done ? <Banner kind="ok" text={done} /> : null}
      {cfg?.addon ? <Banner kind="info" text={t("plugAddon")} /> : null}

      <Section title={t("plugTitle")} footer={t("plugHint")}>
        <TextInput value={url} onChangeText={setUrl} placeholder={cfg?.addon ? `${t("plugUrl")} (Add-on)` : "http://homeassistant.local:8123"}
          placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} keyboardType="url"
          accessibilityLabel={t("plugUrl")} style={input} />
        <Divider />
        <TextInput value={token} onChangeText={setToken} secureTextEntry autoCapitalize="none" autoCorrect={false}
          placeholder={cfg?.token_set ? t("plugTokenKept") : t("plugToken")} placeholderTextColor={c.sub}
          accessibilityLabel={t("plugToken")} style={input} />
        <Divider />
        <TextInput value={entity} onChangeText={setEntity} placeholder={`${t("plugEntity")}: switch.drucker`}
          placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false}
          accessibilityLabel={t("plugEntity")} style={input} />
        {current ? <Row icon="flash-outline" label={current.name} sub={current.entity} chevron={false} /> : null}
        <Divider />
        <Row icon="list-outline" label={entities.length ? t("plugChoose") : t("plugLoad")}
          right={busy === "load" ? <ActivityIndicator color={c.accent} /> : undefined}
          onPress={() => (entities.length ? setPicking(true) : load())} />
      </Section>

      <Section footer={t("plugAutoOnHint")}>
        <Row icon="power-outline" label={t("plugAutoOn")}
          right={<Switch value={autoOn} onValueChange={v => { tap(); setAutoOn(v); }}
            trackColor={{ true: c.accent, false: c.track }} accessibilityLabel={t("plugAutoOn")} />} />
      </Section>

      <View style={{ marginBottom: 22 }}>
        <Button kind="secondary" title={t("plugTest")} icon="pulse-outline" onPress={test} loading={busy === "test"}
          disabled={!entity.trim() || (!supervisor && !url.trim() && !cfg?.token_set)} />
      </View>

      {cfg?.configured ? (
        <Section>
          <Row icon="trash-outline" label={t("plugRemove")} danger onPress={remove} />
        </Section>
      ) : null}

      <PickerSheet visible={picking} title={t("plugChoose")} value={entity || null}
        choices={entities.map(e => ({ value: e.entity, label: e.name,
          sub: [e.entity, e.state ? t.table.powerStates[e.state] ?? e.state : null].filter(Boolean).join(" · "),
          group: e.entity.split(".")[0] }))}
        onPick={v => { setEntity(v); setPicking(false); }} onClose={() => setPicking(false)}
        searchLabel={t("search")} closeLabel="OK" />
    </Screen>
  );
}
