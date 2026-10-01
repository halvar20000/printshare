// 3D view of a model before slicing (MQ-06): a small three.js page shown in a WebView (iframe on the web build).
// The app hands over the file with showModel(base64, ext); the page answers with messages
// {type: "ready" | "loaded" | "error", ...} through ReactNativeWebView.postMessage (or parent.postMessage on the web).

const THREE = "https://cdn.jsdelivr.net/npm/three@0.170.0";

export function viewerHtml(colors: { bg: string; model: string; grid: string; text: string }, bed = 256): string {
  return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<style>html,body{margin:0;height:100%;overflow:hidden;background:${colors.bg};font-family:system-ui,sans-serif}
#info{position:absolute;left:0;right:0;bottom:10px;text-align:center;color:${colors.text};font-size:13px;pointer-events:none}</style>
<script type="importmap">{"imports":{"three":"${THREE}/build/three.module.js","three/addons/":"${THREE}/examples/jsm/"}}</script>
</head><body><div id="info"></div>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { ThreeMFLoader } from "three/addons/loaders/3MFLoader.js";

const post = m => { const s = JSON.stringify(m);
  if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(s); else parent.postMessage(s, "*"); };
const BED = ${bed};
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color("${colors.bg}");
const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 1, 5000);
scene.add(new THREE.HemisphereLight(0xffffff, 0x666666, 2.2));
const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(150, 300, 200); scene.add(sun);
const grid = new THREE.GridHelper(BED, BED / 10, "${colors.grid}", "${colors.grid}");
scene.add(grid);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
camera.position.set(BED * 0.8, BED * 0.7, BED * 0.9); controls.update();
addEventListener("resize", () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight); });
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

let current = null;
window.showModel = (b64, ext) => {
  try {
    const bin = atob(b64), bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const mat = new THREE.MeshStandardMaterial({ color: "${colors.model}", roughness: 0.6, metalness: 0.05 });
    let obj;
    if (ext === "stl") obj = new THREE.Mesh(new STLLoader().parse(bytes.buffer), mat);
    else if (ext === "obj") obj = new OBJLoader().parse(new TextDecoder().decode(bytes));
    else if (ext === "3mf") obj = new ThreeMFLoader().parse(bytes.buffer);
    else throw new Error("unsupported");
    if (ext !== "3mf") obj.traverse(o => { if (o.isMesh) o.material = mat; });
    obj.rotation.x = -Math.PI / 2;                 // printers are Z-up, three.js is Y-up
    const holder = new THREE.Group(); holder.add(obj);
    holder.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(holder);
    const size = box.getSize(new THREE.Vector3());
    // centre on the bed and stand on it
    holder.position.set(-(box.min.x + box.max.x) / 2, -box.min.y, -(box.min.z + box.max.z) / 2);
    if (current) scene.remove(current);
    scene.add(holder); current = holder;
    const r = Math.max(size.x, size.y, size.z, 20);
    controls.target.set(0, size.y / 2, 0);
    camera.position.set(r * 2.1, r * 1.7 + size.y / 2, r * 2.4); controls.update();
    const dims = [size.x, size.z, size.y].map(v => v.toFixed(1)).join(" × ");
    document.getElementById("info").textContent = dims + " mm";
    post({ type: "loaded", size: [size.x, size.z, size.y] });
  } catch (e) { post({ type: "error", message: String(e && e.message || e) }); }
};
addEventListener("message", e => { let m = e.data; try { if (typeof m === "string") m = JSON.parse(m); } catch {}
  if (m && m.b64) window.showModel(m.b64, m.ext); });
post({ type: "ready" });
</script></body></html>`;
}

/** File types the 3D view can show (STEP is sliceable but needs a CAD kernel to display). */
export const viewable = (name: string) => /\.(stl|obj|3mf)$/i.test(name);
export const extOf = (name: string) => (name.match(/\.([a-z0-9]+)$/i)?.[1] ?? "").toLowerCase();
