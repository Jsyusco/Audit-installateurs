const CACHE_NAME = 'streamlit-pwa-v1';

// On n'enregistre rien en cache pour Streamlit car le contenu est dynamique
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

// Répond aux requêtes réseau (nécessaire pour la validation PWA)
self.addEventListener('fetch', (event) => {
  event.respondWith(
    fetch(event.request).catch(() => {
      return caches.match(event.request);
    })
  );
});
