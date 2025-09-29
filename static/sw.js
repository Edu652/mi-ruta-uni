const CACHE_NAME = 'mi-ruta-cache-v1';
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
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Cache abierta');
        return cache.addAll(urlsToCache);
      })
  );
});

// Evento de "fetch": intercepta las peticiones de red.
self.addEventListener('fetch', event => {
  event.respondWith(
    // Intenta encontrar la respuesta en la caché.
    caches.match(event.request)
      .then(response => {
        // Si se encuentra en caché, la devuelve.
        if (response) {
          return response;
        }
        // Si no, hace la petición a la red.
        return fetch(event.request);
      })
  );
});