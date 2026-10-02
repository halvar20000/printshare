// A three.js page (lib/gcode3d.ts) in a WebView: `calls` go in as window.<name>(arg) once the page says "ready", each
// again whenever its argument changes (the big G-code data once, the small view settings on every slider move).
import { useEffect, useRef, useState } from "react";
import type { StyleProp, ViewStyle } from "react-native";
import { WebView } from "react-native-webview";

import type { ViewerMessage } from "./Model3D";

export type ViewerCall = { name: string; arg: unknown };

export function Viewer3D({ html, calls, onMessage, style }: {
  html: string; calls: (ViewerCall | null)[]; onMessage: (m: ViewerMessage) => void; style?: StyleProp<ViewStyle>;
}) {
  const ref = useRef<WebView>(null);
  const [ready, setReady] = useState(false);
  const sent = useRef<unknown[]>([]);
  useEffect(() => {
    if (!ready) return;
    calls.forEach((c, i) => {
      if (!c || sent.current[i] === c.arg) return;
      sent.current[i] = c.arg;
      ref.current?.injectJavaScript(`window.${c.name}(${JSON.stringify(c.arg)}); true;`);
    });
  }, [ready, calls]);
  return (
    <WebView ref={ref} source={{ html, baseUrl: "https://pocketprint3d.com/" }} originWhitelist={["*"]}
      javaScriptEnabled style={[{ flex: 1, backgroundColor: "transparent" }, style]} scrollEnabled={false}
      nestedScrollEnabled
      onMessage={e => {
        try {
          const m = JSON.parse(e.nativeEvent.data) as ViewerMessage;
          if (m.type === "ready") setReady(true);
          onMessage(m);
        } catch { /* not ours */ }
      }} />
  );
}
