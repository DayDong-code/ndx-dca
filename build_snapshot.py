# -*- coding: utf-8 -*-
"""构建多指数定投工作台数据快照：纳指100(NDX) + 标普500(SPX)
   5年历史 + 实时行情 + 指标计算 + 新闻

快照结构（v2）：
{
  v: 2, builtAt, news,
  idx: {
    ndx: {days, closes, quote, ind, ddScale, ...},
    spx: {days, closes, quote, ind, ddScale, ...}
  }
}
"""
import json, re, subprocess, datetime, statistics, os

ART = os.path.dirname(os.path.abspath(__file__)) + '/'

# ================= 指数配置 =================
# ddScale: s4 回撤评分的「满分回撤幅度」。取各自近5年真实最大回撤，
#          使两个指数的「深度回调」口径可比（ndx 35.56%，spx 25.43%，实测所得）
IDX_CFG = {
    'ndx': {
        'name': '纳斯达克100',
        'short': '纳指100',
        'nasdaq_sym': 'NDX',        # 纳斯达克官方 chart 接口
        'tencent_sym': 'usNDX',     # 腾讯实时行情
        'sina_sym': '.NDX',         # 新浪美股日K（备用）
        'ddScale': 0.3556,
        'fallback': 'ndx_5y.json',
    },
    'spx': {
        'name': '标普500',
        'short': '标普500',
        'nasdaq_sym': None,         # 纳斯达克接口不支持 .INX，只能用新浪
        'tencent_sym': 'us.INX',
        'sina_sym': '.INX',
        'ddScale': 0.2543,
        'fallback': None,
    },
}


# ---------- 1. 历史日线 ----------
def _bars_from_nasdaq(sym):
    """纳斯达克官方 chart 接口：dateTime 字段(M/D/YYYY)即美东交易日"""
    today = datetime.date.today()
    url = ('https://api.nasdaq.com/api/quote/%s/chart?assetclass=index'
           '&fromdate=2021-08-01&todate=%s' % (sym, today.strftime('%Y-%m-%d')))
    raw = subprocess.run(['curl', '-s', '--max-time', '40', url,
                          '-H', 'User-Agent: Mozilla/5.0',
                          '-H', 'Accept: application/json'],
                         capture_output=True).stdout.decode('utf-8', 'ignore')
    j = json.loads(raw)
    ch = j['data']['chart']
    if not ch:
        raise RuntimeError('nasdaq empty chart')
    out = []
    for bar in ch:
        try:
            m, d, y = map(int, bar['z']['dateTime'].split('/'))
        except Exception:
            continue
        out.append((datetime.date(y, m, d), float(bar['y'])))
    print('  nasdaq live chart bars:', len(out), '| timeAsOf', j['data'].get('timeAsOf'))
    return out


def _bars_from_sina(sym):
    """新浪美股日K：返回自 2004 年起的全部日线，字段 d(日期) / c(收盘)"""
    # 注意：不能用 % 格式化拼 URL——路径里的 %20 会被当成格式符
    url = ('https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20x=/'
           'US_MinKService.getDailyK?symbol=' + sym + '&___qn=3')
    t = subprocess.run(['curl', '-s', '--max-time', '40', url,
                        '-H', 'Referer: https://finance.sina.com.cn',
                        '-H', 'User-Agent: Mozilla/5.0'],
                       capture_output=True).stdout.decode('utf-8', 'ignore')
    m = re.search(r'var x=\((\[.*\])\)', t, re.S)
    if not m:
        raise RuntimeError('sina parse failed')
    arr = json.loads(m.group(1))
    out = []
    for a in arr:
        try:
            d = datetime.date.fromisoformat(a['d'])
            c = float(a['c'])
        except Exception:
            continue
        if c > 0:
            out.append((d, c))
    print('  sina daily bars:', len(out))
    return out


