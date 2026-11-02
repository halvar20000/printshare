// PocketPrint3D: the classic page's service worker is retired (0.47.0). Since then the web app is served at / of home
// servers too; an old worker caching "/" would sit between the browser and it. This version removes its caches and
// unregisters itself, so browsers that installed the classic page fetch everything from the server again.
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith("printshare-")).map(k => caches.delete(k))))
    .then(() => self.registration.unregister())
    .then(() => self.clients.matchAll({ type: "window" }))
    .then(clients => clients.forEach(c => c.navigate(c.url).catch(() => {}))));
});
