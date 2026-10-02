// AI failure detection on a printer card (server 0.23.0): a small status chip while it watches, a red box with the
// checked camera frame on an alert - "false alarm" mutes it for the rest of the print, "pause" stops the printer.
import Ionicons from "@expo/vector-icons/Ionicons";
import { Image } from "expo-image";
import { Text, View } from "react-native";

import { Button } from "@/components/ui";
import type { WatchState } from "@/lib/api";
import { useApp } from "@/lib/app";
import { useColors } from "@/lib/theme";

export function WatchInfo({ printer, watch, onMute, onPause, busy }: {
  printer: string; watch: WatchState; onMute: () => void; onPause: () => void; busy: string;
}) {
  const { api, t } = useApp();
  const c = useColors();
  if (watch.state === "alert") {
    return (
      <View style={{ marginTop: 14, borderRadius: 12, borderWidth: 2, borderColor: c.danger, padding: 12 }}>
        <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 8 }}>
          <Ionicons name="warning" size={20} color={c.danger} style={{ marginRight: 8 }} />
          <Text style={{ color: c.danger, fontSize: 16, fontWeight: "700", flex: 1 }}>{t("watchAlert")}</Text>
        </View>
        <Text style={{ color: c.text, fontSize: 14, marginBottom: 10 }}>
          {watch.paused ? t("watchPaused") : t("watchCheck")}
        </Text>
        {watch.frame ? (
          <Image source={{ uri: api?.imageUrl(`/api/printers/${encodeURIComponent(printer)}/watch/frame?t=${watch.last_check ?? 0}`) }}
            contentFit="cover" style={{ width: "100%", aspectRatio: 4 / 3, borderRadius: 8, marginBottom: 10 }} />
        ) : null}
        <View style={{ flexDirection: "row", gap: 10 }}>
          <Button kind="secondary" title={t("watchFalseAlarm")} icon="checkmark" onPress={onMute} style={{ flex: 1 }}
            loading={busy === `${printer}:mute`} />
          {!watch.paused ? (
            <Button kind="danger" title={t("pause")} icon="pause" onPress={onPause} style={{ flex: 1 }}
              loading={busy === `${printer}:pause`} />
          ) : null}
        </View>
      </View>
    );
  }
  if (watch.state === "idle") return null;
  const label = watch.error ? t("watchError", { error: watch.error }) : t(watch.state === "warming" ? "watchWarming"
    : watch.state === "muted" ? "watchMuted" : "watchActive");
  return (
    <View style={{ flexDirection: "row", alignItems: "center", marginTop: 12 }}>
      <Ionicons name={watch.error ? "alert-circle-outline" : "eye-outline"} size={16} color={watch.error ? c.danger : c.sub}
        style={{ marginRight: 6 }} />
      <Text style={{ color: watch.error ? c.danger : c.sub, fontSize: 13, flex: 1 }} numberOfLines={2}>{label}</Text>
    </View>
  );
}