def load_hist(key):
    """按优先级抓取历史：纳斯达克(若有) -> 新浪 -> 本地静态文件"""
    cfg = IDX_CFG[key]
    cutoff = datetime.date(2021, 8, 1)
    attempts = []
    if cfg['nasdaq_sym']:
        attempts.append(('nasdaq', lambda: _bars_from_nasdaq(cfg['nasdaq_sym'])))
    attempts.append(('sina', lambda: _bars_from_sina(cfg['sina_sym'])))
    for src, fn in attempts:
        try:
            bars = fn()
            bars = [(d, c) for d, c in bars if d >= cutoff]
            if len(bars) > 200:
                print('  [%s] 使用数据源: %s, bars=%d' % (key, src, len(bars)))
                return bars
            print('  [%s] %s 数据过少(%d)，尝试下一个源' % (key, src, len(bars)))
        except Exception as e:
            print('  [%s] %s 抓取失败: %s' % (key, src, e))
    # 回退本地静态文件
    fb = cfg.get('fallback')
    if fb and os.path.exists(ART + fb):
        ch = json.load(open(ART + fb))['data']['chart']
        out = []
        for bar in ch:
            try:
                m, d, y = map(int, bar['z']['dateTime'].split('/'))
            except Exception:
                continue
            out.append((datetime.date(y, m, d), float(bar['y'])))
        print('  [%s] 回退本地静态文件 %s, bars=%d' % (key, fb, len(out)))
        return out
    raise RuntimeError('no data source for ' + key)


def clean_bars(bars):
    """按日期去重排序，跳过周末异常点"""
    seen = {}
    for d, c in bars:
        if d.weekday() >= 5:
            continue
        seen[d] = round(float(c), 2)
    ds = sorted(seen.keys())
    return ds, [seen[d] for d in ds]


# ---------- 2. 实时行情（腾讯） ----------
def fetch_quote(tex_sym):
    raw = subprocess.run(['curl', '-s', '--max-time', '20',
                          'https://qt.gtimg.cn/q=' + tex_sym],
                         capture_output=True).stdout.decode('gbk', 'ignore')
    f = raw.split('"')[1].split('~')
    return {
        'p': float(f[3]), 'pc': float(f[4]), 'o': float(f[5]), 'vol': f[6],
        'timeET': f[30], 'ch': float(f[31]), 'chp': float(f[32]),
        'h': float(f[33]), 'l': float(f[34]),
        'wk52h': float(f[48]) if len(f) > 48 and f[48] else None,
        'wk52l': float(f[49]) if len(f) > 49 and f[49] else None,
    }


def et_date_to_day(s):
    y, m, d = map(int, s.split('-'))
    return (datetime.date(y, m, d) - datetime.date(1970, 1, 1)).days


# ---------- 3. 指标计算（与页面 JS 完全一致） ----------
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


def calc_indicators(days, closes, dd_scale):
    dates = [datetime.date.fromordinal(datetime.date(1970, 1, 1).toordinal() + d) for d in days]
    cur = closes[-1]

    # 3.1 价格分位（5年收盘价 <= 当前价 的比例）
    below = sum(1 for c in closes if c <= cur)
    pct = below / len(closes)
    s1 = round((1 - pct) * 100, 1)

    # 3.2 日/周/月 RSI
    rsi_d = rsi_wilder(closes, 14)
    weekly, monthly = [], []
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

    # 3.4 阶段回撤（5年高点）——分母按各指数真实最大回撤校准
    peak = max(closes)
    dd = (cur - peak) / peak
    s4 = round(max(0, min(100, abs(dd) / dd_scale * 100)), 1)

    # 3.5 本月价格位置 + 本月第几便宜
    cur_month = (dates[-1].year, dates[-1].month)
    mc = [c for dt, c in zip(dates, closes) if (dt.year, dt.month) == cur_month]
    m_lo, m_hi = min(mc), max(mc)
    pos = (cur - m_lo) / (m_hi - m_lo) if m_hi > m_lo else 0.5
    s5 = round((1 - pos) * 100, 1)
    rank = sorted(mc).index(cur) + 1  # 1=最便宜

    total = round(0.3*s1 + 0.2*s2 + 0.2*s3 + 0.2*s4 + 0.1*s5, 1)
    return {
        'cur': cur, 'pct5y': round(pct*100, 1), 's1': s1,
        'rsiD': round(rsi_d, 1), 'rsiW': round(rsi_w, 1), 'rsiM': round(rsi_m, 1), 's2': s2,
        'ma200': round(ma200, 1), 'dev': round(dev*100, 2), 's3': s3,
        'peak': peak, 'dd': round(dd*100, 2), 's4': s4,
        'monthLow': m_lo, 'monthHigh': m_hi, 'monthPos': round(pos*100, 1),
        'monthRank': rank, 'monthDays': len(mc), 's5': s5, 'total': total,
    }


