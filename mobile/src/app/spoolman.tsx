// Spoolman (spec MA-07): address of the user's Spoolman server (kept on this phone) and bookings waiting for a decision.
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { BookingCard } from "@/components/bookings";
import { Banner, Button, Divider, Row, Screen, Section } from "@/components/ui";
import { useApp } from "@/lib/app";
import { loadBookings, loadSpoolmanUrl, saveSpoolmanUrl, Spoolman, type Booking } from "@/lib/spoolman";
import { space, useColors } from "@/lib/theme";

export default function SpoolmanScreen() {
  const { server, t } = useApp();
  const c = useColors();
  const [url, setUrl] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [bookings, setBookings] = useState<Booking[]>([]);

  const reload = useCallback(() => {
    if (!server) return;
    loadSpoolmanUrl(server).then(u => { setSaved(u); setUrl(v => v || u || ""); });
    loadBookings(server).then(setBookings);
  }, [server]);
  useFocusEffect(reload);

  const check = async (address: string) => {
    setTesting(true);
    setTest(null);
    try {
      const sm = new Spoolman(address);
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

  const save = async () => {
    if (!server || !(await check(url))) return;
    await saveSpoolmanUrl(server, url);
    setSaved(url.trim());
  };
  const remove = async () => {
    if (!server) return;
    await saveSpoolmanUrl(server, null);
    setSaved(null);
    setUrl("");
    setTest(null);
  };

  if (!server) return null;
  const input = { color: c.text, fontSize: 16, paddingHorizontal: space, paddingVertical: 14 };
  const open = bookings.filter(b => b.ask);
  const waiting = bookings.filter(b => !b.ask);
  return (
    <Screen footer={<Button title={t("save")} icon="checkmark" onPress={save} loading={testing}
      disabled={!url.trim() || url.trim() === saved} />}>
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
        {saved ? <><Divider /><Row icon="trash-outline" label={t("spoolmanRemove")} danger onPress={remove} /></> : null}
      </Section>

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
