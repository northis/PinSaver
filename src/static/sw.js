const CACHE_NAME = 'pinsaver-v1';
const STATIC_ASSETS = [
    '/',
    '/static/styles.css',
    '/static/app.js',
    '/static/manifest.json'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(STATIC_ASSETS);
        })
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) => name !== CACHE_NAME)
                    .map((name) => caches.delete(name))
            );
        })
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);
    
    // Handle share target POST requests
    if (url.pathname === '/share' && event.request.method === 'POST') {
        event.respondWith(handleShare(event.request));
        return;
    }
    
    // Network first for API calls
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(event.request).catch(() => {
                return new Response(JSON.stringify({ error: 'Offline' }), {
                    headers: { 'Content-Type': 'application/json' }
                });
            })
        );
        return;
    }
    
    // Cache first for static assets
    event.respondWith(
        caches.match(event.request).then((response) => {
            return response || fetch(event.request);
        })
    );
});

async function handleShare(request) {
    const formData = await request.formData();
    const title = formData.get('title') || '';
    const text = formData.get('text') || '';
    const url = formData.get('url') || '';
    
    // Extract Pinterest pin URL and info
    const sharedContent = `${title} ${text} ${url}`.trim();
    
    // Redirect to share handler page with data
    const params = new URLSearchParams({
        title: title,
        text: text,
        url: url
    });
    
    return Response.redirect(`/share-handler?${params.toString()}`, 303);
}
