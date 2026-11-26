#!/usr/bin/env python3
"""MPT 投資組合:全市場(上市+上櫃,含 ETF)的「還原權息」日收盤價(Yahoo Finance,與 yfinance 同一個資料來源)

用法(在專案最上層資料夾執行):
  python3 scripts/update_mpt.py [--budget 120] [--workers 4] [--limit 0]

標的清單取自 site/trend/data.json(趨勢雷達每天更新的全市場清單),產業取自 site/dividend/industry.json。
輸出到 site/mpt/px/(不放進 git,由 GitHub Actions 快取保存,發布網站時一起上傳):
  px/index.json      清單:{"asof": "20261125", "list": [{"c": 代號, "n": 名稱, "g": "ETF/上市/上櫃", "i": 產業,
                              "s": 起日, "e": 迄日, "u": 最後抓取日}, ...]}
  px/<代號>.json     {"d0": 第一天 YYYYMMDD, "dd": [與前一筆相差的天數...], "p": [還原收盤價...]}

更新方式:
  - 沒有檔案的標的 → 抓 2015 年起的完整歷史
  - 已有檔案 → 只抓最近約 40 天;若重疊日期的還原價變了(代表有新的除權息或分割,Yahoo 會整段重算),改抓完整歷史
  - 今天已經抓過(台北時間收盤後)的跳過;依「最久沒更新」優先,超過 --budget 分鐘就停,沒抓到的下次再補
結束代碼:0 正常(含部分沒抓到)、1 一檔都沒成功。
"""
import argparse, json, os, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = 'Mozilla/5.0'   # Yahoo 會對完整瀏覽器 UA 回 429,用簡短 UA 反而正常
TPE = timezone(timedelta(hours=8))
START = '2015-01-01'
_pause_until = [0.0]
_lock = threading.Lock()


def now_tpe():
    return datetime.now(TPE)


def ymd_to_ts(ymd):
    return int(datetime.strptime(ymd, '%Y%m%d').replace(tzinfo=TPE).timestamp())


def sig(v, n=6):
    """保留 n 位有效數字,縮小檔案"""
    if v == 0:
        return 0
    from math import floor, log10
    return round(v, max(0, n - 1 - int(floor(log10(abs(v))))))


def fetch(symbol, start_ts, tries=4):
    """回傳 {YYYYMMDD: 還原收盤價};抓不到回 None,沒有資料(下市/代號不存在)回 {}"""
    now = now_tpe()
    skip_today = now.strftime('%Y%m%d') if (now.hour, now.minute) < (14, 30) else None   # 盤中的當日價不算
    for i in range(tries):
        wait = _pause_until[0] - time.time()
        if wait > 0:
            time.sleep(wait)
        host = 'query1' if i % 2 == 0 else 'query2'
        url = (f'https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}'
               f'?period1={start_ts}&period2={int(time.time()) + 86400}&interval=1d&events=div%2Csplit')
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
            with urllib.request.urlopen(req, timeout=60) as r:
                js = json.loads(r.read().decode('utf-8'))
            res = (js.get('chart') or {}).get('result')
            if not res:
                return {}
            res = res[0]
            ts = res.get('timestamp') or []
            adj = ((res.get('indicators') or {}).get('adjclose') or [{}])[0].get('adjclose') or []
            out = {}
            for t, v in zip(ts, adj):
                if v is None or v <= 0:
                    continue
                d = datetime.fromtimestamp(t, TPE).strftime('%Y%m%d')
                if d != skip_today:
                    out[d] = sig(float(v))
            return out
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            if e.code == 429:        # 被限速:所有執行緒一起暫停
                with _lock:
                    _pause_until[0] = max(_pause_until[0], time.time() + 20 * (i + 1))
            time.sleep(2 * (i + 1))
        except Exception:            # noqa: BLE001  網路問題一律重試
            time.sleep(3 * (i + 1))
    return None


def load_series(path):
    try:
        with open(path, encoding='utf-8') as f:
            j = json.load(f)
        d = datetime.strptime(j['d0'], '%Y%m%d')
        out = {}
        for k, (dd, p) in enumerate(zip([0] + j['dd'], j['p'])):
            d += timedelta(days=dd)
            out[d.strftime('%Y%m%d')] = p
        return out
    except Exception:                # noqa: BLE001  壞檔就當沒有
        return None


def save_series(path, s):
    dates = sorted(s)
    prev, dd = datetime.strptime(dates[0], '%Y%m%d'), []
    for d in dates[1:]:
        cur = datetime.strptime(d, '%Y%m%d')
        dd.append((cur - prev).days)
        prev = cur
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'d0': dates[0], 'dd': dd, 'p': [s[d] for d in dates]}, f, separators=(',', ':'))
    os.replace(tmp, path)


