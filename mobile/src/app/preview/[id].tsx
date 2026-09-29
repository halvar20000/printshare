// G-code layer viewer (spec SL-06/SL-07): top view per layer, colours by line type, layer slider.
import Ionicons from "@expo/vector-icons/Ionicons";
import Slider from "@react-native-community/slider";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View, useWindowDimensions } from "react-native";
import Svg, { G, Path, Rect } from "react-native-svg";

import { Button, Card, Empty, Segmented, tap } from "@/components/ui";
import type { Preview } from "@/lib/api";
import { useApp } from "@/lib/app";
import { space, useColors } from "@/lib/theme";

// Similar to OrcaSlicer's own preview colours, readable on light and dark backgrounds.
const TYPE_COLORS: Record<string, string> = {
  "Outer wall": "#FF8A00", "Inner wall": "#F2C200", "Overhang wall": "#2F6FED", "Sparse infill": "#C8322B",
  "Internal solid infill": "#9B51E0", "Top surface": "#E0457B", "Bottom surface": "#5E7CE2", "Bridge": "#4DA3D9",
  "Gap infill": "#8A8A8A", "Skirt": "#1B998B", "Brim": "#1B998B", "Support": "#2DB84D", "Support interface": "#1E7F35",
  "Support transition": "#62C370", "Prime tower": "#7A5C3E", "Ironing": "#FF5C8A", "Custom": "#7F8C8D",
};
const FALLBACK = ["#00A6A6", "#B36BFF", "#FF6B6B", "#6BCB77", "#4D96FF"];

type Mode = "type" | "color";
/** Group key of a path: its line type, or its filament (tool) in colour mode. Version 1 had no tool. */
const keyOf = (p: number[], mode: Mode, v2: boolean) => (mode === "color" ? (v2 ? p[1] : 0) : p[0]);

function pathData(paths: number[][], unit: number, flipY: number, mode: Mode, v2: boolean,
                  filter?: (k: number) => boolean) {
  const off = v2 ? 2 : 1;
  const byType = new Map<number, string[]>();
  for (const p of paths) {
    const t = keyOf(p, mode, v2);
    if (filter && !filter(t)) continue;
    let d = `M${p[off] / unit} ${flipY - p[off + 1] / unit}`;
    for (let i = off + 2; i < p.length; i += 2) d += `L${p[i] / unit} ${flipY - p[i + 1] / unit}`;
    const list = byType.get(t) ?? [];
    list.push(d);
    byType.set(t, list);
  }
  return [...byType].map(([t, ds]) => ({ t, d: ds.join("") }));
}

