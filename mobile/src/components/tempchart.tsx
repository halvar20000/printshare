// Temperature history as a line chart (issue #5): actual solid, target dashed, one colour per heater.
import { Platform, Text, View } from "react-native";
import Svg, { G, Line, Path, Text as SvgText } from "react-native-svg";

import type { TempHistory } from "@/lib/api";
import { useApp } from "@/lib/app";
import { useColors } from "@/lib/theme";

// react-native-svg text defaults to a serif font in browsers
const FONT = Platform.OS === "web" ? "system-ui, sans-serif" : undefined;
const COLORS: Record<string, string> = { nozzle: "#FF8A00", bed: "#2F6FED", chamber: "#2DB84D" };

export function TempChart({ series, width, height = 180 }: {
  series: TempHistory["series"]; width: number; height?: number;
}) {
  const { t } = useApp();
  const c = useColors();
  const names = Object.keys(series).filter(k => series[k].length > 1);
  if (!names.length) {
    return <Text style={{ color: c.sub, fontSize: 13, padding: 16, lineHeight: 18 }}>{t("historyEmpty")}</Text>;
  }
  const pad = { l: 36, r: 8, t: 8, b: 20 };
  const w = width - pad.l - pad.r, h = height - pad.t - pad.b;
  const tMin = Math.min(...names.map(n => series[n][0][0]), -60);
  let vMax = 0;
  for (const n of names) for (const [, a, tg] of series[n]) vMax = Math.max(vMax, a ?? 0, tg ?? 0);
  vMax = Math.max(50, Math.ceil((vMax + 5) / 50) * 50);
  const x = (s: number) => pad.l + (1 - s / tMin) * w;        // tMin (oldest, negative) -> left, 0 -> right
  const y = (v: number) => pad.t + h - (v / vMax) * h;
  const line = (pts: [number, number | null][]) => {
    let d = "", pen = false;
    for (const [s, v] of pts) {
      if (v == null) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${x(s).toFixed(1)} ${y(v).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  const ticks = [0, vMax / 2, vMax];
  const minutes = Math.round(-tMin / 60);
  return (
    <View>
      <Svg width={width} height={height}>
        {ticks.map(v => (
          <Line key={v} x1={pad.l} x2={pad.l + w} y1={y(v)} y2={y(v)} stroke={c.line} strokeWidth={1} />
        ))}
        {ticks.map(v => (
          <SvgText key={`l${v}`} x={pad.l - 6} y={y(v) + 4} fontSize={11} fontFamily={FONT} fill={c.sub} textAnchor="end">{`${v}°`}</SvgText>
        ))}
        <SvgText x={pad.l} y={height - 4} fontSize={11} fontFamily={FONT} fill={c.sub}>{t("minutesAgo", { m: minutes })}</SvgText>
        <SvgText x={pad.l + w} y={height - 4} fontSize={11} fontFamily={FONT} fill={c.sub} textAnchor="end">0</SvgText>
        {names.map(n => {
          const color = COLORS[n] ?? c.accent;
          const target = series[n].filter(p => p[2] != null && p[2] > 0).length
            ? line(series[n].map(p => [p[0], p[2]])) : "";
          return (
            <G key={n}>
              {target ? <Path d={target} stroke={color} strokeWidth={1.5} strokeDasharray="5 4" fill="none" opacity={0.7} /> : null}
              <Path d={line(series[n].map(p => [p[0], p[1]]))} stroke={color} strokeWidth={2.2} fill="none"
                strokeLinejoin="round" strokeLinecap="round" />
            </G>
          );
        })}
      </Svg>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 14, paddingHorizontal: 12, paddingBottom: 10 }}>
        {names.map(n => (
          <View key={n} style={{ flexDirection: "row", alignItems: "center" }}>
            <View style={{ width: 14, height: 3, borderRadius: 2, backgroundColor: COLORS[n] ?? c.accent, marginRight: 6 }} />
            <Text style={{ color: c.sub, fontSize: 12 }}>{t.table.heaterNames[n] ?? n}</Text>
          </View>
        ))}
        <Text style={{ color: c.sub, fontSize: 12 }}>— {t("actual")}  ┄ {t("target")}</Text>
      </View>
    </View>
  );
}