def update_one(item, pxdir, full_start_ts):
    """回傳 (狀態, 序列);狀態:full/inc/nodata/fail"""
    code, sym = item['c'], item['sym']
    path = os.path.join(pxdir, code + '.json')
    old = load_series(path) if os.path.exists(path) else None
    if old:
        last = max(old)
        since = (datetime.strptime(last, '%Y%m%d') - timedelta(days=40)).strftime('%Y%m%d')
        new = fetch(sym, ymd_to_ts(since))
        if new is None:
            return 'fail', old
        overlap = [d for d in new if d in old]
        same = overlap and all(abs(new[d] - old[d]) <= 2e-4 * max(abs(old[d]), 1e-9) for d in overlap)
        if same:
            old.update(new)
            save_series(path, old)
            return 'inc', old
        # 有新的除權息/分割(或沒有重疊),整段重抓
    new = fetch(sym, full_start_ts)
    if new is None:
        return 'fail', old
    if not new:
        return 'nodata', old
    save_series(path, new)
    return 'full', new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--radar', default=os.path.join(ROOT, 'site', 'trend', 'data.json'))
    ap.add_argument('--industry', default=os.path.join(ROOT, 'site', 'dividend', 'industry.json'))
    ap.add_argument('--outdir', default=os.path.join(ROOT, 'site', 'mpt', 'px'))
    ap.add_argument('--budget', type=float, default=120, help='最多執行幾分鐘')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--limit', type=int, default=0, help='只處理前 N 檔(測試用)')
    a = ap.parse_args()
    t0 = time.time()
    os.makedirs(a.outdir, exist_ok=True)

    with open(a.radar, encoding='utf-8') as f:
        radar = json.load(f)
    try:
        with open(a.industry, encoding='utf-8') as f:
            ind = json.load(f).get('map', {})
    except Exception:                # noqa: BLE001
        ind = {}

    idx_path = os.path.join(a.outdir, 'index.json')
    old_idx = {}
    if os.path.exists(idx_path):
        try:
            with open(idx_path, encoding='utf-8') as f:
                old_idx = {x['c']: x for x in json.load(f).get('list', [])}
        except Exception:            # noqa: BLE001
            old_idx = {}

    items = []
    for s in radar.values():
        code, mkt = s.get('code'), s.get('market')
        if not code or mkt not in ('TWSE', 'TPEX'):
            continue
        items.append({'c': code, 'n': s.get('name', ''), 'sym': code + ('.TW' if mkt == 'TWSE' else '.TWO'),
                      'g': 'ETF' if code.startswith('00') else ('上市' if mkt == 'TWSE' else '上櫃'),
                      'i': ind.get(code, '')})
    items.sort(key=lambda x: x['c'])
    if a.limit:
        items = items[:a.limit]

    now = now_tpe()
    closed = (now.hour, now.minute) >= (14, 30)
    today = now.strftime('%Y%m%d')

    def done_today(it):
        o = old_idx.get(it['c'])
        return bool(o and o.get('u') == today and closed and o.get('uc') and
                    os.path.exists(os.path.join(a.outdir, it['c'] + '.json')))

    # 沒檔案的先抓,其他依最後抓取日由舊到新
    todo = [it for it in items if not done_today(it)]
    todo.sort(key=lambda it: (os.path.exists(os.path.join(a.outdir, it['c'] + '.json')),
                              (old_idx.get(it['c']) or {}).get('u', '')))
    print(f'全市場 {len(items)} 檔,本次要處理 {len(todo)} 檔(預算 {a.budget:.0f} 分鐘)', flush=True)

    full_start_ts = ymd_to_ts(START.replace('-', ''))
    stats = {'full': 0, 'inc': 0, 'nodata': 0, 'fail': 0, 'skip': 0}
    meta = {}
    stop = threading.Event()

    def job(it):
        if stop.is_set() or time.time() - t0 > a.budget * 60:
            stop.set()
            return it, 'skip', None
        st, s = update_one(it, a.outdir, full_start_ts)
        return it, st, s

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(job, it) for it in todo]
        for n, fu in enumerate(as_completed(futs), 1):
            it, st, s = fu.result()
            stats[st] += 1
            if st in ('full', 'inc'):
                meta[it['c']] = {'s': min(s), 'e': max(s), 'u': today, 'uc': closed}
            if n % 200 == 0:
                print(f'  {n}/{len(todo)} 已處理,{(time.time() - t0) / 60:.1f} 分鐘', flush=True)

    # 重新整理清單:只列出有價格檔的標的
    out = []
    for it in items:
        path = os.path.join(a.outdir, it['c'] + '.json')
        if not os.path.exists(path):
            continue
        m = meta.get(it['c'])
        if not m:
            o = old_idx.get(it['c'])
            if o and o.get('s'):
                m = {k: o.get(k) for k in ('s', 'e', 'u', 'uc')}
            else:
                s = load_series(path)
                if not s:
                    continue
                m = {'s': min(s), 'e': max(s), 'u': '', 'uc': False}
        out.append({'c': it['c'], 'n': it['n'], 'g': it['g'], 'i': it['i'], **m})
    # 已不在全市場清單上的(下市)刪掉
    keep = {it['c'] for it in items}
    if not a.limit:
        for fn in os.listdir(a.outdir):
            if fn.endswith('.json') and fn != 'index.json' and fn[:-5] not in keep:
                os.remove(os.path.join(a.outdir, fn))

    asof = max((x['e'] for x in out), default='')
    with open(idx_path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump({'asof': asof, 'start': START.replace('-', ''), 'source': 'Yahoo Finance 還原權息收盤價',
                   'list': out}, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(idx_path + '.tmp', idx_path)

    print(f'MPT 價格:清單 {len(out)} 檔,資料至 {asof};本次 完整 {stats["full"]}、增量 {stats["inc"]}、'
          f'無資料 {stats["nodata"]}、失敗 {stats["fail"]}、超時未處理 {stats["skip"]},'
          f'耗時 {(time.time() - t0) / 60:.1f} 分鐘', flush=True)
    sys.exit(0 if (stats['full'] + stats['inc'] > 0 or not todo or out) else 1)


if __name__ == '__main__':
    main()
