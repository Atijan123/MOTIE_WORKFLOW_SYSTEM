// The service worker (step 12h). It makes the app installable and shows a
// plain "no connection" page when the network is down. It stores NO Ministry
// data: pages and API answers always come from the server, so nothing about a
// case is left on a staff PC or phone. Only the offline page is kept.
const CACHE = "motie-offline-v1";
const OFFLINE = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.add(OFFLINE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // Remove caches from older versions of this file.
  event.waitUntil(
    caches.keys().then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // Only page loads get the offline fallback; everything else goes straight
  // to the network as if there were no service worker.
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});
