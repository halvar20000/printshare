// Spoolman bookings the user has to decide (print cancelled or its end missed): book all, the printed share or nothing.
import { useState } from "react";
import { Text, View } from "react-native";

import { Button, Card } from "@/components/ui";
import type { Server } from "@/lib/api";
import { useApp } from "@/lib/app";
import { resolveBooking, type Booking } from "@/lib/spoolman";
import { useColors } from "@/lib/theme";

const sum = (b: Booking) => b.uses.reduce((a, u) => a + u.grams, 0);
const g = (v: number) => (Math.round(v * 10) / 10).toFixed(1);

export function BookingCard({ server, booking: b, onDone }: { server: Server; booking: Booking; onDone: () => void }) {
  const { t } = useApp();
  const c = useColors();
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  const part = b.ask?.part ?? 1;
  const decide = async (p: number) => {
    setBusy(p);
    setError("");
    try {
      await resolveBooking(server, b.id, p);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card style={{ padding: 16, marginBottom: 16 }}>
      <Text style={{ color: c.text, fontSize: 15, lineHeight: 21 }}>
        {t("bookingAsk", { file: b.file, printer: b.printerName })}
      </Text>
      <Text style={{ color: c.sub, fontSize: 13, marginTop: 6 }}>
        {b.uses.map(u => `${g(u.grams)} g → ${u.label}`).join("\n")}
      </Text>
      {error ? <Text style={{ color: c.danger, fontSize: 13, marginTop: 6 }}>{error}</Text> : null}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
        <Button title={t("bookAll", { g: g(sum(b)) })} onPress={() => decide(1)} loading={busy === 1}
          disabled={busy != null} style={{ flexGrow: 1 }} />
        {part > 0.01 && part < 0.99 ? (
          <Button kind="secondary" title={t("bookPart", { g: g(sum(b) * part), pct: Math.round(part * 100) })}
            onPress={() => decide(part)} loading={busy === part} disabled={busy != null} style={{ flexGrow: 1 }} />
        ) : null}
        <Button kind="plain" title={t("bookNone")} onPress={() => decide(0)} loading={busy === 0}
          disabled={busy != null} style={{ flexGrow: 1 }} />
      </View>
    </Card>
  );
}

/** "Spoolman: 11.4 g booked on #3 Elegoo PLA" */
export const bookedText = (t: ReturnType<typeof useApp>["t"], b: Booking) =>
  t("booked", { g: g(sum(b)), spool: b.uses.map(u => u.label).join(", ") });
