// 3D view of the sliced G-code (issue #4): the toolpaths of /api/jobs/{id}/preview stacked by layer height, as lines,
// in a three.js page (WebView, iframe on the web build). The app calls
//   window.setData({unit, version, bed, bounds, layers})   once,
//   window.view({layer, mode, colors: {key: "#rrggbb"}, hidden: [key]})   on every change (slider, legend, colour mode);
// the page answers {type: "ready" | "loaded" | "error"} like lib/viewer3d.ts.
// All layers sit in one line buffer: the slider only changes the drawn range; the current layer is drawn on top in
// full colour, the ones below dimmed. The buffer is only rebuilt when the colours or hidden line types change.

const THREE = "https://cdn.jsdelivr.net/npm/three@0.170.0";

export function gcode3dHtml(colors: { bg: string; grid: string }): string {
  return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<style>html,body{margin:0;height:100%;overflow:hidden;background:${colors.bg}}</style>
<script type="importmap">{"imports":{"three":"${THREE}/build/three.module.js","three/addons/":"${THREE}/examples/jsm/"}}</script>
</head><body>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const post = m => { const s = JSON.stringify(m);
  if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(s); else parent.postMessage(s, "*"); };
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color("${colors.bg}");
const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 0.5, 5000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
addEventListener("resize", () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight); });
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

let data = null, sig = "", positions = null, colorsArr = null, starts = [], ends = [];
let below = null, top = null, grid = null;
const dimMat = new THREE.LineBasicMaterial({ vertexColors: true, color: 0x8a8a8a });   // multiplies the vertex colours
const topMat = new THREE.LineBasicMaterial({ vertexColors: true });

window.setData = d => {
  try {
    data = d; sig = "";
    const bw = d.bed ? d.bed[0] : 256, bh = d.bed ? d.bed[1] : 256;
    if (grid) scene.remove(grid);
    grid = new THREE.GridHelper(Math.max(bw, bh), Math.round(Math.max(bw, bh) / 10), "${colors.grid}", "${colors.grid}");
    scene.add(grid);
    const [x0, y0, x1, y1] = d.bounds || [0, 0, bw, bh];
    const h = d.layers.length ? d.layers[d.layers.length - 1].z : 10;
    const cx = (x0 + x1) / 2 - bw / 2, cz = -((y0 + y1) / 2 - bh / 2);
    const r = Math.max(x1 - x0, y1 - y0, h, 20);
    controls.target.set(cx, h / 2, cz);
    camera.position.set(cx + r * 1.15, h / 2 + r * 0.95, cz + r * 1.35);
    controls.update();
    post({ type: "loaded" });
  } catch (e) { post({ type: "error", message: String(e && e.message || e) }); }
};

function build(v) {
  const off = data.version >= 2 ? 2 : 1, u = data.unit;
  const bw = data.bed ? data.bed[0] : 256, bh = data.bed ? data.bed[1] : 256;
  const hidden = new Set(v.hidden), keyOf = p => (v.mode === "color" ? (off === 2 ? p[1] : 0) : p[0]);
  let n = 0;                                            // segments
  for (const l of data.layers) for (const p of l.paths) if (!hidden.has(keyOf(p))) n += Math.max(0, (p.length - off) / 2 - 1);
  positions = new Float32Array(n * 6); colorsArr = new Float32Array(n * 6); starts = []; ends = [];
  const rgb = {}, c = new THREE.Color();
  for (const [k, hex] of Object.entries(v.colors)) { c.set(hex); rgb[k] = [c.r, c.g, c.b]; }
  let s = 0;
  data.layers.forEach(l => {
    starts.push(s);
    const z = l.z;
    for (const p of l.paths) {
      const k = keyOf(p);
      if (hidden.has(k)) continue;
      const col = rgb[k] || [0.5, 0.5, 0.5];
      for (let i = off; i + 3 < p.length; i += 2) {
        const o = s * 6;
        positions[o] = p[i] / u - bw / 2; positions[o + 1] = z; positions[o + 2] = -(p[i + 1] / u - bh / 2);
        positions[o + 3] = p[i + 2] / u - bw / 2; positions[o + 4] = z; positions[o + 5] = -(p[i + 3] / u - bh / 2);
        colorsArr.set(col, o); colorsArr.set(col, o + 3);
        s++;
      }
    }
    ends.push(s);
  });
  if (below) { scene.remove(below); below.geometry.dispose(); }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  g.setAttribute("color", new THREE.BufferAttribute(colorsArr, 3));
  below = new THREE.LineSegments(g, dimMat); below.frustumCulled = false;
  scene.add(below);
}

function showLayer(n) {
  n = Math.max(0, Math.min(n, ends.length - 1));
  below.geometry.setDrawRange(0, starts[n] * 2);
  if (top) { scene.remove(top); top.geometry.dispose(); }
  const g = new THREE.BufferGeometry();         // the current layer: views into the big buffers, no copy
  g.setAttribute("position", new THREE.BufferAttribute(positions.subarray(starts[n] * 6, ends[n] * 6), 3));
  g.setAttribute("color", new THREE.BufferAttribute(colorsArr.subarray(starts[n] * 6, ends[n] * 6), 3));
  top = new THREE.LineSegments(g, topMat); top.frustumCulled = false;
  scene.add(top);
}

window.view = v => {
  if (!data) return;
  try {
    const s = v.mode + "|" + v.hidden.join(",") + "|" + JSON.stringify(v.colors);
    if (s !== sig) { build(v); sig = s; }
    showLayer(v.layer);
  } catch (e) { post({ type: "error", message: String(e && e.message || e) }); }
};
// web build: commands arrive as messages from the app frame
addEventListener("message", e => { const m = e.data;
  if (m && m.call === "setData") window.setData(m.arg); else if (m && m.call === "view") window.view(m.arg); });
post({ type: "ready" });
</script></body></html>`;
}
