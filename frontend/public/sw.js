/* Training Cockpit — Service Worker
 *
 * Zweck: die App-Hülle (HTML/JS/CSS/Icons) offline verfügbar machen, damit das
 * Dashboard auch ohne Verbindung öffnet (z. B. unterwegs ohne Empfang). API-
 * Aufrufe (/api/*) werden NICHT gecacht — Schreibzugriffe im Offline-Fall
 * übernimmt die Warteschlange in App.jsx (siehe loadKey/saveKey).
 */
const CACHE_NAME = "cockpit-shell-v1";
const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-180.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // API immer live, nie aus dem Cache

  // Stale-while-revalidate: sofort aus dem Cache antworten (falls vorhanden),
  // im Hintergrund neu laden und den Cache aktualisieren.
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
