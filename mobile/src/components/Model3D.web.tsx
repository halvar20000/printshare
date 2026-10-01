// Web build: the same viewer page in an iframe (react-native-webview has no web version).
import { useEffect, useRef, useState } from "react";
import type { StyleProp, ViewStyle } from "react-native";

import type { ViewerMessage } from "./Model3D";

export type { ViewerMessage } from "./Model3D";

export function Model3D({ html, model, onMessage }: {
  html: string; model: { b64: string; ext: string } | null; onMessage: (m: ViewerMessage) => void;
  style?: StyleProp<ViewStyle>;
}) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const listen = (e: MessageEvent) => {
      if (e.source !== ref.current?.contentWindow) return;
      try {
        const m = JSON.parse(e.data) as ViewerMessage;
        if (m.type === "ready") setReady(true);
        onMessage(m);
      } catch { /* not ours */ }
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, [onMessage]);
  useEffect(() => {
    if (ready && model) ref.current?.contentWindow?.postMessage({ b64: model.b64, ext: model.ext }, "*");
  }, [ready, model]);
  return <iframe ref={ref} srcDoc={html} style={{ flex: 1, border: 0, width: "100%", height: "100%" }} title="3D" />;
}
