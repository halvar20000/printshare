// Cloud: bridges at home (docs/BRIDGE.md) - "print from anywhere". A bridge is the user's own PocketPrint3D server
// (Unraid, Home Assistant, Docker) with "Connect to PocketPrint3D Cloud" on; it shows a code that is entered here.
// Its printers then appear in the account by themselves; more can be added through the bridge.
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Text, TextInput, View } from "react-native";

import { Badge, Banner, Button, Card, Divider, Row, Screen, Section, confirmAsync } from "@/components/ui";
import { errorText, type Bridge } from "@/lib/api";
import { useApp } from "@/lib/app";
import { ago } from "@/lib/format";
import { space, useColors } from "@/lib/theme";

/** "k7q4m2zx" / "K7Q4 M2ZX" → "K7Q4-M2ZX" while typing (no 0/O, 1/I in codes) */
const formatCode = (v: string) => {
  const raw = v.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
  return raw.length > 4 ? `${raw.slice(0, 4)}-${raw.slice(4)}` : raw;
};

export default function Bridges() {
  const { api, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const [bridges, setBridges] = useState<Bridge[] | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [paired, setPaired] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!api) return;
    api.bridges().then(setBridges).catch(e => { setError(errorText(t, e)); setBridges([]); });
  }, [api, t]);
  useFocusEffect(load);

  const pair = async () => {
    if (!api) return;
    setBusy(true);
    setError("");
    try {
      const b = await api.pairBridge(code);
      setPaired(b.name);
      setCode("");
      // the bridge picks up its token within a few seconds and connects
      setTimeout(load, 4000);
      load();
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (b: Bridge) => {
    if (!api || !(await confirmAsync(t("bridgeRemoveQ", { name: b.name }), t("del"), t("cancelBtn")))) return;
    try {
      await api.deleteBridge(b.id);
      load();
    } catch (e) {
      setError(errorText(t, e));
    }
  };

  const input = { color: c.text, fontSize: 22, letterSpacing: 3, paddingHorizontal: space, paddingVertical: 14,
                  fontWeight: "600" as const, textAlign: "center" as const };
  return (
    <Screen>
      <Text style={{ color: c.sub, fontSize: 15, lineHeight: 21, marginBottom: 16 }}>{t("bridgeIntro")}</Text>
      {error ? <Banner kind="error" text={error} /> : null}
      {paired ? <Banner kind="ok" text={t("bridgePaired", { name: paired })} /> : null}

      <Section title={t("bridgeConnect")} footer={t("bridgeCodeHint")}>
        <TextInput value={code} onChangeText={v => { setCode(formatCode(v)); setError(""); }} placeholder="K7Q4-M2ZX"
          placeholderTextColor={c.sub} autoCapitalize="characters" autoCorrect={false} maxLength={9}
          accessibilityLabel={t("bridgeCode")} style={input} onSubmitEditing={pair} />
        <View style={{ padding: space, paddingTop: 0 }}>
          <Button title={t("bridgeConnectBtn")} icon="link" onPress={pair} loading={busy}
            disabled={code.replace("-", "").length !== 8} />
        </View>
      </Section>

      {bridges === null ? <ActivityIndicator color={c.accent} style={{ marginTop: 20 }} /> : null}
      {(bridges ?? []).map(b => (
        <Card key={b.id} style={{ marginBottom: 16 }}>
          <Row icon="git-network-outline" label={b.name}
            sub={[b.version ? `PocketPrint3D ${b.version}` : null,
                  !b.online && b.last_seen ? t("bridgeLastSeen", { v: ago(t, b.last_seen) }) : null].filter(Boolean).join(" · ")}
            right={<Badge text={b.online ? t("connected") : t("offline")} kind={b.online ? "ok" : "error"} />} />
          {b.printers.map(p => (
            <View key={p.id}>
              <Divider />
              <Row icon="print-outline" label={p.name} sub={p.type ? t.table.printerTypes[p.type] ?? p.type : undefined} />
            </View>
          ))}
          <Divider />
          <Row icon="add-circle-outline" label={t("bridgeAddPrinter")}
            sub={b.online ? undefined : t("bridgeNeedsOnline")}
            onPress={b.online ? () => router.push({ pathname: "/cloud-printer/[id]", params: { id: "new", bridge: b.id } }) : undefined} />
          <Divider />
          <Row icon="trash-outline" label={t("bridgeRemove")} danger onPress={() => remove(b)} />
        </Card>
      ))}
    </Screen>
  );
}
