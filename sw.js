/* 纳指100定投工作台 Service Worker  v83
 *
 * v39 性能重构（解决"从桌面进入要等很久"）：
 *   旧策略：导航请求 fetch(cache:'no-store') + Date.now() 破缓存参数 → 每次进入必然完整重下 ~413KB。
 *   新策略：
 *     1. HTML 导航用 stale-while-revalidate —— 立即返回缓存（毫秒级打开），后台静默拉新版。
 *     2. 更新检测走「版本号比对」：后台重取 index.html，比对 meta x-app-ver，
 *        发现版本变化才通知页面提示更新，避免用户看到旧数据。
 *     3. 静态资源（图标/manifest/news.json）cache-first + 后台更新。
 *     4. 保留 v38 的强制换页能力：新 SW 激活时 navigate 已打开页面，确保不卡旧版。
 */
const CACHE = 'ndx-dca-v83';
const HTML = '/ndx-dca/';
const HTML_FILE = '/ndx-dca/index.html';
const CORE = [HTML_FILE, '/ndx-dca/manifest.json', '/ndx-dca/icon-180.webp', '/ndx-dca/icon-192.webp'];

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    // 预缓存核心资源；单个失败不阻断安装
    await Promise.all(CORE.map(u => c.add(new Request(u, { cache: 'reload' })).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
    // 旧版本升级上来时，强制已打开页面换成新版（保留 v38 逻辑）
    const cls = await self.clients.matchAll({ includeUncontrolled: true, type: 'window' });
    cls.forEach(c => { try { c.navigate(c.url); } catch (_) { try { c.postMessage({ type: 'RELOAD' }); } catch (_) {} } });
  })());
});

self.addEventListener('message', e => {
  if (e.data && e.data.type === 'RELOAD') { try { self.skipWaiting(); } catch (_) {} }
});

/* 后台静默更新 HTML 缓存，并比对版本号 */
async function revalidateHTML(req) {
  try {
    // 注意：必须按「当前导航的实际 URL」重新取，不能用固定路径，
    // 否则深层路径 / 带查询参数的入口会 404（曾导致页面白屏）。
    const u = new URL(req.url);
    const target = u.origin + u.pathname;
    const net = await fetch(target, { cache: 'no-store' });
    if (!net || !net.ok) return;
    const txt = await net.clone().text();
    const newVer = (/<meta\s+name="x-app-ver"\s+content="([^"]+)"/.exec(txt) || [])[1] || '';
    const c = await caches.open(CACHE);
    const old = await c.match(req) || await c.match(HTML_FILE);
    let oldVer = '';
    if (old) {
      try { oldVer = (/<meta\s+name="x-app-ver"\s+content="([^"]+)"/.exec(await old.text()) || [])[1] || ''; } catch (_) {}
    }
    await c.put(req, net);
    if (newVer && oldVer && newVer !== oldVer) {
      const cls = await self.clients.matchAll({ type: 'window' });
      cls.forEach(cl => cl.postMessage({ type: 'NEW_VERSION', ver: newVer }));
    }
  } catch (_) {}
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // sw.js 自身：network-first，保证部署新版本时一定能更新
  if (url.pathname.endsWith('/sw.js')) {
    e.respondWith((async () => {
      try {
        const net = await fetch(req, { cache: 'no-store' });
        const c = await caches.open(CACHE);
        c.put(req, net.clone());
        return net;
      } catch (err) {
        return (await caches.match(req)) || new Response('', { status: 503 });
      }
    })());
    return;
  }

  // 导航请求：stale-while-revalidate —— 有缓存立刻用，后台更新
  if (req.mode === 'navigate' || url.pathname === HTML || url.pathname === '/ndx-dca') {
    e.respondWith((async () => {
      const c = await caches.open(CACHE);
      const cached = (await c.match(req)) || (await c.match(HTML_FILE));
      if (cached) {
        e.waitUntil(revalidateHTML(req));
        return cached;
      }
      // 首次访问无缓存：只能走网络（用当前位置的路径，兼容根路径部署）
      try {
        const net = await fetch(url.origin + url.pathname, { cache: 'no-store' });
        if (net && net.ok) await c.put(req, net.clone());
        return net;
      } catch (err) {
        return new Response('网络不可用，请联网后重试', {
          status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' }
        });
      }
    })());
    return;
  }

  // 其它同源静态资源：cache-first + 后台更新
  if (url.origin === self.location.origin) {
    e.respondWith((async () => {
      const c = await caches.open(CACHE);
      const hit = await c.match(req);
      if (hit) {
        e.waitUntil(fetch(req).then(r => { if (r && r.ok) c.put(req, r.clone()); }).catch(() => {}));
        return hit;
      }
      try {
        const net = await fetch(req);
        if (net && net.ok) c.put(req, net.clone());
        return net;
      } catch (err) {
        return new Response('', { status: 404 });
      }
    })());
    return;
  }
});
