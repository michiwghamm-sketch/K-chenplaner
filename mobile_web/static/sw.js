// Service Worker fuer die mobile Einkaufslisten-Ansicht - cacht besuchte Seiten/Assets, damit
// die zuletzt geladene Liste auch ohne Internet (z. B. schlechtes Netz auf dem Zeltplatz) noch
// sichtbar bleibt. Schreibende Aktionen (POST) werden hier bewusst NICHT abgefangen - dafuer
// sorgt offline.js mit einer lokalen Warteschlange, die bei wiederhergestellter Verbindung
// automatisch nachgesendet wird.
const CACHE_NAME = "zelakueche-v1";

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return; // POST/etc. immer direkt ans Netz - Warteschlange uebernimmt offline.js.
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        // Nur erfolgreiche Antworten cachen (kein 4xx/5xx, z. B. nicht die Login-Fehlerseite).
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
