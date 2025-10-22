const CACHE_VERSION = 'v2';
const RUNTIME_CACHE = `mi-ruta-runtime-${CACHE_VERSION}`;
const PRECACHE = `mi-ruta-precache-${CACHE_VERSION}`;
// Lista de ficheros que componen el "esqueleto" de la app.
const urlsToCache = [
  '/',
  '/static/manifest.json',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png'
];

// Evento de instalación: se abre la caché y se guardan los ficheros.
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(PRECACHE).then(cache => cache.addAll(urlsToCache))
  );
  self.skipWaiting();
});

// Evento de "fetch": intercepta las peticiones de red.
self.addEventListener('activate', event => {
  // Limpiar cachés antiguas
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys
        .filter(key => key.startsWith('mi-ruta-') && ![PRECACHE, RUNTIME_CACHE].includes(key))
        .map(key => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Bypass non-GET
  if (request.method !== 'GET') return;

  // Network-first for HTML navigations to always get fresh content
  if (request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html')) {
    event.respondWith(
      fetch(request)
        .then(response => {
          const copy = response.clone();
          caches.open(RUNTIME_CACHE).then(cache => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request))
        .catch(() => caches.match('/'))
    );
    return;
  }

  // Stale-while-revalidate for static assets (CSS, JS, images, manifest)
  if (url.pathname.startsWith('/static/') || url.origin.includes('fonts.googleapis.com') || url.origin.includes('fonts.gstatic.com')) {
    event.respondWith(
      caches.match(request, { ignoreSearch: true }).then(cached => {
        const fetchPromise = fetch(request).then(networkResponse => {
          caches.open(RUNTIME_CACHE).then(cache => cache.put(request, networkResponse.clone()));
          return networkResponse;
        }).catch(() => cached);
        return cached || fetchPromise;
      })
    );
    return;
  }

  // Default: try cache, then network
  event.respondWith(
    caches.match(request).then(res => res || fetch(request))
  );
});