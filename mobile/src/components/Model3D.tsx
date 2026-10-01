// The three.js page from lib/viewer3d.ts in a WebView; the model goes in once the page says "ready".
import { useEffect, useRef, useState } from "react";
import type { StyleProp, ViewStyle } from "react-native";
import { WebView } from "react-native-webview";

export type ViewerMessage = { type: "ready" | "loaded" | "error"; size?: number[]; message?: string };

export function Model3D({ html, model, onMessage, style }: {
  html: string; model: { b64: string; ext: string } | null; onMessage: (m: ViewerMessage) => void;
  style?: StyleProp<ViewStyle>;
}) {
  const ref = useRef<WebView>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (ready && model) ref.current?.injectJavaScript(`window.showModel(${JSON.stringify(model.b64)}, "${model.ext}"); true;`);
  }, [ready, model]);
  return (
    <WebView ref={ref} source={{ html, baseUrl: "https://pocketprint3d.com/" }} originWhitelist={["*"]}
      javaScriptEnabled style={[{ flex: 1, backgroundColor: "transparent" }, style]} scrollEnabled={false}
      onMessage={e => {
        try {
          const m = JSON.parse(e.nativeEvent.data) as ViewerMessage;
          if (m.type === "ready") setReady(true);
          onMessage(m);
        } catch { /* not ours */ }
      }} />
  );
}
