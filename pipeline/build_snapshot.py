# -*- coding: utf-8 -*-
"""构建纳指100定投工作台数据快照：5年历史 + 实时行情 + 指标计算 + 新闻"""
import json, re, subprocess, datetime, statistics, os

ART = os.path.dirname(os.path.abspath(__file__)) + '/'

# ---------- 1. 加载5年历史 ----------
hist = json.load(open(ART + 'ndx_5y.json'))['data']['chart']
days, closes = [], []
for bar in hist:
    dt = datetime.datetime.fromtimestamp(bar['x'] / 1000, datetime.timezone.utc)
    if dt.weekday() >= 5:
        continue  # 过滤异常周末点
    price = float(bar['y'])
    # 数据时间戳落在美东交易日的 UTC 次日 00:00–04:00，统一减 4 小时即得真实美东交易日。
    # 全量 1267 根 K 线验证：UTC 日期 − 美东(−4h)日期 恒为 1 天，故固定 −4h 即可，无需 DST 判断。
    et = dt + datetime.timedelta(hours=-4)
    days.append(int((et.date() - datetime.date(1970, 1, 1)).days))
    closes.append(round(price, 2))
# 去重（同一天只留最后一个）
seen = {}
for d, c in zip(days, closes):
    seen[d] = c
days = sorted(seen.keys())
closes = [seen[d] for d in days]
print('bars after clean:', len(days), 'range:', datetime.date.fromordinal(datetime.date(1970,1,1).toordinal()+days[0]), '->', datetime.date.fromordinal(datetime.date(1970,1,1).toordinal()+days[-1]))

# ---------- 2. 腾讯实时行情（失败则回退到上一次快照的末端，保证脚本不崩、Action 仍可提交） ----------
tx = None
try:
    raw = subprocess.run(['curl', '-s', '--max-time', '20', 'https://qt.gtimg.cn/q=usNDX'],
                         capture_output=True).stdout.decode('gbk', 'ignore')
    f = raw.split('"')[1].split('~')
    tx = {
        'p': float(f[3]), 'pc': float(f[4]), 'o': float(f[5]), 'vol': f[6],
        'timeET': f[30], 'ch': float(f[31]), 'chp': float(f[32]),
        'h': float(f[33]), 'l': float(f[34]),
        'wk52h': float(f[48]) if f[48] else None, 'wk52l': float(f[49]) if f[49] else None,
    }
    dET = tx['timeET'][:10]  # 美东日期 YYYY-MM-DD
    print('tencent quote:', tx['p'], tx['chp'], '%', tx['timeET'])

    # 把实时价并入历史：当日bar替换或追加
    def et_date_to_day(s):
        y, m, d = map(int, s.split('-'))
        return (datetime.date(y, m, d) - datetime.date(1970, 1, 1)).days
    cur_day = et_date_to_day(dET)
    if cur_day == days[-1]:
        closes[-1] = round(tx['p'], 2)
    elif cur_day > days[-1]:
        days.append(cur_day)
        closes.append(round(tx['p'], 2))
except Exception as e:
    print('tencent quote failed, reuse prev snap last bar:', e)
    try:
        prev = json.load(open(ART + 'snap.json'))
        days[-1] = prev['days'][-1]; closes[-1] = prev['closes'][-1]; tx = prev.get('quote') or {}
    except Exception as e2:
        print('prev snap fallback failed:', e2); tx = {'p': closes[-1], 'chp': 0, 'timeET': ''}
print('last bar:', datetime.date.fromordinal(datetime.date(1970,1,1).toordinal()+days[-1]), closes[-1])

