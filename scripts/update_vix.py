#!/usr/bin/env python3
"""更新 VIX 期限结构数据:下载 VIX9D、VIX、VIX3M、VIX6M 日收盘价,计算比值、状态和历次倒挂,
写入 docs/data/vix_term.json。优先使用 Cboe 官网数据,失败或不够新时改用 yfinance。"""
import io, json, sys, datetime as dt, urllib.request
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'data' / 'vix_term.json'
START = '2011-01-03'                                   # VIX9D 自 2011 年起有数据
NAMES = ['VIX9D', 'VIX', 'VIX3M', 'VIX6M']
CBOE = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv'
YF = {'VIX9D': '^VIX9D', 'VIX': '^VIX', 'VIX3M': '^VIX3M', 'VIX6M': '^VIX6M'}
FLAT = 0.95                                            # 0.95–1 视为接近持平

def from_cboe(name):
    req = urllib.request.Request(CBOE.format(name), headers={'User-Agent': 'Mozilla/5.0 (vix-monitor)'})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode('utf-8-sig')
    df = pd.read_csv(io.StringIO(raw)); df.columns = [str(c).strip().upper() for c in df.columns]
    col = 'CLOSE' if 'CLOSE' in df.columns else df.columns[-1]
    idx = pd.to_datetime(df[df.columns[0]], errors='coerce')
    return pd.Series(pd.to_numeric(df[col], errors='coerce').values, index=idx).dropna().sort_index()

def from_yf(name):
    import yfinance as yf
    s = yf.download(YF[name], start='2008-01-01', progress=False, auto_adjust=False)['Close'].squeeze()
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None: s.index = s.index.tz_localize(None)
    return s.dropna().sort_index()

def load(name):
    got = []
    for f in (from_cboe, from_yf):                     # 两个数据源都取,各指数用日期最新的一份
        try:
            s = f(name)
            if len(s) > 250: got.append((s, f.__name__))
        except Exception as e:
            print(f'[警告] {name} 通过 {f.__name__} 获取失败:{e}', file=sys.stderr)
    if not got: sys.exit(f'[错误] {name} 两个数据源都获取失败')
    print(f"{name}:" + ",".join(f"{src} 至 {x.index[-1].date()}" for x, src in got))
    return max(got, key=lambda t: (t[0].index[-1], t[1] == 'from_cboe'))

def main():
    S, SRC = {}, {}
    for n in NAMES: S[n], SRC[n] = load(n)
    d = pd.DataFrame(S).dropna(); d = d[d.index >= START]
    d['r_short'] = d['VIX9D'] / d['VIX']; d['r_main'] = d['VIX'] / d['VIX3M']; d['r_mid'] = d['VIX3M'] / d['VIX6M']
    d['pct1y'] = d['r_main'].rolling(252).apply(lambda x: (x <= x[-1]).mean(), raw=True)
    d['state'] = np.where(d['r_main'] > 1, 'inverted', np.where(d['r_main'] > FLAT, 'flat', 'contango'))
    inv = (d['r_main'] > 1).astype(int); grp = (inv != inv.shift()).cumsum()
    d['streak'] = inv.groupby(grp).cumsum() * inv
    eps = []
    for _, g in d[inv == 1].groupby(grp[inv == 1]):
        pk = g['r_main'].idxmax()
        eps.append({'start': g.index[0].strftime('%Y-%m-%d'), 'end': g.index[-1].strftime('%Y-%m-%d'), 'days': int(len(g)),
                    'peak': round(float(g['r_main'].max()), 4), 'peak_date': pk.strftime('%Y-%m-%d'),
                    'peak_vix': round(float(g.loc[pk, 'VIX']), 2), 'ongoing': bool(g.index[-1] == d.index[-1])})
    L, prev, y1 = d.iloc[-1], d.iloc[-2], d.iloc[-252:]
    ago = lambda k: d.iloc[-1 - k] if len(d) > k else d.iloc[0]
    curve = lambda r: [round(float(r[n]), 2) for n in NAMES]
    latest = {'date': d.index[-1].strftime('%Y-%m-%d'),
              'levels': {n: round(float(L[n]), 2) for n in NAMES}, 'change': {n: round(float(L[n] - prev[n]), 2) for n in NAMES},
              'r_short': round(float(L['r_short']), 4), 'r_main': round(float(L['r_main']), 4), 'r_mid': round(float(L['r_mid']), 4),
              'pct1y': round(float(L['pct1y']), 4), 'state': str(L['state']), 'streak': int(L['streak']),
              'curve': {'today': curve(L), 'week_ago': curve(ago(5)), 'month_ago': curve(ago(21)),
                        'week_ago_date': ago(5).name.strftime('%Y-%m-%d'), 'month_ago_date': ago(21).name.strftime('%Y-%m-%d')}}
    stats = {'median_1y': round(float(y1['r_main'].median()), 4), 'p90_1y': round(float(y1['r_main'].quantile(0.9)), 4),
             'inverted_days_1y': int((y1['r_main'] > 1).sum()), 'days_1y': int(len(y1))}
    cols = ['VIX9D', 'VIX', 'VIX3M', 'VIX6M', 'r_short', 'r_main', 'r_mid', 'pct1y']
    series = [[i.strftime('%Y-%m-%d')] + [None if pd.isna(r[c]) else round(float(r[c]), 4 if c.startswith(('r_', 'pct')) else 2) for c in cols]
              + [r['state']] for i, r in d.iterrows()]
    out = {'updated_at': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M'), 'sources': SRC, 'flat_threshold': FLAT,
           'columns': ['date'] + cols + ['state'], 'latest': latest, 'stats_1y': stats, 'episodes': eps[::-1], 'series': series}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"已更新至 {latest['date']}:VIX/VIX3M {latest['r_main']:.3f}({latest['state']}),数据源 {SRC}")

if __name__ == '__main__':
    main()
