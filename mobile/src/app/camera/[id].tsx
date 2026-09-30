// Fullscreen printer camera (issue #3): live MJPEG through the PocketPrint3D server, or still images.
import { Stack, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Platform, Text, View, useWindowDimensions } from "react-native";
import { Image } from "expo-image";
import { WebView } from "react-native-webview";

import { CameraImage } from "@/components/camera";
import { Segmented } from "@/components/ui";
import type { CameraInfo } from "@/lib/api";
import { useApp } from "@/lib/app";
import { space } from "@/lib/theme";

type Mode = "live" | "still";

function LiveStream({ uri }: { uri: string }) {
  if (Platform.OS === "web") {
    // browsers show MJPEG in an <img> directly
    return <Image source={{ uri }} contentFit="contain" style={{ flex: 1 }} />;
  }
  const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{margin:0;height:100%;background:#000}img{width:100%;height:100%;object-fit:contain}</style></head>
<body><img src="${uri.replace(/"/g, "&quot;")}"></body></html>`;
  return (
    <WebView source={{ html }} originWhitelist={["*"]} mixedContentMode="always" scrollEnabled={false}
      style={{ flex: 1, backgroundColor: "#000" }} containerStyle={{ backgroundColor: "#000" }}
      allowsInlineMediaPlayback javaScriptEnabled={false} />
  );
}

export default function CameraScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const { api, t } = useApp();
  const { width } = useWindowDimensions();
  const [info, setInfo] = useState<CameraInfo | null>(null);
  const [modePref, setModePref] = useState<Mode | null>(null);
  const [streamUri, setStreamUri] = useState<string | null>(null);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    api.cameraInfo(id).then(i => { if (alive) setInfo(i); }).catch(() => { if (alive) setInfo(null); });
    // the MJPEG view can't send headers, so its URL carries the token
    api.cameraSource(id, "stream", undefined, true).then(s => { if (alive) setStreamUri(s.uri); }).catch(() => {});
    return () => { alive = false; };
  }, [api, id]);

  // away from home (Tailscale) still images by default: live is ~300 KB/s
  const away = api?.route() === "remote";
  const mode: Mode = modePref ?? (info?.stream && !away ? "live" : "still");
  const h = Math.min(width, 900) * 9 / 16;

  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <Stack.Screen options={{ title: name ?? t("camera"), headerStyle: { backgroundColor: "#000" }, headerTintColor: "#fff",
        headerTitleStyle: { color: "#fff" } }} />
      {info?.stream ? (
        <View style={{ padding: space }}>
          <Segmented<Mode> values={["live", "still"]} value={mode} onChange={setModePref}
            labels={{ live: t("cameraLive"), still: t("cameraStill") }} />
        </View>
      ) : null}
      <View style={{ flex: 1, justifyContent: "center" }}>
        <View style={{ width: "100%", maxWidth: 900, height: h, alignSelf: "center" }}>
          {mode === "live" && streamUri ? <LiveStream uri={streamUri} />
            : <CameraImage printer={id} width={away ? 960 : 1280} intervalMs={away ? 3000 : 1000}
                contentFit="contain" style={{ flex: 1 }} />}
        </View>
      </View>
      {info?.stream ? (
        <Text style={{ color: "#9A9AA2", fontSize: 12, textAlign: "center", padding: space }}>{t("cameraDataHint")}</Text>
      ) : null}
    </View>
  );
}
