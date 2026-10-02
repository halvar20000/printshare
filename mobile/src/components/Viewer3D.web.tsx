// Web build: the same page in an iframe; calls go in as messages {call, arg}.
import { useEffect, useRef, useState } from "react";
import type { StyleProp, ViewStyle } from "react-native";

import type { ViewerMessage } from "./Model3D";
import type { ViewerCall } from "./Viewer3D";

export function Viewer3D({ html, calls, onMessage }: {
  html: string; calls: (ViewerCall | null)[]; onMessage: (m: ViewerMessage) => void; style?: StyleProp<ViewStyle>;
}) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const sent = useRef<unknown[]>([]);
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
    if (!ready) return;
    calls.forEach((c, i) => {
      if (!c || sent.current[i] === c.arg) return;
      sent.current[i] = c.arg;
      ref.current?.contentWindow?.postMessage({ call: c.name, arg: c.arg }, "*");
    });
  }, [ready, calls]);
  return <iframe ref={ref} srcDoc={html} style={{ flex: 1, border: 0, width: "100%", height: "100%" }} title="3D" />;
}
