// Spool and NFC reader for printers with one slot (tool 0: Centauri Carbon without CANVAS, Prusa …), on the control
// page: which spool is in the printer (shown; the print screen proposes it), the chip the reader last saw ("which spool
// is this?" for a new one), and the reader key for the ESP32 + PN5180 firmware (firmware/nfc-reader). Printers with
// several slots have all of this on the filament screen.
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Text, View } from "react-native";

import { Banner, Divider, PickerSheet, Row, Section, confirmAsync } from "@/components/ui";
import { errorText, type Api, type ReaderKey, type Server, type SlotSpools } from "@/lib/api";
import { useApp } from "@/lib/app";
import { loadSpoolmanUrl, openSpoolman, setSlotSpool, spoolLabel, type Spool } from "@/lib/spoolman";
import { space, useColors } from "@/lib/theme";

const SLOT = 0;

export function SpoolReader({ api, server, id }: { api: Api; server: Server; id: string }) {
  const { t } = useApp();
  const c = useColors();
  const [slots, setSlots] = useState<SlotSpools | null>(null);
  const [reader, setReader] = useState<(ReaderKey & { key?: string }) | null>(null);
  const [spools, setSpools] = useState<Spool[] | null>(null);
  const [pick, setPick] = useState<"link" | "spool" | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.slotSpools(id).then(setSlots).catch(() => setSlots(null));
    api.readerKey(id).then(r => setReader(old => (old?.key ? old : r))).catch(() => setReader(null));
    loadSpoolmanUrl(server).then(url => {
      if (url) openSpoolman(server, url).spools().then(setSpools).catch(() => setSpools([]));
    });
  }, [api, id, server]);
  useFocusEffect(useCallback(() => {
    load();
    const timer = setInterval(() => api.slotSpools(id).then(setSlots).catch(() => {}), 5000);   // a reader may report
    return () => clearInterval(timer);
  }, [load, api, id]));

  if (!slots && !reader) return null;              // older server: nothing to show
  const scan = slots?.scans?.[String(SLOT)];
  const spoolId = slots?.slots?.[String(SLOT)]?.spool;
  const spool = spools?.find(s => s.id === spoolId);
  const choices = (spools ?? []).map(s => ({ value: String(s.id), group: s.material ?? "?",
    label: `${spoolLabel(s)}${s.remaining_g != null ? ` · ${Math.round(s.remaining_g)} g` : ""}` }));

  const onPick = async (v: string) => {
    const mode = pick;
    setPick(null);
    setError("");
    try {
      if (mode === "link" && scan) await api.linkSpoolTag(scan.uid, Number(v));      // the server puts it in the slot
      else await setSlotSpool(server, id, SLOT, v === "none" ? null : Number(v), api);
      load();
    } catch (e) {
      setError(errorText(t, e));
    }
  };
  const newKey = async () => {
    if (reader?.enabled && !(await confirmAsync(t("readerKeyRenewQ"), t("readerKeyNew"), t("cancelBtn")))) return;
    try { setReader(await api.createReaderKey(id)); } catch (e) { setError(errorText(t, e)); }
  };

  return (
    <>
      {error ? <View style={{ marginBottom: space }}><Banner kind="error" text={error} /></View> : null}
      <Section title={t("spoolReaderTitle")} footer={reader?.key ? t("readerKeyHint") : t("spoolReaderHint")}>
        <Row icon="disc-outline" label={t("spoolInPrinter")}
          value={spool ? spoolLabel(spool) : spoolId != null ? `#${spoolId}` : t("spoolNone")}
          sub={spool?.remaining_g != null ? `${Math.round(spool.remaining_g)} g` : undefined}
          onPress={spools?.length ? () => setPick("spool") : undefined} />
        {scan && scan.spool == null ? (
          <>
            <Divider />
            <Row icon="help-circle-outline" label={t("readerUnknownChip")} sub={scan.uid}
              onPress={spools?.length ? () => setPick("link") : undefined} />
          </>
        ) : null}
        {reader ? (
          <>
            <Divider />
            <Row icon="radio-outline" label={t("readerTitle")} sub={reader.enabled ? t("readerOn") : t("readerOff")}
              value={reader.enabled ? t("readerKeyNew") : t("readerKeyCreate")} onPress={newKey} />
            {reader.key ? (
              <View style={{ paddingHorizontal: space, paddingBottom: space, gap: 6 }}>
                <Text style={{ color: c.sub, fontSize: 13 }}>{t("readerUrl")}</Text>
                <Text selectable style={{ color: c.text, fontSize: 14 }}>{reader.url}</Text>
                <Text style={{ color: c.sub, fontSize: 13 }}>{t("readerKey")}</Text>
                <Text selectable style={{ color: c.text, fontSize: 14, fontWeight: "600" }}>{reader.key}</Text>
                <Text style={{ color: c.sub, fontSize: 13 }}>{t("readerSlot", { slot: SLOT })}</Text>
              </View>
            ) : null}
          </>
        ) : null}
      </Section>
      <PickerSheet visible={!!pick} value={pick === "spool" && spoolId != null ? String(spoolId) : null}
        title={pick === "link" ? t("linkChipTitle", { slot: t("spoolInPrinter") }) : t("spoolInPrinter")}
        choices={pick === "spool" ? [{ value: "none", label: t("spoolNone") }, ...choices] : choices}
        onPick={onPick} onClose={() => setPick(null)} searchLabel={t("search")} closeLabel="OK" />
    </>
  );
}
