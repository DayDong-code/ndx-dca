# -*- coding: utf-8 -*-
"""部署纳指100定投工作台到 GitHub Pages。

关键修正：GitHub Contents API 更新【已存在】文件时必须在 PUT 里带上该文件的
当前 sha，否则会静默返回 422（内容未更新）。本脚本先 GET 当前 sha，再带 sha 推送。
"""
import json, base64, ssl, socket, http.client, os, re

# Token 取自环境变量 GH_PAT（GitHub Action 用 secret 注入），本地部署时也用环境变量注入。
# 注意：本文件会被同步到公开仓库，绝不能在此硬编码真实 token。
TOKEN = os.environ.get("GH_PAT")
if not TOKEN:
    raise SystemExit("ERROR: 缺少环境变量 GH_PAT（ghp_ 开头的 Personal Access Token）")
ART = os.path.dirname(os.path.abspath(__file__)) + '/'
HOST = "api.github.com"
# 默认走硬编码 IP（绕过沙箱 DNS）；GitHub Actions 上置 GH_API_IP="" 改用域名解析
IP = os.environ.get("GH_API_IP", "140.82.121.6")
REPO = "DayDong-code/ndx-dca"

ctx = ssl.create_default_context()

class RConn(http.client.HTTPSConnection):
    def connect(self):
        if IP:
            sock = socket.create_connection((IP, 443), 15)
            self.sock = ctx.wrap_socket(sock, server_hostname=HOST)
        else:
            self.sock = ctx.wrap_socket(socket.create_connection((HOST, 443), 15),
                                       server_hostname=HOST)

