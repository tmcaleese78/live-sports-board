const CACHE_NAME = 'osp-shell-v1';
const STATIC_ASSETS = [
  '/static/favicon.png',
  '/static/logo-dark-opt.jpg?v=3',
  '/manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // Never cache live API or slip-parse endpoints
  if (url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then(cached => cached || fetch(req).then(resp => {
        if (resp && resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(req, clone)).catch(() => {});
        }
        return resp;
      }))
    );
    return;
  }
  // Network-first for HTML shell so deploys are always fresh
  event.respondWith(
    fetch(req).catch(() => caches.match(req))
  );
});
