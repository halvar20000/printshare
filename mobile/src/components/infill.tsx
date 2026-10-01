// OrcaSlicer infill patterns as drawings (server 0.15.2 `infill_pattern`). Drawn in millimetres: the line width
// comes from the quality profile, the spacing from density and pattern - like Orca, one layer seen from above.
//   InfillTile:    small icon for the picker row
//   InfillPreview: 3 x 3 cm at real size (Android: 160 dp = 1 inch; close to real size on most phones)
import { Text, View } from "react-native";
import Svg, { ClipPath, Defs, G, Path, Rect } from "react-native-svg";

import { useColors } from "@/lib/theme";

const MM = 30;                                       // drawing area in mm
const f = (v: number) => v.toFixed(2);

function lines(angle: number, gap: number): string {
  const a = (angle * Math.PI) / 180, dx = Math.cos(a), dy = Math.sin(a), nx = -dy, ny = dx;
  let d = "";
  for (let o = -MM; o <= MM; o += gap) {
    const cx = MM / 2 + nx * o, cy = MM / 2 + ny * o;
    d += `M${f(cx - dx * MM)} ${f(cy - dy * MM)}L${f(cx + dx * MM)} ${f(cy + dy * MM)}`;
  }
  return d;
}
function zigzag(gap: number): string {               // connected lines with short turns (Orca zig zag family)
  let d = "";
  for (let y = gap / 2, i = 0; y < MM + gap; y += gap, i++) {
    d += i % 2 ? `L${MM} ${f(y)}L0 ${f(y)}` : `${i ? "L" : "M"}0 ${f(y)}L${MM} ${f(y)}`;
  }
  return d;
}
function hexes(side: number): string {
  const h = side * Math.sqrt(3);
  let d = "";
  for (let row = -1; (row * h) / 2 < MM + h; row++) {
    for (let col = -1; col * side * 3 < MM + side * 3; col++) {
      const cx = col * side * 3 + (row % 2 ? side * 1.5 : 0), cy = (row * h) / 2;
      for (let i = 0; i <= 6; i++) {
        const a = (Math.PI / 3) * i;
        d += `${i ? "L" : "M"}${f(cx + side * Math.cos(a))} ${f(cy + side * Math.sin(a))}`;
      }
    }
  }
  return d;
}
function waves(gap: number, phase: number): string { // gyroid / TPMS cut: wavy lines
  let d = "";
  for (let y = 0; y <= MM + gap; y += gap) {
    for (let x = 0; x <= MM; x += 0.4) {
      d += `${x ? "L" : "M"}${f(x)} ${f(y + Math.sin((x / gap) * Math.PI + phase) * gap * 0.3)}`;
    }
  }
  return d;
}
function concentric(gap: number): string {
  let d = "";
  for (let i = gap / 2; i < MM / 2; i += gap) d += `M${f(i)} ${f(i)}H${f(MM - i)}V${f(MM - i)}H${f(i)}Z`;
  return d;
}
function spiral(gap: number, star = false): string {
  let d = `M${MM / 2} ${MM / 2}`;
  for (let t = 0; t < (MM / gap) * Math.PI * 1.5; t += 0.05) {
    const r = ((gap * t) / (2 * Math.PI)) * (star ? 1 + 0.18 * Math.cos(8 * t) : 1);
    d += `L${f(MM / 2 + r * Math.cos(t))} ${f(MM / 2 + r * Math.sin(t))}`;
  }
  return d;
}
function hilbert(gap: number): string {
  const n = 2 ** Math.max(1, Math.min(7, Math.round(Math.log2(MM / gap))));
  let d = "";
  for (let i = 0; i < n * n; i++) {
    let t = i, x = 0, y = 0;
    for (let s = 1; s < n; s *= 2) {
      const rx = 1 & (t >> 1), ry = 1 & (t ^ rx);
      if (ry === 0) { if (rx === 1) { x = s - 1 - x; y = s - 1 - y; } [x, y] = [y, x]; }
      x += s * rx; y += s * ry; t >>= 2;
    }
    d += `${i ? "L" : "M"}${f((x + 0.5) * (MM / n))} ${f((y + 0.5) * (MM / n))}`;
  }
  return d;
}
function lightning(gap: number): string {             // tree-like support for the top only; spacing grows with gap
  let d = "";
  for (let x = gap; x < MM; x += gap * 3) {
    d += `M${f(x)} ${MM}L${f(x)} ${f(MM * 0.6)}L${f(x - gap)} ${f(MM * 0.3)}L${f(x - gap * 1.4)} 0`;
    d += `M${f(x)} ${f(MM * 0.6)}L${f(x + gap)} ${f(MM * 0.25)}L${f(x + gap * 1.2)} 0`;
  }
  return d;
}

