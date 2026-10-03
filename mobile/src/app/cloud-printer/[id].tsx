// Cloud: a printer of the account - name, type, OrcaSlicer model - and how the app reaches it on the home Wi-Fi
// (address, PrusaLink password, API key: stored only on this phone, docs/CLOUD.md). id "new" adds a printer.
// With a bridge (docs/BRIDGE.md, ?bridge=<id> or a printer that has one): the bridge searches its home network, and
// address/password/key are sealed for the bridge - the cloud passes them on without being able to read them.
import Ionicons from "@expo/vector-icons/Ionicons";
import * as Crypto from "expo-crypto";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Switch, Text, TextInput, View } from "react-native";

import { Banner, Button, Divider, PickerSheet, Row, Screen, Section, confirmAsync } from "@/components/ui";
import { errorText, WEB_APP, type Printer } from "@/lib/api";
import { useApp } from "@/lib/app";
import { lanPrinter } from "@/lib/lan";
import { discoverPrinters, NoWifiError, type Found } from "@/lib/lan/discover";
import LanDiscovery from "../../../modules/lan-discovery/src/LanDiscoveryModule";
import { loadAccess, saveAccess } from "@/lib/printerAccess";
import { seal } from "@/lib/seal";
import { space, useColors } from "@/lib/theme";

type Kind = "elegoo_sdcp" | "moonraker" | "prusalink" | "octoprint";
const KINDS: Kind[] = ["elegoo_sdcp", "moonraker", "prusalink", "octoprint"];
const needsModel = (k: Kind) => k === "prusalink" || k === "octoprint";

