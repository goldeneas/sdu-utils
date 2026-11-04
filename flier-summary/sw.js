// Offline-capable service worker. Bump VERSION when you change the app files so installed copies refresh.
const VERSION = 'v7';
const CACHE = `flier-summary-${VERSION}`;
const PRECACHE = [
  './',
  'index.html',
  'app.js',
  'pwa.js',
  'manifest.webmanifest',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/icon-180.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(PRECACHE.map((u) => new Request(u, { cache: 'reload' }))))
      // the offers file is optional at install time; it is cached on first successful load
      .then(() => caches.open(CACHE).then((c) => c.add(new Request('data/offers.json', { cache: 'reload' })).catch(() => {})))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return; // product images come from the flier CDN

  // Pages, scripts and the offers data are network-first, so a new day's offers show on the next open.
  // The cached copy is the offline fallback.
  if (req.mode === 'navigate' || /\.(html|js|json)$/.test(url.pathname) || url.pathname.endsWith('/')) {
    event.respondWith(
      fetch(req.url, { cache: 'no-cache' })
        .then((res) => {
          if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(url.pathname.endsWith('offers.json') ? 'data/offers.json' : req, copy)); }
          return res;
        })
        .catch(() => caches.match(url.pathname.endsWith('offers.json') ? 'data/offers.json' : req, { ignoreSearch: true })
          .then((r) => r || (req.mode === 'navigate' ? caches.match('index.html') : Response.error())))
    );
    return;
  }

  // Everything else (icons): cache-first, refreshed in the background.
  event.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(req, { ignoreSearch: true });
      const network = fetch(req).then((res) => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => undefined);
      return cached || (await network) || Response.error();
    })
  );
});