/** Path of one layer; `density` 0..1, `width` = line width in mm. */
export function infillPath(pattern: string, density: number, width: number): string {
  const rho = Math.max(0.03, Math.min(1, density || 0.15));
  const s = (dirs: number) => (dirs * width) / rho;    // spacing so that line area / total area = density
  switch (pattern) {
    case "grid": return lines(45, s(2)) + lines(135, s(2));
    case "line": case "rectilinear": case "alignedrectilinear": case "crosshatch": return lines(45, s(1));
    case "zigzag": case "crosszag": case "lockedzag": return zigzag(s(1));
    case "triangles": case "cubic": case "adaptivecubic": case "quartercubic": case "supportcubic": case "tri-hexagon":
      return lines(0, s(3)) + lines(60, s(3)) + lines(120, s(3));
    case "lateral-lattice": return lines(60, s(2)) + lines(120, s(2));
    // honeycomb: edge length a with line length per area 1.1547/a -> a = 1.1547 w / rho
    case "honeycomb": case "3dhoneycomb": case "lateral-honeycomb": return hexes((1.1547 * width) / rho);
    case "gyroid": case "tpmsd": case "tpmsfk": return waves(s(1), 0);
    case "concentric": return concentric(s(1));
    case "hilbertcurve": return hilbert(s(1));
    case "archimedeanchords": return spiral(s(1));
    case "octagramspiral": return spiral(s(1), true);
    case "lightning": return lightning(s(1));
    default: return lines(45, s(1));
  }
}

function Drawing({ pattern, density, width, size, radius }: {
  pattern: string; density: number; width: number; size: number; radius: number;
}) {
  const c = useColors();
  const r = (radius / size) * MM;
  const clip = `infill-${Math.round(size)}`;
  return (
    <Svg width={size} height={size} viewBox={`0 0 ${MM} ${MM}`}>
      <Defs>
        <ClipPath id={clip}><Rect x={0} y={0} width={MM} height={MM} rx={r} /></ClipPath>
      </Defs>
      <Rect x={0} y={0} width={MM} height={MM} rx={r} fill={c.input} />
      <G clipPath={`url(#${clip})`}>
        <Path d={infillPath(pattern, density, width)} stroke={c.accent} strokeWidth={width} fill="none"
          strokeLinejoin="round" strokeLinecap="round" />
      </G>
      <Rect x={0} y={0} width={MM} height={MM} rx={r} fill="none" stroke={c.line} strokeWidth={MM / size} />
    </Svg>
  );
}

/** Icon for the picker row: the pattern at a coarse density so it stays readable when small. */
export function InfillTile({ pattern, size = 44 }: { pattern: string | null | undefined; size?: number }) {
  return <Drawing pattern={pattern ?? ""} density={0.12} width={0.9} size={size} radius={8} />;
}

const REAL_SIZE_DP = (MM / 25.4) * 160;              // 30 mm in dp (Android: 160 dp per inch)

/** 3 x 3 cm at real size with the profile's line width and the chosen density. */
export function InfillPreview({ pattern, density, lineWidth, caption }: {
  pattern: string; density: number; lineWidth: number | null | undefined; caption: string;
}) {
  const c = useColors();
  return (
    <View style={{ alignItems: "center", paddingVertical: 12 }}>
      <Drawing pattern={pattern} density={density} width={lineWidth || 0.45} size={REAL_SIZE_DP} radius={6} />
      <Text style={{ color: c.sub, fontSize: 12, marginTop: 8, textAlign: "center", paddingHorizontal: 16 }}>{caption}</Text>
    </View>
  );
}
