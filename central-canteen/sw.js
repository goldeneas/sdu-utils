const PREFIX = 'central-canteen-';
const CACHE = PREFIX + 'v1';
const SHELL = ['./', 'index.html', 'style.css', 'app.js', 'manifest.webmanifest', 'icons/icon-180.png', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-maskable-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL.map(url=>new Request(url,{cache:'reload'})))).then(()=>caches.open(CACHE).then(cache=>cache.add(new Request('data/menu.json',{cache:'reload'}))).catch(()=>{})).then(()=>self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith(PREFIX)&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const req=event.request, url=new URL(req.url);
  if(req.method!=='GET'||url.origin!==self.location.origin||!url.href.startsWith(self.registration.scope)) return;
  event.respondWith((async()=>{
    const cache=await caches.open(CACHE);
    try {
      const res=await fetch(req,{cache:'no-cache'});
      if(!res.ok) throw new Error('HTTP '+res.status);
      await cache.put(req,res.clone());
      return res;
    } catch {
      return await cache.match(req,{ignoreSearch:true}) || (req.mode==='navigate' ? await cache.match('index.html') : null) || Response.error();
    }
  })());
});