def call(method, path, body=None, debug=False):
    c = RConn(HOST, 443, timeout=30)
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Host": HOST,
        "Authorization": f"Bearer {TOKEN}",
        "User-Agent": "ndx-deploy",
        "Accept": "application/vnd.github+json",
    }
    if data:
        headers["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=headers)
    r = c.getresponse()
    raw = r.read().decode()
    c.close()
    if debug:
        print("RAW:", raw[:400])
    try:
        j = json.loads(raw)
    except Exception:
        j = raw
    return r.status, j

def get_sha(path):
    st, j = call("GET", f"/repos/{REPO}/contents/{path}")
    if st == 200 and isinstance(j, dict) and "sha" in j:
        return j["sha"]
    return None  # 文件不存在（首次创建）

def upsert(path, content_bytes, message):
    b64 = base64.b64encode(content_bytes).decode()
    sha = get_sha(path)
    body = {"message": message, "content": b64}
    if sha:
        body["sha"] = sha  # 已存在必须带 sha
    st, j = call("PUT", f"/repos/{REPO}/contents/{path}", body, debug=True)
    ok = st in (200, 201) and isinstance(j, dict)
    print(f"  {path}: HTTP {st}  new_sha={j.get('content',{}).get('sha') if ok else j}")
    return ok

# 0. 自动升 SW 版本：每次部署都让 PWA 拉取新 Service Worker 并强制刷新页面，
#    彻底避免"部署了新版本但浏览器一直停在旧缓存"的问题（iOS 添加到主屏幕尤其明显）。
def bump_sw_version():
    swp = ART + "sw.js"
    if not os.path.exists(swp):
        print("! 未找到 sw.js，跳过 SW 自动升版"); return
    sw = open(swp, "r", encoding="utf-8").read()
    m = re.search(r"CACHE\s*=\s*'ndx-dca-v(\d+)'", sw)
    if not m:
        print("! 未在 sw.js 找到 CACHE 版本，跳过 SW 自动升版"); return
    n = int(m.group(1)); n2 = n + 1
    sw2 = re.sub(r"CACHE\s*=\s*'ndx-dca-v\d+'", "CACHE = 'ndx-dca-v%d'" % n2, sw)
    sw2 = re.sub(r"Service Worker\s+v\d+", "Service Worker  v%d" % n2, sw2)
    open(swp, "w", encoding="utf-8").write(sw2)
    # 同步改注册 query（sw.js?v=N）到所有 HTML 源码/产物
    for fp in [ART + "template.html", ART + "index.html", "/workspace/ndx-dca.html", ART + "pipeline/template.html"]:
        if not os.path.exists(fp):
            continue
        t = open(fp, "r", encoding="utf-8").read()
        t2 = re.sub(r"sw\.js\?v=\d+", "sw.js?v=%d" % n2, t)
        if t2 != t:
            open(fp, "w", encoding="utf-8").write(t2)
    print("SW 版本自动升版 v%d -> v%d（强制 PWA 拉最新页面）" % (n, n2))

bump_sw_version()

# 0.5 把 App 版本号写成"当天日期"，让手动与每日自动刷新都反映数据/部署新鲜度，
# 避免版本号停在一个旧功能版本号（如 21ar）却已含最新数据造成的误导。
def bump_appver_date():
    import datetime
    today = datetime.date.today().strftime("%Y.%m.%d")
    for fp in [ART + "template.html", ART + "index.html", "/workspace/ndx-dca.html"]:
        if not os.path.exists(fp):
            continue
        t = open(fp, "r", encoding="utf-8").read()
        t2 = re.sub(r'x-app-ver"\s*content="[^"]*"', 'x-app-ver" content="%s"' % today, t)
        if t2 != t:
            open(fp, "w", encoding="utf-8").write(t2)
    print("App 版本号更新为当天日期:", today)
bump_appver_date()

# 1. 上传 index.html（由 assemble.py 生成在 ART 目录）
html = open(ART + "index.html", "rb").read()
print("上传 index.html (%d bytes) ..." % len(html))
upsert("index.html", html, "deploy: 纳指100定投工作台 PWA (带 sha 更新)")

# 2. 上传 .nojekyll（若不存在则不传 sha）
print("上传 .nojekyll ...")
upsert(".nojekyll", b"", "add .nojekyll")

# 2.5 上传 Service Worker（让 PWA 自动更新，无需删了重装图标）
sw = open(ART + "sw.js", "rb").read()
print("上传 sw.js (%d bytes) ..." % len(sw))
upsert("sw.js", sw, "deploy: 添加 Service Worker 实现 PWA 自动更新")

# 2.6 同步构建脚本（含"用 dateTime 定日期"修复），避免仓库里的 Action 用旧版 build_snapshot.py 重新生成数据时把周一错算成周日
bs = open(ART + "build_snapshot.py", "rb").read()
print("上传 build_snapshot.py (%d bytes) ..." % len(bs))
upsert("build_snapshot.py", bs, "deploy: 同步构建脚本（日历日期修复）")

# 2.7 同步全部构建源到仓库根，使 GitHub Action 每日自动刷新时能完整复现构建环境
# 注意：daily.yml（每日自动刷新 workflow）不在此处上传——GitHub Contents API 不支持
#       创建 .github 目录下的文件，需通过 git 提交（见 daily.yml 说明），否则会返回 404。
SRC = ["template.html", "assemble.py", "gh_deploy2.py", "build_snapshot.py", "ndx_5y.json", "sw.js"]
for f in SRC:
    p = ART + f
    if os.path.exists(p):
        upsert(f, open(p, "rb").read(), "sync build source: " + f)

# 注意：不要把构建管线源码(pipeline/)上传到 Pages 仓库根目录！
# 该目录会导致 GitHub Pages 构建瞬间失败(errored, duration 0)，
# 使后续所有部署都无法上线（CDN 停在最后一次成功构建）。运行时不依赖它。

# 3. 确保 Pages 已开启（已开启会返回 409，可忽略）
st3, j3 = call("POST", f"/repos/{REPO}/pages", {"source": {"branch": "main", "path": "/"}})
print("Pages:", st3, (j3.get("html_url") if isinstance(j3, dict) else j3))

print("\n完成。链接：https://daydong-code.github.io/ndx-dca/")