# ---------- 3. 指标计算（与页面JS完全一致的逻辑） ----------
def rsi_wilder(cs, period=14):
    if len(cs) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(cs)):
        diff = cs[i] - cs[i-1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - 100 / (1 + rs)

def to_dates(days):
    return [datetime.date.fromordinal(datetime.date(1970,1,1).toordinal() + d) for d in days]

dates = to_dates(days)
cur = closes[-1]

# 3.1 价格分位（5年收盘价 <= 当前价 的比例）
below = sum(1 for c in closes if c <= cur)
pct = below / len(closes)
s1 = round((1 - pct) * 100, 1)

# 3.2 日/周/月 RSI
rsi_d = rsi_wilder(closes, 14)
weekly, monthly, wcur, mcur = [], [], None, None
last_w, last_m = None, None
for dt, c in zip(dates, closes):
    wk = dt.isocalendar()[:2]
    mo = (dt.year, dt.month)
    if wk != last_w:
        weekly.append(c); last_w = wk
    else:
        weekly[-1] = c
    if mo != last_m:
        monthly.append(c); last_m = mo
    else:
        monthly[-1] = c
rsi_w = rsi_wilder(weekly, 14)
rsi_m = rsi_wilder(monthly, 14)
avg_rsi = (rsi_d + rsi_w + rsi_m) / 3
s2 = round(100 - avg_rsi, 1)

# 3.3 MA200 偏离
ma200 = sum(closes[-200:]) / 200
dev = (cur - ma200) / ma200
s3 = round(max(0, min(100, 50 - dev * 250)), 1)

# 3.4 阶段回撤（5年高点）
peak = max(closes)
dd = (cur - peak) / peak
s4 = round(max(0, min(100, abs(dd) / 0.35 * 100)), 1)

# 3.5 本月价格位置 + 本月第几便宜
cur_month = (dates[-1].year, dates[-1].month)
mc = [c for dt, c in zip(dates, closes) if (dt.year, dt.month) == cur_month]
m_lo, m_hi = min(mc), max(mc)
pos = (cur - m_lo) / (m_hi - m_lo) if m_hi > m_lo else 0.5
s5 = round((1 - pos) * 100, 1)
rank = sorted(mc).index(cur) + 1  # 1=最便宜

total = round(0.3*s1 + 0.2*s2 + 0.2*s3 + 0.2*s4 + 0.1*s5, 1)
indicators = {
    'cur': cur, 'pct5y': round(pct*100, 1), 's1': s1,
    'rsiD': round(rsi_d, 1), 'rsiW': round(rsi_w, 1), 'rsiM': round(rsi_m, 1), 's2': s2,
    'ma200': round(ma200, 1), 'dev': round(dev*100, 2), 's3': s3,
    'peak': peak, 'dd': round(dd*100, 2), 's4': s4,
    'monthLow': m_lo, 'monthHigh': m_hi, 'monthPos': round(pos*100, 1),
    'monthRank': rank, 'monthDays': len(mc), 's5': s5, 'total': total,
}
print(json.dumps(indicators, ensure_ascii=False, indent=1))

# ---------- 4. 新闻快照（失败则沿用上次快照） ----------
news = {'jin10': [], 'sina': []}
try:
    # 金十
    j = subprocess.run(['curl', '-s', '--max-time', '15',
                        f'https://www.jin10.com/flash_newest.js?t={int(datetime.datetime.now().timestamp())}',
                        '-H', 'User-Agent: Mozilla/5.0', '-H', 'Referer: https://www.jin10.com/'],
                       capture_output=True).stdout.decode('utf-8', 'ignore')
    m = re.search(r'var newest = (\[.*\])\s*;?\s*$', j, re.S)
    jin10 = []
    if m:
        for it in json.loads(m.group(1)):
            d = it.get('data') or {}
            content = (d.get('content') or '').strip()
            tm = (it.get('time') or '')[:16]
            mt = re.match(r'【(.+?)】', content)
            title = mt.group(1) if mt else (d.get('title') or content[:36])
            body = re.sub(r'^【.*?】(金十数据\S*讯，?)?', '', content)[:80]
            if title and tm:
                jin10.append({'t': title, 'c': body, 'tm': tm, 'id': it.get('id', '')})
    jin10 = jin10[:20]
    # 新浪
    s = subprocess.run(['curl', '-s', '--max-time', '15',
                        'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=20&page=1',
                        '-H', 'User-Agent: Mozilla/5.0'], capture_output=True).stdout.decode('utf-8', 'ignore')
    sina = []
    try:
        for it in json.loads(s)['result']['data']:
            title = it.get('title') or it.get('intro') or ''
            url = it.get('url') or ''
            tm = datetime.datetime.fromtimestamp(int(it.get('ctime', 0))).strftime('%m-%d %H:%M')
            src = it.get('media_name') or '新浪财经'
            if title and url:
                sina.append({'t': title, 'tm': tm, 'src': src, 'u': url})
    except Exception as e:
        print('sina parse err', e)
    sina = sina[:20]
    news = {'jin10': jin10, 'sina': sina}
    print('news: jin10', len(jin10), 'sina', len(sina))
    print('jin10[0]:', jin10[0] if jin10 else None)
    print('sina[0]:', sina[0] if sina else None)
except Exception as e:
    print('news fetch failed, reuse prev:', e)
    try:
        news = json.load(open(ART + 'snap.json')).get('news', {'jin10': [], 'sina': []})
    except Exception:
        news = {'jin10': [], 'sina': []}

# ---------- 5. 输出快照 ----------
now = datetime.datetime.now()
snap = {
    'v': 1,
    'builtAt': now.strftime('%Y-%m-%d %H:%M'),
    'days': days,
    'closes': closes,
    'quote': tx,
    'ind': indicators,
    'news': news,
}
json.dump(snap, open(ART + 'snap.json', 'w'), ensure_ascii=False, separators=(',', ':'))
print('snap.json size KB:', len(open(ART + 'snap.json').read()) // 1024)
