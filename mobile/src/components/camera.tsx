// Camera still images, refreshed while visible (issue #3). Two image slots take turns: the next image
// loads into the hidden slot, which becomes visible once complete - no flicker, one download per frame.
import { Image } from "expo-image";
import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, Text, View, type StyleProp, type ViewStyle } from "react-native";

import { useApp } from "@/lib/app";
import { useColors } from "@/lib/theme";

type Source = { uri: string; headers: Record<string, string> };

export function CameraImage({ printer, width, intervalMs, style, contentFit = "cover" }: {
  printer: string; width?: number; intervalMs: number; style?: StyleProp<ViewStyle>;
  contentFit?: "cover" | "contain";
}) {
  const { api, t } = useApp();
  const c = useColors();
  const [slots, setSlots] = useState<[Source | null, Source | null]>([null, null]);
  const [visible, setVisible] = useState<0 | 1 | null>(null);
  const [failed, setFailed] = useState(false);
  const visibleRef = useRef<0 | 1 | null>(null);

  // only while the screen is visible: no downloads in the background
  useFocusEffect(useCallback(() => {
    if (!api) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const src = await api.cameraSource(printer, "snapshot", width);
        // into the slot that is not on screen
        if (alive) setSlots(s => (visibleRef.current === 0 ? [s[0], src] : [src, s[1]]));
      } catch {
        if (alive) setFailed(true);
      }
      if (alive) timer = setTimeout(tick, intervalMs);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [api, printer, width, intervalMs]));

  const fill = { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 } as const;
  return (
    <View style={[{ backgroundColor: "#000", overflow: "hidden" }, style]}>
      {slots.map((src, i) => src ? (
        <Image key={i} source={src} contentFit={contentFit} cachePolicy="none" transition={0}
          onLoad={() => { visibleRef.current = i as 0 | 1; setVisible(i as 0 | 1); setFailed(false); }}
          onError={() => setFailed(true)}
          style={[fill, { opacity: visible === i ? 1 : 0 }]} />
      ) : null)}
      {visible === null ? (
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
          {failed ? <Text style={{ color: c.sub, fontSize: 13 }}>{t("cameraOffline")}</Text>
            : <ActivityIndicator color="#fff" />}
        </View>
      ) : null}
    </View>
  );
}
