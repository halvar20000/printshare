// 3D view of the chosen model file before slicing (MQ-06): rotate with one finger, zoom with two.
import { Stack, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { Model3D, type ViewerMessage } from "@/components/Model3D";
import { Banner } from "@/components/ui";
import { useApp } from "@/lib/app";
import { loadModelBase64 } from "@/lib/modelFile";
import { space, useColors } from "@/lib/theme";
import { extOf, viewable, viewerHtml } from "@/lib/viewer3d";

const MAX_BYTES = 40 * 1024 * 1024;     // bigger files take too long to hand over for a preview

export default function Model3DScreen() {
  const { link, file, name } = useLocalSearchParams<{ link: string; file?: string; name: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const [model, setModel] = useState<{ b64: string; ext: string } | null>(null);
  const [loadError, setError] = useState("");
  const [size, setSize] = useState<number[] | null>(null);
  const error = name && !viewable(name) ? t("view3dUnsupported") : loadError;
  const html = useMemo(() => viewerHtml({ bg: c.bg, model: c.accent, grid: c.line, text: c.sub }), [c]);

  useEffect(() => {
    if (!api || !link || !name || !viewable(name)) return;
    let alive = true;
    (async () => {
      try {
        const { url, headers } = await api.modelFileDownload(link, file || null);
        const { b64 } = await loadModelBase64(url, headers, name, MAX_BYTES);
        if (alive) setModel({ b64, ext: extOf(name) });
      } catch (e) {
        if (alive) setError(e instanceof RangeError ? t("view3dTooBig") : `${t("view3dFailed")} ${(e as Error).message}`);
      }
    })();
    return () => { alive = false; };
  }, [api, link, file, name, t]);

  const onMessage = useCallback((m: ViewerMessage) => {
    if (m.type === "loaded") setSize(m.size ?? null);
    if (m.type === "error") setError(`${t("view3dFailed")} ${m.message ?? ""}`);
  }, [t]);

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <Stack.Screen options={{ title: name ?? t("view3d") }} />
      {error ? <View style={{ padding: space }}><Banner kind="error" text={error} /></View> : null}
      {!error ? <Model3D html={html} model={model} onMessage={onMessage} /> : null}
      {!error && !size ? (
        <View style={{ position: "absolute", top: 0, bottom: 0, left: 0, right: 0, alignItems: "center", justifyContent: "center" }}
          pointerEvents="none">
          <ActivityIndicator color={c.accent} size="large" />
          <Text style={{ color: c.sub, marginTop: 12 }}>{t(model ? "view3dPreparing" : "view3dLoading")}</Text>
        </View>
      ) : null}
      {size ? <Text style={{ color: c.sub, fontSize: 13, textAlign: "center", padding: 10 }}>{t("view3dHint")}</Text> : null}
    </View>
  );
}
