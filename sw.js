/* 纳指100定投工作台 Service Worker  v9
 * 目标：让"添加到主屏幕"的 PWA 每次都拿到最新页面，绝不卡在旧缓存上。
 * 关键修正（针对"刷新一直在转 / 页面停旧版"）：
 *   1. sw.js 自身 network-first —— 部署新 SW 时一定能拉到新脚本，保证自更新。
 *   2. 激活时对所有已打开页面 client.navigate(url) 强制跳转刷新，
 *      哪怕旧页面没有监听 RELOAD 消息也能被换掉（旧版只 postMessage，旧页忽略就卡死）。
 *   3. HTML 导航 network-first + no-store + 时间戳绕过 CDN/浏览器缓存，强制最新。
 */
const CACHE = 'ndx-dca-v9';
const HTML = '/ndx-dca/';

self.addEventListener('install', e => { self.skipWaiting(); });

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
    // 强制所有已打开页面跳到最新版（旧页即使没监听消息也会被换成新页）
    const cls = await self.clients.matchAll({ includeUncontrolled: true, type: 'window' });
    cls.forEach(c => {
      try { c.navigate(c.url); }
      catch (_) { try { c.postMessage({ type: 'RELOAD' }); } catch (_) {} }
    });
  })());
});

self.addEventListener('message', e => {
  if (e.data && e.data.type === 'RELOAD') { try { self.skipWaiting(); } catch (_) {} }
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // sw.js 自身：network-first，保证部署新版本时一定能更新（不读旧缓存）
  // 同时兼容带版本戳的注册 URL（如 sw.js?v=5）
  if (url.pathname.endsWith('/sw.js') || url.pathname === '/sw.js') {
    e.respondWith((async () => {
      try {
        const net = await fetch(req, { cache: 'no-store' });
        const c = await caches.open(CACHE);
        c.put(req, net.clone());
        return net;
      } catch (err) {
        const c = await caches.match(req);
        if (c) return c;
        return new Response('', { status: 503 });
      }
    })());
    return;
  }

  // 导航请求（HTML 文档）：带时间戳绕过缓存，强制最新；失败回退缓存
  if (req.mode === 'navigate' || url.pathname === HTML || url.pathname.endsWith('/')) {
    e.respondWith((async () => {
      const busted = url.origin + url.pathname + (url.search ? '&' : '?') + '_=' + Date.now();
      try {
        const net = await fetch(busted, { cache: 'no-store' });
        const c = await caches.open(CACHE);
        try { c.put(req, net.clone()); } catch (_) {}
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

  // 其它同源静态资源：cache-first，缺失再走网络
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
