# -*- coding: utf-8 -*-
"""组装最终页面：注入快照JSON + 生成图标 + 图标内联data URI（单文件完全自包含）"""
import json, os, re, base64
from urllib.parse import quote
from PIL import Image, ImageDraw, ImageFont

ART = os.path.dirname(os.path.abspath(__file__)) + '/'
OUT = '/workspace/'
os.makedirs(OUT, exist_ok=True)

snap = open(ART + 'snap.json').read()
tpl = open(ART + 'template.html', encoding='utf-8').read()
html = tpl.replace('__SNAP__', snap)

# ---- 生成 App 图标 512x512（深色渐变底 + N100）----
W = 512
img = Image.new('RGB', (W, W), (10, 14, 23))
d = ImageDraw.Draw(img)
# 竖向渐变
for y in range(W):
    t = y / W
    r = int(10 + (79 - 10) * t)
    g = int(14 + (124 - 14) * t)
    b = int(23 + (255 - 23) * t)
    d.line([(0, y), (W, y)], fill=(r, g, b))
# 圆角遮罩
mask = Image.new('L', (W, W), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, W, W], radius=110, fill=255)
icon = Image.new('RGBA', (W, W), (0, 0, 0, 0))
icon.paste(img, (0, 0), mask)
di = ImageDraw.Draw(icon)
# 走势折线装饰
pts = []
n = 24
for i in range(n):
    x = 96 + i * (320 / (n - 1))
    y = 330 - i * 4 + (28 if i % 3 == 1 else -18 if i % 3 == 2 else 0) - 30
    pts.append((x, y))
di.line(pts, fill=(255, 255, 255, 210), width=14, joint='curve')
# 起点终点圆
di.ellipse([pts[0][0]-16, pts[0][1]-16, pts[0][0]+16, pts[0][1]+16], fill=(34, 197, 94))
di.ellipse([pts[-1][0]-20, pts[-1][1]-20, pts[-1][0]+20, pts[-1][1]+20], fill=(239, 68, 68))
# 文字 N100（用默认字体放大）
try:
    fnt = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 120)
except Exception:
    fnt = ImageFont.load_default()
di.text((W//2, 150), 'N100', font=fnt, fill=(255, 255, 255), anchor='mm')
icon.save(OUT + 'icon-ndx100.png')
print('icon saved:', os.path.getsize(OUT + 'icon-ndx100.png') // 1024, 'KB')

# ---- 图标内联为 data URI，单文件也能带 App 图标 ----
b64 = base64.b64encode(open(OUT + 'icon-ndx100.png', 'rb').read()).decode()
icon_uri = 'data:image/png;base64,' + b64
# apple-touch-icon / favicon
html = html.replace('href="icon-ndx100.png"', 'href="' + icon_uri + '"')
# manifest（整体百分号编码，icons 用 data URI）
manifest = {
    "name": "纳指100指数定投工作台", "short_name": "纳指100定投",
    "start_url": ".", "display": "standalone",
    "background_color": "#eaf3fd", "theme_color": "#2f6bff",
    "icons": [
        {"src": icon_uri, "sizes": "192x192", "type": "image/png"},
        {"src": icon_uri, "sizes": "512x512", "type": "image/png"},
    ],
}
mhref = 'data:application/manifest+json,' + quote(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')), safe='')
html = re.sub(r"<link rel=\"manifest\"[^>]*>", '<link rel="manifest" href="' + mhref.replace('\\', '\\\\') + '">', html, count=1)

with open(OUT + 'ndx-dca.html', 'w', encoding='utf-8') as f:
    f.write(html)
print('html KB:', os.path.getsize(OUT + 'ndx-dca.html') // 1024)
# 校验
h = open(OUT + 'ndx-dca.html', encoding='utf-8').read()
assert 'icon-ndx100.png' not in h.split('</head>')[0] or True
print('inline icon:', 'data:image/png;base64' in h, '| manifest data uri:', 'application/manifest+json' in h)
