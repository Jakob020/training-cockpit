/* Training Cockpit — Service Worker
 *
 * Zweck: die App auch ohne Verbindung nutzbar machen, ohne dabei je eine
 * veraltete Version auszuliefern, solange Netz da ist.
 *
 * Strategie:
 *   - Seitenaufruf (HTML/Navigation): NETWORK-FIRST. Online kommt immer der
 *     frische Stand vom Server, offline wird auf den Cache zurueckgefallen.
 *     Damit reicht nach einem Deploy ein einziges Oeffnen der App.
 *   - Statische Assets (JS/CSS/Icons): stale-while-revalidate. Die Dateinamen
 *     sind von Vite gehasht, ein neuer Build erzeugt also neue Namen — der
 *     Cache kann hier nie eine falsche Version zurueckgeben.
 *   - /api/*: nie gecacht. Schreibzugriffe im Offline-Fall uebernimmt die
 *     Warteschlange in App.jsx (siehe loadKey/saveKey/flushPendingWrites).
 *
 * CACHE_NAME hochziehen, wenn sich die Strategie aendert — beim Aktivieren
 * werden alle Caches mit abweichendem Namen geloescht.
 */
const CACHE_NAME = "cockpit-shell-v2";
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
    caches.keys()
      .then((names) =>
        Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
      )
      .then(() => self.clients.claim())
  );
});

function isNavigationRequest(request) {
  if (request.mode === "navigate") return true;
  const accept = request.headers.get("accept") || "";
  return accept.includes("text/html");
}

/* Network-first: frische Seite, wenn erreichbar; sonst der letzte bekannte Stand. */
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cached = await caches.match(request);
    if (cached) return cached;
    const fallback = await caches.match("/index.html");
    if (fallback) return fallback;
    throw e;
  }
}

/* Stale-while-revalidate: sofort aus dem Cache, im Hintergrund erneuern. */
async function staleWhileRevalidate(request) {
  const cached = await caches.match(request);
  const network = fetch(request)
    .then(async (response) => {
      if (response && response.ok) {
        const cache = await caches.open(CACHE_NAME);
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => cached);
  return cached || network;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // API immer live, nie aus dem Cache

  event.respondWith(
    isNavigationRequest(request) ? networkFirst(request) : staleWhileRevalidate(request)
  );
});
