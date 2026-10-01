// Small schematic drawing of an OrcaSlicer infill pattern (server 0.15.2 `infill_pattern`), not to scale.
import Svg, { ClipPath, Defs, Path, Rect } from "react-native-svg";

import { useColors } from "@/lib/theme";

const N = 60;                                        // tile size
const lines = (angle: number, gap: number) => {      // parallel lines through the tile at `angle` degrees
  const a = (angle * Math.PI) / 180, dx = Math.cos(a), dy = Math.sin(a), nx = -dy, ny = dx;
  let d = "";
  for (let o = -N; o <= N; o += gap) {
    const cx = N / 2 + nx * o, cy = N / 2 + ny * o;
    d += `M${(cx - dx * N).toFixed(1)} ${(cy - dy * N).toFixed(1)}L${(cx + dx * N).toFixed(1)} ${(cy + dy * N).toFixed(1)}`;
  }
  return d;
};
const zigzag = (gap: number, amp: number) => {
  let d = "";
  for (let y = gap / 2; y < N; y += gap) {
    d += `M0 ${y}`;
    for (let x = 0; x <= N; x += 6) d += `L${x} ${y + ((x / 6) % 2 ? amp : -amp)}`;
  }
  return d;
};
const hexes = (r: number) => {
  let d = "";
  const h = r * Math.sqrt(3);
  for (let row = -1; (row * h) / 2 < N + h; row++) {
    for (let col = -1; col * r * 3 < N + r * 3; col++) {
      const cx = col * r * 3 + (row % 2 ? r * 1.5 : 0), cy = row * h / 2;
      d += [0, 1, 2, 3, 4, 5, 6].map(i => {
        const a = (Math.PI / 3) * i;
        return `${i ? "L" : "M"}${(cx + r * Math.cos(a)).toFixed(1)} ${(cy + r * Math.sin(a)).toFixed(1)}`;
      }).join("");
    }
  }
  return d;
};
const waves = (gap: number, phase: number) => {
  let d = "";
  for (let y = 0; y <= N + gap; y += gap) {
    d += `M0 ${y}`;
    for (let x = 0; x <= N; x += 2) d += `L${x} ${(y + Math.sin((x / N) * 4 * Math.PI + phase) * gap * 0.35).toFixed(1)}`;
  }
  return d;
};
const concentric = (gap: number) => {
  let d = "";
  for (let i = gap / 2; i < N / 2; i += gap) d += `M${i} ${i}H${N - i}V${N - i}H${i}Z`;
  return d;
};
const spiral = (turns: number, star = false) => {
  let d = `M${N / 2} ${N / 2}`;
  for (let t = 0; t < turns * 2 * Math.PI; t += 0.15) {
    const r = (t / (turns * 2 * Math.PI)) * (N / 2) * (star ? 1 + 0.25 * Math.cos(8 * t) : 1);
    d += `L${(N / 2 + r * Math.cos(t)).toFixed(1)} ${(N / 2 + r * Math.sin(t)).toFixed(1)}`;
  }
  return d;
};
const hilbert = (order: number) => {
  const pts: [number, number][] = [];
  const n = 2 ** order;
  for (let i = 0; i < n * n; i++) {
    let t = i, x = 0, y = 0;
    for (let s = 1; s < n; s *= 2) {
      const rx = 1 & (t >> 1), ry = 1 & (t ^ rx);
      if (ry === 0) { if (rx === 1) { x = s - 1 - x; y = s - 1 - y; } [x, y] = [y, x]; }
      x += s * rx; y += s * ry; t >>= 2;
    }
    pts.push([(x + 0.5) * (N / n), (y + 0.5) * (N / n)]);
  }
  return pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
};
const lightning = () => "M30 60L30 40L18 24L12 6M30 40L42 22L48 4M18 24L28 10M42 22L34 8";

function patternPath(p: string): string {
  switch (p) {
    case "grid": return lines(0, 10) + lines(90, 10);
    case "line": case "rectilinear": case "alignedrectilinear": case "crosshatch": return lines(45, 8);
    case "triangles": case "cubic": case "adaptivecubic": case "quartercubic": case "supportcubic":
      return lines(0, 12) + lines(60, 12) + lines(120, 12);
    case "tri-hexagon": return lines(0, 16) + lines(60, 16) + lines(120, 16) + lines(30, 1000);
    case "honeycomb": case "3dhoneycomb": case "lateral-honeycomb": return hexes(7);
    case "lateral-lattice": return lines(30, 10) + lines(150, 10);
    case "gyroid": case "tpmsd": case "tpmsfk": return waves(10, 0) + waves(10, Math.PI);
    case "zigzag": case "crosszag": case "lockedzag": return zigzag(10, 3);
    case "concentric": return concentric(6);
    case "hilbertcurve": return hilbert(3);
    case "archimedeanchords": return spiral(4);
    case "octagramspiral": return spiral(4, true);
    case "lightning": return lightning();
    default: return lines(45, 8);
  }
}

export function InfillTile({ pattern, size = 44 }: { pattern: string | null | undefined; size?: number }) {
  const c = useColors();
  return (
    <Svg width={size} height={size} viewBox={`0 0 ${N} ${N}`} accessibilityElementsHidden>
      <Defs>
        <ClipPath id="infill-tile"><Rect x={0} y={0} width={N} height={N} rx={8} /></ClipPath>
      </Defs>
      <Rect x={0} y={0} width={N} height={N} rx={8} fill={c.input} />
      <Path d={patternPath(pattern ?? "")} stroke={c.accent} strokeWidth={1.6} fill="none" strokeLinejoin="round"
        clipPath="url(#infill-tile)" />
      <Rect x={0} y={0} width={N} height={N} rx={8} fill="none" stroke={c.line} strokeWidth={1} />
    </Svg>
  );
}
