// The time-lapse of a print (server 0.32.0): play it, download / share it.
import { Stack, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Linking, Platform, View } from "react-native";

import { VideoPlayer } from "@/components/VideoPlayer";
import { Button } from "@/components/ui";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

export default function Timelapse() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const [uri, setUri] = useState<string | null>(null);
  useEffect(() => {
    api?.timelapseUrl(id).then(setUri).catch(() => {});
  }, [api, id]);
  const download = () => {
    if (!uri) return;
    if (Platform.OS === "web") globalThis.open?.(uri, "_blank");
    else Linking.openURL(uri);
  };
  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <Stack.Screen options={{ title: name ? `${t("timelapseTitle")} · ${name}` : t("timelapseTitle") }} />
      {uri ? <VideoPlayer uri={uri} /> : <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />}
      <View style={{ padding: space, backgroundColor: c.bg }}>
        <Button kind="secondary" title={t("timelapseSave")} icon="download-outline" onPress={download} disabled={!uri} />
      </View>
    </View>
  );
}
