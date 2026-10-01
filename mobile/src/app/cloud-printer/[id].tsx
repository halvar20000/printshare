// Cloud: a printer of the account - name, type, COSMOS - and its address on the home Wi-Fi (stored only on this
// phone; the app talks to the printer itself, docs/CLOUD.md). id "new" adds a printer.
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Switch, Text, TextInput, View } from "react-native";

import { Banner, Button, Divider, Row, Screen, Section, Segmented, confirmAsync } from "@/components/ui";
import type { Printer } from "@/lib/api";
import { useApp } from "@/lib/app";
import { lanPrinter } from "@/lib/lan";
import { loadAddresses, saveAddress } from "@/lib/printerAccess";
import { space, useColors } from "@/lib/theme";

type Kind = "elegoo_sdcp" | "moonraker";

export default function CloudPrinter() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const isNew = id === "new";
  const { api, server, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const [loaded, setLoaded] = useState(isNew);
  const [name, setName] = useState("");
  const [type, setType] = useState<Kind>("elegoo_sdcp");
  const [cosmos, setCosmos] = useState(false);
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (!api || !server || isNew) return;
    let alive = true;
    Promise.all([api.printers(), loadAddresses(server)]).then(([ps, addrs]) => {
      if (!alive) return;
      const p = ps.find(x => x.id === id);
      if (p) {
        setName(p.name);
        setType(p.type === "moonraker" ? "moonraker" : "elegoo_sdcp");
        setCosmos(!!p.cosmos);
      }
      setAddress(addrs[id] ?? "");
      setLoaded(true);
    }).catch(e => { if (alive) { setError((e as Error).message); setLoaded(true); } });
    return () => { alive = false; };
  }, [api, server, id, isNew]);

  const testConnection = async () => {
    setTesting(true);
    setTest(null);
    const lan = lanPrinter(type, address);
    try {
      const st = await lan.status();
      setTest({ ok: true, text: t("lanReachable", { state: t.table.printerKinds[st.kind] ?? st.state ?? "",
        temp: st.nozzle != null ? `${Math.round(st.nozzle)} °C` : "–" }) });
    } catch (e) {
      setTest({ ok: false, text: `${t("lanUnreachable")} (${(e as Error).message})` });
    } finally {
      lan.close();
      setTesting(false);
    }
  };

  const save = async () => {
    if (!api || !server) return;
    setBusy(true);
    setError("");
    try {
      const body = { name: name.trim(), type, cosmos: type === "moonraker" ? cosmos : false };
      const p: Printer = isNew ? await api.addPrinter(body) : await api.updatePrinter(id, body);
      await saveAddress(server, p.id, address);
      router.back();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!api || !server || !(await confirmAsync(t("deletePrinterQ", { name }), t("del"), t("cancelBtn")))) return;
    try {
      await api.deletePrinter(id);
      await saveAddress(server, id, null);
      router.back();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  if (!loaded) return <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />;
  return (
    <Screen footer={<Button title={t("save")} icon="checkmark" onPress={save} loading={busy} disabled={!name.trim()} />}>
      <Stack.Screen options={{ title: isNew ? t("addPrinter") : name || t("printer") }} />
      {error ? <Banner kind="error" text={error} /> : null}

      <Section title={t("printerName")}>
        <TextInput value={name} onChangeText={setName} placeholder="Centauri Carbon" placeholderTextColor={c.sub}
          accessibilityLabel={t("printerName")} style={input} maxLength={60} />
      </Section>

      <Section title={t("printerType")} footer={type === "moonraker" ? t("cosmosHint") : undefined}>
        <View style={{ padding: 12 }}>
          <Segmented<Kind> values={["elegoo_sdcp", "moonraker"]} value={type} onChange={v => { setType(v); setTest(null); }}
            labels={{ elegoo_sdcp: t("typeCentauri"), moonraker: t("typeKlipper") }} />
        </View>
        {type === "moonraker" ? (
          <>
            <Divider />
            <Row label={t("cosmos")} right={<Switch value={cosmos} onValueChange={setCosmos} />} />
          </>
        ) : null}
      </Section>

      <Section title={t("lanAddress")} footer={t("lanAddressHint")}>
        <TextInput value={address} onChangeText={v => { setAddress(v); setTest(null); }} placeholder="192.168.1.50"
          placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} keyboardType="url"
          accessibilityLabel={t("lanAddress")} style={input} />
        <Divider />
        <View style={{ padding: space }}>
          <Button kind="secondary" title={t("testConnection")} icon="wifi-outline" onPress={testConnection}
            loading={testing} disabled={!address.trim()} />
          {test ? <Text style={{ color: test.ok ? c.ok : c.danger, marginTop: 10, fontSize: 14 }}>{test.text}</Text> : null}
        </View>
      </Section>

      {!isNew ? (
        <Section>
          <Row icon="document-text-outline" label={t("printerProfile")}
            onPress={() => router.push({ pathname: "/printer/[id]", params: { id } })} />
          <Divider />
          <Row icon="trash-outline" label={t("deletePrinter")} danger onPress={remove} />
        </Section>
      ) : null}
    </Screen>
  );
}
