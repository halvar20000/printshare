// PrintShare service worker: makes the app installable and keeps the shell available
// offline. Network first, so a new deploy is picked up on the next start; the API is
// never cached.
const CACHE = "printshare-shell-v1";
const SHELL = ["/", "/static/app.css", "/static/app.js", "/manifest.webmanifest",
               "/static/icons/icon-192.png", "/static/icons/favicon.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // share-target and ?token= links all load the same shell
  const key = e.request.mode === "navigate" ? "/" : e.request;
  e.respondWith(
    fetch(e.request, { cache: "no-cache" })
      .then(r => {
        if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(key, copy)); }
        return r;
      })
      .catch(() => caches.match(key).then(r => r || Response.error())));
});
