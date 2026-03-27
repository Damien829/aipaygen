// AiPayGen Service Worker — caching for PWA shell + Expo bundles
const CACHE_NAME = 'aipaygen-v2';
const SHELL_URLS = [
  '/try',
  '/static/css/main.css',
  '/static/icon.png',
];

// Install — cache shell
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS))
  );
  self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

// Fetch — network first, fallback to cache
// Cache immutable _expo bundles (content-hashed) forever
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);

  // Immutable assets: _expo bundles with content hashes — cache-first
  if (url.pathname.includes('/_expo/static/')) {
    e.respondWith(
      caches.match(e.request).then((cached) => {
        if (cached) return cached;
        return fetch(e.request).then((resp) => {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
          }
          return resp;
        });
      })
    );
    return;
  }

  // Everything else: network-first with cache fallback
  if (url.origin === self.location.origin) {
    e.respondWith(
      fetch(e.request)
        .then((resp) => {
          if (resp.ok && (url.pathname.includes('/try') || url.pathname.includes('/static/'))) {
            const clone = resp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
          }
          return resp;
        })
        .catch(() => caches.match(e.request))
    );
  }
});
