// AiPayGen Service Worker — basic caching for PWA shell
const CACHE_NAME = 'aipaygen-v1';
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
self.addEventListener('fetch', (e) => {
  // Only cache GET requests for same origin
  if (e.request.method !== 'GET') return;

  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        // Cache successful HTML/CSS responses
        if (resp.ok && (e.request.url.includes('/try') || e.request.url.includes('/static/'))) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
        }
        return resp;
      })
      .catch(() => caches.match(e.request))
  );
});
