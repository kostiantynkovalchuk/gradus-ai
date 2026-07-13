// Minimal service worker — required for Chrome's PWA install prompt.
// Strategy: network-only pass-through for everything (no caching of
// lesson audio, beat videos, or API responses). The only goal here is
// satisfying Chrome's installability check; offline support is out of
// scope and aggressive caching would risk serving stale JS/HTML.
//
// Scope: registered from "/" (served by an explicit FastAPI route in
// app.py, not from /static/) so it covers the full app origin.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => e.respondWith(fetch(e.request)));
