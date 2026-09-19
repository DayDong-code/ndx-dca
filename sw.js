/* 纳指100定投工作台 Service Worker
 * 策略：HTML 导航请求每次都带时间戳绕过 CDN/浏览器缓存，强制拿最新页面（部署后立即生效）；
 *       离线时回退到缓存。静态资源 cache-first。
 * 这样添加到主屏幕的 PWA 打开即最新，无需删了重装图标。 */
const CACHE = 'ndx-dca-v3';
const HTML = '/ndx-dca/';

self.addEventListener('install', e => { self.skipWaiting(); });

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
    // 立即让所有已打开页面刷新到最新版，避免停留在旧缓存页
    const cls = await self.clients.matchAll({ includeUncontrolled: true });
    cls.forEach(c => c.postMessage({ type: 'RELOAD' }));
  })());
});

self.addEventListener('message', e => {
  if (e.data && e.data.type === 'RELOAD') { try { self.skipWaiting(); } catch (_) {} }
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // 导航请求（HTML 文档）：带时间戳绕过缓存，强制最新；失败回退缓存
  if (req.mode === 'navigate' || url.pathname === HTML || url.pathname.endsWith('/')) {
    e.respondWith((async () => {
      const busted = url.origin + url.pathname + (url.search ? '&' : '?') + '_=' + Date.now();
      try {
        const net = await fetch(busted, { cache: 'no-store' });
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
