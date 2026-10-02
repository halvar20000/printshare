// Spoolman (spec MA-07): where the spools are - the user's own Spoolman (address kept on this phone) or, for cloud
// accounts, the PocketPrint3D cloud (server 0.17.0) - and bookings waiting for a decision.
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { BookingCard } from "@/components/bookings";
import { Banner, Button, Divider, Row, Screen, Section, Segmented } from "@/components/ui";
import { useApp } from "@/lib/app";
import { CLOUD_SPOOLS, loadBookings, loadSpoolmanUrl, openSpoolman, saveSpoolmanUrl, type Booking } from "@/lib/spoolman";
import { space, useColors } from "@/lib/theme";

type Mode = "cloud" | "own";

export default function SpoolmanScreen() {
  const { server, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const cloud = !!server?.cloud;
  const [mode, setMode] = useState<Mode | null>(null);
  const [url, setUrl] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [bookings, setBookings] = useState<Booking[]>([]);

  const reload = useCallback(() => {
    if (!server) return;
    loadSpoolmanUrl(server).then(u => {
      setSaved(u);
      setMode(m => m ?? (u && u !== CLOUD_SPOOLS ? "own" : cloud ? "cloud" : "own"));
      if (u && u !== CLOUD_SPOOLS) setUrl(v => v || u);
      if (u === CLOUD_SPOOLS) openSpoolman(server, u).spools().then(l => setCount(l.length)).catch(() => setCount(null));
    });
    loadBookings(server).then(setBookings);
  }, [server, cloud]);
  useFocusEffect(reload);

  const check = async (address: string) => {
    if (!server) return false;
    setTesting(true);
    setTest(null);
    try {
      const sm = openSpoolman(server, address);
      const [info, spools] = [await sm.info(), await sm.spools()];
      setTest({ ok: true, text: t("spoolmanOk", { version: info.version, n: spools.length }) });
      return true;
    } catch (e) {
      setTest({ ok: false, text: t("spoolmanUnreachable", { error: (e as Error).message }) });
      return false;
    } finally {
      setTesting(false);
    }
  };

  const save = async (value: string) => {
    if (!server || (value !== CLOUD_SPOOLS && !(await check(value)))) return;
    await saveSpoolmanUrl(server, value);
    setSaved(value.trim());
    if (value === CLOUD_SPOOLS) reload();
  };
  const remove = async () => {
    if (!server) return;
    await saveSpoolmanUrl(server, null);
    setSaved(null);
    setUrl("");
    setTest(null);
  };

  if (!server || !mode) return null;
  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  const open = bookings.filter(b => b.ask);
  const waiting = bookings.filter(b => !b.ask);
  const cloudOn = saved === CLOUD_SPOOLS;
  const footer = mode === "cloud"
    ? (!cloudOn ? <Button title={t("spoolsUseCloud")} icon="cloud-outline" onPress={() => save(CLOUD_SPOOLS)} /> : null)
    : <Button title={t("save")} icon="checkmark" onPress={() => save(url)} loading={testing}
        disabled={!url.trim() || url.trim() === saved} />;
  return (
    <Screen footer={footer}>
      {cloud ? (
        <Section title={t("spoolsWhere")} footer={mode === "cloud" ? t("spoolsCloudHint") : undefined}>
          <View style={{ padding: 12 }}>
            <Segmented<Mode> values={["cloud", "own"]} value={mode} onChange={m => { setMode(m); setTest(null); }}
              labels={{ cloud: t("spoolsInCloud"), own: t("spoolsOwnServer") }} />
          </View>
          {mode === "cloud" && cloudOn ? (
            <>
              <Divider />
              <Row icon="disc-outline" label={t("spoolsManage")} value={count != null ? t("spoolsCount", { n: count }) : undefined}
                onPress={() => router.push("/spools")} />
              <Divider />
              <Row icon="close-circle-outline" label={t("spoolmanRemove")} danger onPress={remove} />
            </>
          ) : null}
        </Section>
      ) : null}

      {mode === "own" ? (
        <Section title={t("spoolmanAddress")} footer={t("spoolmanHint")}>
          <TextInput value={url} onChangeText={v => { setUrl(v); setTest(null); }} placeholder="192.168.1.20:7912"
            placeholderTextColor={c.sub} autoCapitalize="none" autoCorrect={false} keyboardType="url"
            accessibilityLabel={t("spoolmanAddress")} style={input} />
          <Divider />
          <View style={{ padding: space }}>
            <Button kind="secondary" title={t("testConnection")} icon="wifi-outline" onPress={() => check(url)}
              loading={testing} disabled={!url.trim()} />
            {test ? <Text style={{ color: test.ok ? c.ok : c.danger, marginTop: 10, fontSize: 14 }}>{test.text}</Text> : null}
          </View>
          {saved && !cloudOn ? <><Divider /><Row icon="trash-outline" label={t("spoolmanRemove")} danger onPress={remove} /></> : null}
        </Section>
      ) : null}

      {open.length || waiting.length ? <Text style={{ color: c.sub, fontSize: 13, marginBottom: 8, marginLeft: 16 }}>
        {t("bookingsOpen").toUpperCase()}</Text> : null}
      {open.map(b => <BookingCard key={b.id} server={server} booking={b} onDone={reload} />)}
      {waiting.length ? (
        <Section>
          {waiting.map((b, i) => (
            <View key={b.id}>
              {i ? <Divider /> : null}
              <Row icon="time-outline" label={b.file} sub={`${b.printerName} · ${t("bookingWaits")}`}
                value={`${b.uses.reduce((a, u) => a + u.grams, 0).toFixed(1)} g`} />
            </View>
          ))}
        </Section>
      ) : null}
      {!saved && bookings.length ? <Banner kind="warn" text={t("spoolmanOff")} /> : null}
    </Screen>
  );
}
