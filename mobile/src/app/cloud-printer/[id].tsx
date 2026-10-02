// Cloud: a printer of the account - name, type, OrcaSlicer model - and how the app reaches it on the home Wi-Fi
// (address, PrusaLink password, API key: stored only on this phone, docs/CLOUD.md). id "new" adds a printer.
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Switch, Text, TextInput, View } from "react-native";

import { Banner, Button, Divider, PickerSheet, Row, Screen, Section, confirmAsync } from "@/components/ui";
import { errorText, type Printer } from "@/lib/api";
import { useApp } from "@/lib/app";
import { lanPrinter } from "@/lib/lan";
import { loadAccess, saveAccess } from "@/lib/printerAccess";
import { space, useColors } from "@/lib/theme";

type Kind = "elegoo_sdcp" | "moonraker" | "prusalink" | "octoprint";
const KINDS: Kind[] = ["elegoo_sdcp", "moonraker", "prusalink", "octoprint"];
const needsModel = (k: Kind) => k === "prusalink" || k === "octoprint";

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
  const [machine, setMachine] = useState<string | null>(null);
  const [address, setAddress] = useState("");
  const [password, setPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState<{ name: string; vendor: string }[] | null>(null);
  const [sheet, setSheet] = useState<"type" | "model" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (!api || !server || isNew) return;
    let alive = true;
    Promise.all([api.printers(), loadAccess(server)]).then(([ps, access]) => {
      if (!alive) return;
      const p = ps.find(x => x.id === id);
      if (p) {
        setName(p.name);
        setType((KINDS as string[]).includes(p.type) ? p.type as Kind : "elegoo_sdcp");
        setCosmos(!!p.cosmos);
        setMachine(p.machine);
      }
      const a = access[id];
      setAddress(a?.address ?? "");
      setPassword(a?.password ?? "");
      setApiKey(a?.apiKey ?? "");
      setLoaded(true);
    }).catch(e => { if (alive) { setError((e as Error).message); setLoaded(true); } });
    return () => { alive = false; };
  }, [api, server, id, isNew]);

  // printer models for Prusa / OctoPrint (and optionally Klipper), loaded when the choice is opened
  useEffect(() => {
    if (!api || sheet !== "model" || models) return;
    api.machines().then(setModels).catch(e => setError((e as Error).message));
  }, [api, sheet, models]);
  const modelChoices = useMemo(() => (models ?? []).map(m => ({ value: m.name, label: m.name, group: m.vendor })), [models]);

  const access = { address, password: type === "prusalink" ? password : undefined,
                   apiKey: type === "prusalink" || type === "octoprint" || type === "moonraker" ? apiKey : undefined };

  const testConnection = async () => {
    setTesting(true);
    setTest(null);
    try {
      const lan = lanPrinter(type, access);
      try {
        const st = await lan.status();
        setTest({ ok: true, text: t("lanReachable", { state: t.table.printerKinds[st.kind] ?? st.state ?? "",
          temp: st.nozzle != null ? `${Math.round(st.nozzle)} °C` : "–" }) });
      } finally {
        lan.close();
      }
    } catch (e) {
      setTest({ ok: false, text: errorText(t, e) });
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    if (!api || !server) return;
    setBusy(true);
    setError("");
    try {
      const body = { name: name.trim() || autoName, type, cosmos: type === "moonraker" ? cosmos : false,
                     ...(machine && (needsModel(type) || type === "moonraker") ? { machine } : {}) };
      const p: Printer = isNew ? await api.addPrinter(body) : await api.updatePrinter(id, body);
      await saveAccess(server, p.id, access);
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
      await saveAccess(server, id, null);
      router.back();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  const typeLabel = (k: Kind) => t.table.printerTypes[k];
  const missingModel = needsModel(type) && !machine;
  // a name is optional: without one the printer is called after its model or type
  const autoName = (machine && (needsModel(type) || type === "moonraker") ? machine.replace(/\s+[\d.]+\s*nozzle$/i, "") : "")
    || (type === "moonraker" && cosmos ? "Centauri Carbon" : typeLabel(type));
  const missingCreds = (type === "prusalink" && !password && !apiKey) || (type === "octoprint" && !apiKey);
  if (!loaded) return <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />;
  return (
    <Screen footer={<Button title={t("save")} icon="checkmark" onPress={save} loading={busy}
      disabled={missingModel} />}>
      <Stack.Screen options={{ title: isNew ? t("addPrinter") : name || t("printer") }} />
      {error ? <Banner kind="error" text={error} /> : null}

      <Section title={t("printerType")} footer={t.table.printerTypeHints[type]}>
        <Row icon="print-outline" label={typeLabel(type)} value={t("change")} onPress={() => setSheet("type")} />
        {type === "moonraker" ? (
          <>
            <Divider />
            <Row label={t("cosmos")} right={<Switch value={cosmos} onValueChange={setCosmos} />} />
          </>
        ) : null}
        {needsModel(type) || (type === "moonraker" && !cosmos) ? (
          <>
            <Divider />
            <Row icon="cube-outline" label={t("printerModel")} value={machine ?? t("chooseModel")}
              sub={missingModel ? t("modelNeeded") : undefined} onPress={() => setSheet("model")} />
          </>
        ) : null}
      </Section>

      <Section title={t("lanAddress")} footer={t("lanAddressHint")}>
        <TextInput value={address} onChangeText={v => { setAddress(v); setTest(null); }}
          placeholder={type === "octoprint" ? "octopi.local" : "192.168.1.50"}
          placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} keyboardType="url"
          accessibilityLabel={t("lanAddress")} style={input} />
        {type === "prusalink" ? (
          <>
            <Divider />
            <TextInput value={password} onChangeText={v => { setPassword(v); setTest(null); }} placeholder={t("prusaPassword")}
              placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} secureTextEntry
              accessibilityLabel={t("prusaPassword")} style={input} />
          </>
        ) : null}
        {type !== "elegoo_sdcp" ? (
          <>
            <Divider />
            <TextInput value={apiKey} onChangeText={v => { setApiKey(v); setTest(null); }}
              placeholder={type === "octoprint" ? t("octoApiKey") : t("apiKeyOptional")}
              placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} secureTextEntry
              accessibilityLabel={type === "octoprint" ? t("octoApiKey") : t("apiKeyOptional")} style={input} />
          </>
        ) : null}
        <Divider />
        <View style={{ padding: space }}>
          <Button kind="secondary" title={t("testConnection")} icon="wifi-outline" onPress={testConnection}
            loading={testing} disabled={!address.trim() || missingCreds} />
          {test ? <Text style={{ color: test.ok ? c.ok : c.danger, marginTop: 10, fontSize: 14 }}>{test.text}</Text> : null}
        </View>
      </Section>
      {type === "prusalink" ? <Text style={{ color: c.sub, fontSize: 13, marginTop: -12, marginBottom: 20, marginHorizontal: 16 }}>
        {t("prusaHint")}</Text> : null}
      {type === "octoprint" ? <Text style={{ color: c.sub, fontSize: 13, marginTop: -12, marginBottom: 20, marginHorizontal: 16 }}>
        {t("octoHint")}</Text> : null}

      <Section title={t("printerNameAuto")} footer={name.trim() ? undefined : t("printerNameAutoHint", { name: autoName })}>
        <TextInput value={name} onChangeText={setName} placeholder={autoName} placeholderTextColor={c.sub}
          accessibilityLabel={t("printerName")} style={input} maxLength={60} />
      </Section>

      {!isNew ? (
        <Section>
          <Row icon="document-text-outline" label={t("printerProfile")}
            onPress={() => router.push({ pathname: "/printer/[id]", params: { id } })} />
          <Divider />
          <Row icon="trash-outline" label={t("deletePrinter")} danger onPress={remove} />
        </Section>
      ) : null}

      <PickerSheet visible={sheet === "type"} title={t("printerType")} value={type} searchLabel={t("search")} closeLabel="OK"
        choices={KINDS.map(k => ({ value: k, label: typeLabel(k) }))}
        onPick={v => { setType(v as Kind); setTest(null); }} onClose={() => setSheet(null)} />
      <PickerSheet visible={sheet === "model"} title={t("printerModel")} value={machine} searchLabel={t("search")} closeLabel="OK"
        choices={modelChoices} onPick={setMachine} onClose={() => setSheet(null)} />
      {sheet === "model" && !models ? <ActivityIndicator color={c.accent} /> : null}
    </Screen>
  );
}