export default function PreviewScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const { width } = useWindowDimensions();
  const [data, setData] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [layer, setLayer] = useState(0);
  const [hidden, setHidden] = useState<Set<string>>(new Set());   // "type:3" / "color:1"
  const [modePref, setModePref] = useState<Mode | null>(null);
  const [view, setView] = useState<"model" | "plate">("model");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    api.preview(id)
      .then(p => { if (alive) { setData(p); setLayer(Math.max(0, p.layers.length - 1)); setError(""); } })
      .catch(e => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [api, id, attempt]);

  const size = Math.min(width, 640) - space * 2;
  const frame = useMemo(() => {
    if (!data?.bounds) return null;
    const [x0, y0, x1, y1] = data.bounds;
    const bedW = data.bed?.[0] ?? Math.max(x1, 1), bedH = data.bed?.[1] ?? Math.max(y1, 1);
    if (view === "plate") return { x: 0, y: 0, w: bedW, h: bedH, bedW, bedH };
    const m = Math.max(4, Math.max(x1 - x0, y1 - y0) * 0.06);
    const w = x1 - x0 + 2 * m, h = y1 - y0 + 2 * m, s = Math.max(w, h);
    // square view centred on the model; y is flipped (G-code y points up)
    return { x: x0 - m - (s - w) / 2, y: bedH - y1 - m - (s - h) / 2, w: s, h: s, bedW, bedH };
  }, [data, view]);

  const v2 = (data?.version ?? 1) >= 2;
  // filaments used anywhere in the print; colour mode only makes sense with more than one
  const tools = useMemo(() => {
    const s = new Set<number>();
    if (v2) data?.layers.forEach(l => l.paths.forEach(p => s.add(p[1])));
    return [...s].sort((a, b) => a - b);
  }, [data, v2]);
  const mode: Mode = modePref ?? (tools.length > 1 ? "color" : "type");
  const current = useMemo(() => {
    if (!data || !frame || !data.layers[layer]) return [];
    return pathData(data.layers[layer].paths, data.unit, frame.bedH, mode, v2, k => !hidden.has(`${mode}:${k}`));
  }, [data, frame, layer, hidden, mode, v2]);
  const below = useMemo(() => {
    if (!data || !frame || layer === 0) return [];
    return pathData(data.layers[layer - 1].paths, data.unit, frame.bedH, mode, v2);
  }, [data, frame, layer, mode, v2]);
  // 10 mm grid on the build plate for orientation
  const grid = useMemo(() => {
    if (!frame) return "";
    let d = "";
    for (let x = 10; x < frame.bedW; x += 10) d += `M${x} 0V${frame.bedH}`;
    for (let y = 10; y < frame.bedH; y += 10) d += `M0 ${frame.bedH - y}H${frame.bedW}`;
    return d;
  }, [frame]);
  const present = useMemo(() => {
    const s = new Set<number>();
    data?.layers[layer]?.paths.forEach(p => s.add(keyOf(p, mode, v2)));
    return s;
  }, [data, layer, mode, v2]);

  if (!data) {
    return (
      <View style={{ flex: 1, backgroundColor: c.bg, justifyContent: "center" }}>
        {error ? <Empty icon="cloud-offline-outline" title={error}>
          <Button kind="secondary" title={t("tryAgain")} onPress={() => setAttempt(a => a + 1)} />
        </Empty> : <ActivityIndicator size="large" color={c.accent} />}
      </View>
    );
  }
  if (!data.layers.length || !frame) {
    return <View style={{ flex: 1, backgroundColor: c.bg, justifyContent: "center" }}><Empty icon="layers-outline" title={t("previewEmpty")} /></View>;
  }

  const color = (k: number) => mode === "color"
    ? data.filament_colors?.[k] ?? FALLBACK[k % FALLBACK.length]
    : TYPE_COLORS[data.types[k]] ?? FALLBACK[k % FALLBACK.length];
  const legend: { k: number; label: string }[] = mode === "color"
    ? tools.map(k => ({ k, label: t("colorN", { n: k + 1 }) }))
    : data.types.map((name, k) => ({ k, label: t.table.lineTypes[name] ?? name }));
  const stroke = Math.max(frame.w / size * 1.6, 0.3);   // about 1.6 px on screen, at least 0.3 mm
  const last = data.layers.length - 1;
  const step = (d: number) => { tap(); setLayer(l => Math.min(last, Math.max(0, l + d))); };

  return (
    <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={{ padding: space, maxWidth: 640, width: "100%", alignSelf: "center" }}>
      <View style={{ marginBottom: 12 }}>
        <Segmented values={["model", "plate"]} value={view} onChange={v => setView(v as "model" | "plate")}
          labels={{ model: t("fitModel"), plate: t("wholePlate") }} />
        {tools.length > 1 ? (
          <View style={{ marginTop: 8 }}>
            <Segmented values={["color", "type"]} value={mode} onChange={v => setModePref(v as Mode)}
              labels={{ color: t("byColor"), type: t("byLineType") }} />
          </View>
        ) : null}
      </View>
      <Card style={{ padding: 0, marginBottom: 14, backgroundColor: c.input }}>
        <Svg width={size} height={size} viewBox={`${frame.x} ${frame.y} ${frame.w} ${frame.h}`}
          accessibilityLabel={t("layerOf", { n: layer + 1, total: last + 1 })}>
          <Rect x={0} y={0} width={frame.bedW} height={frame.bedH} fill={c.card} stroke={c.line} strokeWidth={stroke} />
          <Path d={grid} stroke={c.line} strokeWidth={stroke * 0.5} fill="none" />
          <G opacity={0.25}>
            {below.map(({ t: ty, d }) => <Path key={`b${ty}`} d={d} stroke={c.sub} strokeWidth={stroke} fill="none" />)}
          </G>
          {mode === "color" ? (
            // thin dark outline, so white or very light filament stays visible on the plate
            <G opacity={0.45}>
              {current.map(({ t: ty, d }) => (
                <Path key={`o${ty}`} d={d} stroke={c.text} strokeWidth={stroke * 1.7} fill="none" strokeLinecap="round" strokeLinejoin="round" />
              ))}
            </G>
          ) : null}
          {current.map(({ t: ty, d }) => (
            <Path key={`c${ty}`} d={d} stroke={color(ty)} strokeWidth={stroke} fill="none" strokeLinecap="round" strokeLinejoin="round" />
          ))}
        </Svg>
      </Card>

      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <Text style={{ color: c.text, fontSize: 17, fontWeight: "700" }}>{t("layerOf", { n: layer + 1, total: last + 1 })}</Text>
        <Text style={{ color: c.sub, fontSize: 15 }}>Z {data.layers[layer].z.toFixed(2)} mm</Text>
      </View>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        <Pressable onPress={() => step(-1)} disabled={layer === 0} hitSlop={10} accessibilityRole="button" accessibilityLabel={t("prevLayer")}>
          <Ionicons name="remove-circle-outline" size={30} color={layer === 0 ? c.track : c.accent} />
        </Pressable>
        <Slider style={{ flex: 1, height: 40 }} minimumValue={0} maximumValue={last} step={1} value={layer}
          onValueChange={v => setLayer(Math.round(v))} minimumTrackTintColor={c.accent} maximumTrackTintColor={c.track}
          thumbTintColor={c.accent} accessibilityLabel={t("layerOf", { n: layer + 1, total: last + 1 })} />
        <Pressable onPress={() => step(1)} disabled={layer === last} hitSlop={10} accessibilityRole="button" accessibilityLabel={t("nextLayer")}>
          <Ionicons name="add-circle-outline" size={30} color={layer === last ? c.track : c.accent} />
        </Pressable>
      </View>

      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 14 }}>
        {legend.map(({ k, label }) => {
          const key = `${mode}:${k}`, off = hidden.has(key), here = present.has(k);
          return (
            <Pressable key={key} accessibilityRole="button" accessibilityState={{ selected: !off }}
              onPress={() => { tap(); setHidden(h => { const n = new Set(h); if (n.has(key)) n.delete(key); else n.add(key); return n; }); }}
              style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999,
                backgroundColor: c.card, opacity: off ? 0.4 : here ? 1 : 0.65 }}>
              <View style={{ width: 12, height: 12, borderRadius: 3, backgroundColor: color(k), marginRight: 6,
                borderWidth: 1, borderColor: c.line }} />
              <Text style={{ color: c.text, fontSize: 13, textDecorationLine: off ? "line-through" : "none" }}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
    </ScrollView>
  );
}