export default function CloudPrinter() {
  const { id, bridge: bridgeParam } = useLocalSearchParams<{ id: string; bridge?: string }>();
  const isNew = id === "new";
  // web app without a bridge: no Wi-Fi search and no address - the browser can't reach the printer anyway
  const webOnly = WEB_APP && !bridgeParam;
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
  // finding printers on the Wi-Fi (new printers only): the form opens when one is picked or "enter yourself" is tapped
  const [found, setFound] = useState<Found[]>([]);
  const [scan, setScan] = useState<{ pct: number } | "done" | "nowifi" | null>(isNew && !webOnly ? { pct: 0 } : null);
  const [picked, setPicked] = useState<string | null>(null);
  const [manual, setManual] = useState(!isNew || webOnly);
  const [known, setKnown] = useState<string[]>([]);
  const scanRun = useRef(0);
  // the bridge this printer sits behind (new: from the route; existing: from the printer)
  const [viaBridge, setViaBridge] = useState<string | null>(bridgeParam ?? null);
  const [bridgeInfo, setBridgeInfo] = useState<{ name: string; key: string | null } | null>(null);
  useEffect(() => {
    if (!api || !viaBridge) return;
    api.bridges().then(bs => {
      const b = bs.find(x => x.id === viaBridge);
      setBridgeInfo(b ? { name: b.name, key: b.public_key } : null);
    }).catch(() => {});
  }, [api, viaBridge]);

  const runScan = () => {
    const run = ++scanRun.current;
    const live = () => scanRun.current === run;
    if (bridgeParam && api) {
      // the bridge searches its own network (no progress steps: one request)
      api.bridgeDiscover(bridgeParam)
        .then(list => {
          if (!live()) return;
          setFound(list.map(f => ({ type: f.type as Found["type"], address: f.address, name: f.name, cosmos: f.cosmos, detail: f.detail })));
          setKnown(list.filter(f => f.added).map(f => f.address));
          setScan("done");
        })
        .catch(e => { if (live()) { setScan("done"); setError(errorText(t, e)); } });
      return;
    }
    discoverPrinters({ wifi: () => LanDiscovery.wifiAddressAsync(), udp: (m, p, ts, ms) => LanDiscovery.udpProbeAsync(m, p, ts, ms) },
      f => { if (live()) setFound(l => [...l, f]); }, () => !live(),
      (done, total) => { if (live() && (done % 8 === 0 || done === total)) setScan({ pct: Math.round(done * 100 / total) }); })
      .then(() => { if (live()) setScan("done"); })
      .catch(e => { if (live()) setScan(e instanceof NoWifiError ? "nowifi" : "done"); });
  };
  useEffect(() => {
    if (!isNew || !server || webOnly) return;
    if (!bridgeParam) {
      loadAccess(server).then(a => setKnown(Object.values(a).map(x => x.address.replace(/^https?:\/\//, "")))).catch(() => {});
    }
    runScan();
    const runs = scanRun;
    return () => { runs.current++; };                        // stop when the screen closes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isNew, server]);
  const startScan = () => {
    setFound([]);
    setScan({ pct: 0 });
    runScan();
  };
  const pick = (f: Found) => {
    setPicked(f.address);
    setType(f.type);
    setAddress(f.address);
    setCosmos(!!f.cosmos);
    // Centauri / Klipper report a real name; for Prusa and OctoPrint the model (chosen below) names the printer
    setName(f.type === "elegoo_sdcp" || f.type === "moonraker" ? f.name : "");
    setTest(null);
    setError("");
  };

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
        if (p.bridge) setViaBridge(p.bridge);
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
      if (viaBridge) {
        // address and secrets go sealed to the bridge; the cloud and this phone don't keep them
        const secrets = { ...(address.trim() ? { address: address.trim() } : {}),
                          ...(access.password ? { password: access.password } : {}),
                          ...(access.apiKey?.trim() ? { api_key: access.apiKey.trim() } : {}) };
        const sealed = () => {
          if (!bridgeInfo?.key) throw new Error(t("errBridgeKey"));
          return seal(bridgeInfo.key, secrets, n => Crypto.getRandomBytes(n));
        };
        if (isNew) await api.bridgeAddPrinter(viaBridge, body, sealed());
        else {
          await api.updatePrinter(id, body);
          if (Object.keys(secrets).length) await api.bridgePrinterAccess(id, sealed());
        }
        router.back();
        return;
      }
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
      setError(errorText(t, e));
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
      disabled={missingModel || (isNew && !webOnly && !address.trim()) || (isNew && !!viaBridge && missingCreds)} />}>
      <Stack.Screen options={{ title: isNew ? t("addPrinter") : name || t("printer") }} />
      {error ? <Banner kind="error" text={error} /> : null}
      {viaBridge ? <Banner kind="info" icon="git-network-outline"
        text={t(isNew ? "bridgeAddHint" : "bridgePrinterHint", { bridge: bridgeInfo?.name ?? "…" })} /> : null}

      {webOnly && !viaBridge ? <Banner kind="info" icon="phone-portrait-outline" text={t("webAddPrinterHint")} /> : null}
      {isNew && !webOnly ? (
        <Section title={t(bridgeParam ? "bridgeFindTitle" : "lanFindTitle")} footer={found.length ? t("discoverHint") : undefined}>
          {found.map((f, i) => {
            const added = known.includes(f.address);
            return (
              <View key={f.address}>
                {i ? <Divider /> : null}
                <Row icon="print-outline" label={f.name}
                  sub={[t.table.printerTypes[f.type], f.address, added ? t("discoverAdded") : null].filter(Boolean).join(" · ")}
                  right={picked === f.address ? <Ionicons name="checkmark-circle" size={22} color={c.accent} /> : undefined}
                  onPress={() => pick(f)} />
              </View>
            );
          })}
          {found.length ? <Divider /> : null}
          {scan && typeof scan === "object" ? (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10, padding: space }}>
              <ActivityIndicator color={c.accent} />
              <Text style={{ color: c.sub, fontSize: 15 }}>
                {bridgeParam ? t("bridgeSearching") : t("discoverRunning", { pct: scan.pct })}</Text>
            </View>
          ) : (
            <>
              {scan === "nowifi" || (scan === "done" && !found.length) ? (
                <Text style={{ color: c.sub, fontSize: 15, lineHeight: 21, padding: space }}>
                  {t(scan === "nowifi" ? "discoverNoWifi" : bridgeParam ? "bridgeNone" : "discoverNone")}
                </Text>
              ) : null}
              <Row icon="refresh" label={t("discoverAgain")} onPress={startScan} />
            </>
          )}
          {!manual && !picked ? <><Divider /><Row icon="create-outline" label={t("discoverManual")} onPress={() => setManual(true)} /></> : null}
        </Section>
      ) : null}

      {manual || picked ? (<>
      <Section title={t("printerType")} footer={t.table.printerTypeHints[type]}>
        <Row icon="print-outline" label={typeLabel(type)} value={viaBridge && !isNew ? undefined : t("change")}
          onPress={viaBridge && !isNew ? undefined : () => setSheet("type")} />
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

      {!(WEB_APP && !viaBridge) ? (
      <Section title={t("lanAddress")} footer={t(!viaBridge ? "lanAddressHint" : isNew ? "bridgeAddressHint" : "bridgeAccessHint")}>
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
        {!viaBridge ? (
          <>
            <Divider />
            <View style={{ padding: space }}>
              <Button kind="secondary" title={t("testConnection")} icon="wifi-outline" onPress={testConnection}
                loading={testing} disabled={!address.trim() || missingCreds} />
              {test ? <Text style={{ color: test.ok ? c.ok : c.danger, marginTop: 10, fontSize: 14 }}>{test.text}</Text> : null}
            </View>
          </>
        ) : null}
      </Section>
      ) : null}
      {type === "prusalink" && !(WEB_APP && !viaBridge) ? <Text style={{ color: c.sub, fontSize: 13, marginTop: -12, marginBottom: 20, marginHorizontal: 16 }}>
        {t("prusaHint")}</Text> : null}
      {type === "octoprint" && !(WEB_APP && !viaBridge) ? <Text style={{ color: c.sub, fontSize: 13, marginTop: -12, marginBottom: 20, marginHorizontal: 16 }}>
        {t("octoHint")}</Text> : null}

      <Section title={t("printerNameAuto")} footer={name.trim() ? undefined : t("printerNameAutoHint", { name: autoName })}>
        <TextInput value={name} onChangeText={setName} placeholder={autoName} placeholderTextColor={c.sub}
          accessibilityLabel={t("printerName")} style={input} maxLength={60} />
      </Section>

      </>) : null}

      {!isNew ? (
        <Section>
          <Row icon="desktop-outline" label={t("orcaRow")}
            onPress={() => router.push({ pathname: "/orca-upload/[id]", params: { id, name } })} />
          <Divider />
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
