// Keep this cache scoped to flight-scanner; sibling PWAs share the Pages origin.
const CACHE = "flight-scanner-v7";
// Keep data across app-shell updates, including an update during a failed daily scan.
const DATA_CACHE = "flight-scanner-data";
const SHELL = [
  "./",
  "index.html",
  "style.css",
  "app.js",
  "pwa.js",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/icon-180.png",
  "icons/icon-maskable-512.png",
];
const DATA = new URL("data/flights.json", self.registration.scope).href;
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then(async (cache) => {
      await cache.addAll(
        SHELL.map((path) => new Request(path, { cache: "reload" })),
      );
      // Only the compact index is prefetched for a first offline visit.
      const dataCache = await caches.open(DATA_CACHE);
      await Promise.all(["data/browser/latest.json", "data/history/index.json"].map((path) =>
        dataCache.add(new Request(new URL(path, self.registration.scope), {
          cache: "no-cache", signal: AbortSignal.timeout(12000),
        })).catch(() => {}),
      ));
      await self.skipWaiting();
    }),
  );
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter(
              (key) =>
                key.startsWith("flight-scanner-") &&
                key !== CACHE &&
                key !== DATA_CACHE,
            )
            .map((key) => caches.delete(key)),
        ),
      )
      .then(async () => {
        const cache = await caches.open(DATA_CACHE);
        await cache.delete(DATA);
      })
      .then(() => self.clients.claim()),
  );
});
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || !url.href.startsWith(self.registration.scope))
    return;
  const isLatest = url.origin + url.pathname === DATA;
  // Legacy clients may still request a complete scan. Do not duplicate it in memory.
  if (isLatest) return;
  const isHistory = url.pathname === new URL("data/history/index.json", self.registration.scope).pathname;
  const isData = isHistory || url.pathname.startsWith(new URL("data/browser/", self.registration.scope).pathname);
  const key = request;
  event.respondWith(
    (async () => {
      const cache = await caches.open(isData ? DATA_CACHE : CACHE);
      try {
        const response = await fetch(request, {
          cache: "no-cache",
          signal: AbortSignal.timeout(isData ? 45000 : 7000),
        });
        if (!response.ok) throw new Error("Unavailable");
        // Cache the streamed bytes without parsing another copy of the scan.
        const stored = cache.put(key, response.clone()).catch(() => {});
        if (event.waitUntil) event.waitUntil(stored);
        return response;
      } catch {
        return (
          (await cache.match(key, { ignoreSearch: true })) ||
          (request.mode === "navigate"
            ? await cache.match("index.html")
            : undefined) ||
          Response.error()
        );
      }
    })(),
  );
});
