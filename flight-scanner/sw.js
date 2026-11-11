// Keep this cache scoped to flight-scanner; sibling PWAs share the Pages origin.
const CACHE = "flight-scanner-v3";
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
      // A first deployment might not have any flight data yet.
      await caches
        .open(DATA_CACHE)
        .then((dataCache) =>
          dataCache.add(new Request(DATA, { cache: "reload" })),
        )
        .catch(() => {});
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
      .then(() => self.clients.claim()),
  );
});
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || !url.href.startsWith(self.registration.scope))
    return;
  const isLatest = url.origin + url.pathname === DATA;
  const isHistory = url.pathname.startsWith(
    new URL("data/history/", self.registration.scope).pathname,
  );
  const isData = isLatest || isHistory;
  const key = isLatest ? DATA : request;
  event.respondWith(
    (async () => {
      const cache = await caches.open(isData ? DATA_CACHE : CACHE);
      try {
        const response = await fetch(request, {
          cache: "no-cache",
          signal: AbortSignal.timeout(isData ? 45000 : 7000),
        });
        if (!response.ok) throw new Error("Unavailable");
        if (isLatest) {
          // Do not replace a working offline snapshot with a malformed response.
          const data = await response.clone().json();
          if (data.schema_version !== 1 || !Array.isArray(data.top))
            throw new Error("Invalid snapshot");
        }
        await cache.put(key, response.clone()).catch(() => {});
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
