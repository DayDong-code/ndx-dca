/* 纳指100定投工作台 Service Worker
 * 策略：HTML 导航请求 network-first（每次都尝试拿最新页面，部署后立即生效）；
 *       离线时回退到缓存。静态资源 cache-first。
 * 这样添加到主屏幕的 PWA 打开即最新，无需删了重装图标。 */
const CACHE = 'ndx-dca-v2';
const HTML = '/ndx-dca/';

self.addEventListener('install', e => { self.skipWaiting(); });

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // 导航请求（HTML 文档）：网络优先，失败回退缓存
  if (req.mode === 'navigate' || url.pathname === HTML || url.pathname.endsWith('/')) {
    e.respondWith((async () => {
      try {
        const net = await fetch(req, { cache: 'no-store' });
        const c = await caches.open(CACHE);
        c.put(req, net.clone());
        return net;
      } catch (err) {
        const c = await caches.match(req);
        if (c) return c;
        const idx = await caches.match(HTML);
        if (idx) return idx;
        return new Response('网络不可用且未缓存', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
      }
    })());
    return;
  }

  // 其它同源静态资源：cache-first
  if (url.origin === self.location.origin) {
    e.respondWith((async () => {
      const c = await caches.match(req);
      if (c) return c;
      try {
        const net = await fetch(req);
        const cc = await caches.open(CACHE);
        cc.put(req, net.clone());
        return net;
      } catch (err) {
        return c || new Response('', { status: 404 });
      }
    })());
  }
});
