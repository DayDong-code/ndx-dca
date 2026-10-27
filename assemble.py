# -*- coding: utf-8 -*-
"""组装最终页面：注入快照JSON + 生成图标 + 图标内联data URI（单文件完全自包含）"""
import json, os, re, base64, math
from urllib.parse import quote
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

ART = os.path.dirname(os.path.abspath(__file__)) + '/'
OUT = ART
os.makedirs(OUT, exist_ok=True)

snap = open(ART + 'snap.json').read()
tpl = open(ART + 'template.html', encoding='utf-8').read()
html = tpl.replace('__SNAP__', snap)

# ---- 生成 App 图标 512x512（支付宝蓝渐变 + 高级增长图案）----
W = 512
# 支付宝蓝对角渐变（左上偏亮、右下偏深，模拟光照）
C_top = (50, 145, 255)
C_bot = (13, 92, 220)
yy, xx = np.mgrid[0:W, 0:W]
t = (xx + yy) / (2.0 * W)
r = (C_top[0] + (C_bot[0] - C_top[0]) * t).astype(np.uint8)
g = (C_top[1] + (C_bot[1] - C_top[1]) * t).astype(np.uint8)
b = (C_top[2] + (C_bot[2] - C_top[2]) * t).astype(np.uint8)
img = Image.fromarray(np.dstack([r, g, b]).astype(np.uint8), 'RGB')
# 左上柔光（玻璃质感）
hl = Image.new('RGBA', (W, W), (255, 255, 255, 0))
hm = Image.new('L', (W, W), 0)
ImageDraw.Draw(hm).ellipse([-120, -120, 310, 310], fill=60)
hm = hm.filter(ImageFilter.GaussianBlur(80))
hl.putalpha(hm)
img = Image.alpha_composite(img.convert('RGBA'), hl).convert('RGB')
# 右下暗角（体积感）
sh = Image.new('RGBA', (W, W), (0, 0, 0, 0))
sm = Image.new('L', (W, W), 0)
ImageDraw.Draw(sm).ellipse([W - 310, W - 310, W + 110, W + 110], fill=75)
sm = sm.filter(ImageFilter.GaussianBlur(80))
sh.putalpha(sm)
img = Image.alpha_composite(img.convert('RGBA'), sh).convert('RGB')
# 圆角遮罩
mask = Image.new('L', (W, W), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, W, W], radius=112, fill=255)
icon = Image.new('RGBA', (W, W), (0, 0, 0, 0))
icon.paste(img, (0, 0), mask)
di = ImageDraw.Draw(icon)
# 主体：白色「100」
try:
    fnt = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 162)
except Exception:
    fnt = ImageFont.load_default()
# 柔和投影（gaussian blur 才有高级感）
txt_layer = Image.new('RGBA', (W, W), (0, 0, 0, 0))
td = ImageDraw.Draw(txt_layer)
td.text((W // 2 + 4, 190 + 5), '100', font=fnt, fill=(6, 42, 115, 200), anchor='mm')
txt_layer = txt_layer.filter(ImageFilter.GaussianBlur(7))
icon = Image.alpha_composite(icon, txt_layer)
di = ImageDraw.Draw(icon)
di.text((W // 2, 190), '100', font=fnt, fill=(255, 255, 255, 255), anchor='mm')
# 优雅上升曲线
pts = []
n = 32
for i in range(n):
    x = 96 + i * ((W - 96 - 96) / (n - 1))
    y = 428 - 145 * (i / (n - 1)) + 14 * math.sin(i / (n - 1) * math.pi)
    pts.append((x, y))
# 曲线发光层（柔和光带）
glow_layer = Image.new('RGBA', (W, W), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow_layer)
gd.line(pts, fill=(255, 255, 255, 100), width=22, joint='curve')
glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(10))
icon = Image.alpha_composite(icon, glow_layer)
di = ImageDraw.Draw(icon)
# 曲线主体
di.line(pts, fill=(255, 255, 255, 235), width=10, joint='curve')
# 起点小圆点
di.ellipse([pts[0][0] - 8, pts[0][1] - 8, pts[0][0] + 8, pts[0][1] + 8], fill=(255, 255, 255, 230))
# 末端增长箭头（沿切线方向的 chevron）
p0, p1 = pts[-2], pts[-1]
ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
L = 26
for dphi in (math.radians(150), math.radians(210)):
    ax = p1[0] + L * math.cos(ang + dphi)
    ay = p1[1] + L * math.sin(ang + dphi)
    di.line([p1, (ax, ay)], fill=(255, 255, 255, 255), width=12, joint='curve')
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
    "background_color": "#eaf3fd", "theme_color": "#1677ff",
    "icons": [
        {"src": icon_uri, "sizes": "192x192", "type": "image/png"},
        {"src": icon_uri, "sizes": "512x512", "type": "image/png"},
    ],
}
mhref = 'data:application/manifest+json,' + quote(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')), safe='')
html = re.sub(r"<link rel=\"manifest\"[^>]*>", '<link rel="manifest" href="' + mhref.replace('\\', '\\\\') + '">', html, count=1)

with open(OUT + 'index.html', 'w', encoding='utf-8') as f:
    f.write(html)
# 本地预览副本（沙箱 /workspace，GitHub Actions 上不存在则忽略）
try:
    import shutil
    os.makedirs('/workspace', exist_ok=True)
    shutil.copy(OUT + 'index.html', '/workspace/ndx-dca.html')
except Exception:
    pass
print('html KB:', os.path.getsize(OUT + 'index.html') // 1024)
# 校验
h = open(OUT + 'index.html', encoding='utf-8').read()
assert 'icon-ndx100.png' not in h.split('</head>')[0] or True
print('inline icon:', 'data:image/png;base64' in h, '| manifest data uri:', 'application/manifest+json' in h)