# ---------- 4. 构建单个指数 ----------
def build_index(key, prev_snap):
    cfg = IDX_CFG[key]
    print('\n===== 构建 %s (%s) =====' % (key, cfg['name']))

    bars = load_hist(key)
    days_dt, closes = clean_bars(bars)
    days = [(d - datetime.date(1970, 1, 1)).days for d in days_dt]
    print('  bars after clean:', len(days), 'range:', days_dt[0], '->', days_dt[-1])

    # 实时行情并入历史
    tx = None
    try:
        tx = fetch_quote(cfg['tencent_sym'])
        print('  tencent quote:', tx['p'], tx['chp'], '%', tx['timeET'])
        cur_day = et_date_to_day(tx['timeET'][:10])
        if cur_day == days[-1]:
            closes[-1] = round(tx['p'], 2)
        elif cur_day > days[-1]:
            days.append(cur_day)
            closes.append(round(tx['p'], 2))
    except Exception as e:
        print('  tencent quote failed:', e)
        prev_idx = (prev_snap.get('idx') or {}).get(key) or {}
        if prev_idx.get('days'):
            days[-1] = prev_idx['days'][-1]
            closes[-1] = prev_idx['closes'][-1]
            tx = prev_idx.get('quote') or {}
            print('  回退上次快照末端')
        else:
            tx = {'p': closes[-1], 'pc': closes[-1], 'o': closes[-1], 'vol': '0',
                  'timeET': '', 'ch': 0, 'chp': 0, 'h': closes[-1], 'l': closes[-1],
                  'wk52h': None, 'wk52l': None}
    print('  last bar:', datetime.date.fromordinal(datetime.date(1970,1,1).toordinal()+days[-1]), closes[-1])

    ind = calc_indicators(days, closes, cfg['ddScale'])
    print('  评分: %.1f (s1=%.1f s2=%.1f s3=%.1f s4=%.1f s5=%.1f) 当前回撤 %.2f%% / 满分阈值 %.2f%%'
          % (ind['total'], ind['s1'], ind['s2'], ind['s3'], ind['s4'], ind['s5'],
             ind['dd'], -cfg['ddScale']*100))

    return {
        'days': days, 'closes': closes, 'quote': tx, 'ind': ind,
        'ddScale': cfg['ddScale'], 'name': cfg['name'], 'short': cfg['short'],
    }


# ---------- 5. 新闻快照（失败则沿用上次） ----------
def build_news(prev_snap):
    try:
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
            print('sina news parse err', e)
        sina = sina[:20]
        print('news: jin10', len(jin10), 'sina', len(sina))
        return {'jin10': jin10, 'sina': sina}
    except Exception as e:
        print('news fetch failed, reuse prev:', e)
        return prev_snap.get('news') or {'jin10': [], 'sina': []}


# ================= 主流程 =================
def main():
    prev_snap = {}
    try:
        prev_snap = json.load(open(ART + 'snap.json'))
    except Exception:
        pass

    idx = {}
    for key in IDX_CFG:
        try:
            idx[key] = build_index(key, prev_snap)
        except Exception as e:
            print('  !! %s 构建失败: %s' % (key, e))
            prev_idx = (prev_snap.get('idx') or {}).get(key)
            if prev_idx:
                idx[key] = prev_idx
                print('  %s 沿用上次快照数据' % key)

    news = build_news(prev_snap)

    now = datetime.datetime.now()
    snap = {
        'v': 2,
        'builtAt': now.strftime('%Y-%m-%d %H:%M'),
        'news': news,
        'idx': idx,
    }
    json.dump(snap, open(ART + 'snap.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    print('\nsnap.json size KB:', len(open(ART + 'snap.json').read()) // 1024)
    for k, v in idx.items():
        print('  %s: bars=%d 末值=%s 评分=%s' % (k, len(v['days']), v['closes'][-1], v['ind']['total']))


if __name__ == '__main__':
    main()
