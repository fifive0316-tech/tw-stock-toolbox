#!/usr/bin/env python3
"""台股趨勢雷達 每日更新(獨立架站版,給 GitHub Actions 或自己的電腦執行)

用法:
  python3 scripts/update_trend.py --data site/trend/data.json --extra site/trend/extra.json \
      --quotes-dir work [--max-days 20] [--today YYYYMMDD]

做的事(對應原本 Claude 排程手冊的 Step 2~4,以及 extra.json 的融資與月營收):
 1. 價量:找出 data.json 最新日期之後、到今天為止的平日,逐日抓上市 MI_INDEX 與上櫃 dailyQuotes,
    append 到每檔的 dates/closes/highs/lows/vols,陣列只留最近 90 筆,重算均線、漲跌幅、量比、區間高低點與趨勢分類。
 2. 三大法人:同一批日期抓上市 T86 與上櫃 insti/dailyTrade,append 到 inst(單位:股,抓不到不補 0)。
 3. 融資餘額:extra.json margin.dates 最後一天之後的平日,抓上市 MI_MARGN 與上櫃 margin/balance(單位:張),
    每檔 append,缺值補 null,只留最近 95 筆。融資資料約晚上 9 點才公布,當天 21:30 前不抓今天。
 4. 月營收:官方開放資料 t187ap05_L / mopsfin_t187ap05_O(最新一個月,千元)。每次都覆寫最新月份
    (公告期間每天會多幾家),寫進 extra.json rev.months(留 6 個月)與 data.json 每檔的 rev(留 24 個月)。
 5. 輸出「最新交易日」的收盤價與漲跌到 --quotes-dir/twse.json、tpex.json(格式同官方開放資料),
    給股利估價雷達的 update_prices.py 用。

資料來源都是證交所 / 櫃買中心公開網站;每次請求間隔約 3 秒,避免被當成攻擊而暫時封鎖。
若上市的 MI_INDEX 抓不到但當天是開放資料 STOCK_DAY_ALL 的日期,價量改用開放資料(沒有三大法人)。

結束代碼:0 = 有更新;2 = 沒有新資料(休市或尚未公布);1 = 網路錯誤太多,資料可能不完整。
"""
import argparse, datetime, json, os, re, sys, time, urllib.request, urllib.error

HIST_WINDOW = 90
MARGIN_WINDOW = 95
REV_MONTHS_EXTRA = 6
REV_MONTHS_DATA = 24
PAUSE = 3.0
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
TPE = datetime.timezone(datetime.timedelta(hours=8))

net_errors = []


# ---------------------------------------------------------------- 工具
def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(',', '').replace('+', '')
    if s in ('', '--', '---', '----', '-', 'N/A', 'X'):
        return None
    s = s.replace('X', '')
    try:
        return float(s)
    except ValueError:
        return None


def get_json(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json,text/plain,*/*'})
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read()
            time.sleep(PAUSE)
            txt = raw.decode('utf-8', errors='replace').strip()
            if not txt or txt[0] not in '{[':
                raise ValueError('回傳不是 JSON(可能被暫時封鎖或網站改版):' + txt[:80])
            return json.loads(txt)
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as e:
            last = e
            time.sleep(PAUSE * (i + 2))
    net_errors.append(f'{url} → {last}')
    print(f'  ⚠ 抓取失敗:{url}\n    {last}')
    return None


def slash(d):
    return f'{d[:4]}/{d[4:6]}/{d[6:]}'


def roc(d):
    return str(int(d[:4]) - 1911) + d[4:]


def find_table(data, must):
    for t in (data or {}).get('tables') or []:
        f = t.get('fields') or []
        if all(m in f for m in must) and t.get('data'):
            return t
    return None


def fidx(fields, name, default=None):
    return fields.index(name) if name in fields else default


# ---------------------------------------------------------------- 抓資料(一天)
def twse_prices(d):
    data = get_json(f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json')
    if data is None:
        return None, True
    if str(data.get('date', d)) != d:
        return {}, False
    t = find_table(data, ['證券代號', '收盤價'])
    if not t:
        return {}, False
    f = t['fields']
    ic, iname, ivol = f.index('證券代號'), fidx(f, '證券名稱', 1), fidx(f, '成交股數', 2)
    io, ih, il, icl = f.index('開盤價'), f.index('最高價'), f.index('最低價'), f.index('收盤價')
    isg, idf = fidx(f, '漲跌(+/-)'), fidx(f, '漲跌價差')
    out = {}
    for r in t['data']:
        code = str(r[ic]).strip()
        o, h, l, c, v = num(r[io]), num(r[ih]), num(r[il]), num(r[icl]), num(r[ivol])
        if not code or c is None or c <= 0 or o is None:
            continue
        chg = None
        if idf is not None:
            dv = num(r[idf])
            if dv is not None:
                sg = re.sub(r'<[^>]+>', '', str(r[isg])) if isg is not None else ''
                chg = -dv if '-' in sg else dv
        out[code] = {'name': str(r[iname]).strip(), 'o': o, 'h': h, 'l': l, 'c': c, 'v': v or 0, 'chg': chg}
    return out, False


def twse_prices_openapi(d):
    """備援:開放資料 STOCK_DAY_ALL 只有最新一天;日期相符才用"""
    rows = get_json('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL')
    if not rows or str(rows[0].get('Date')) != roc(d):
        return None
    out = {}
    for r in rows:
        c, o = num(r.get('ClosingPrice')), num(r.get('OpeningPrice'))
        if c is None or c <= 0 or o is None:
            continue
        out[str(r['Code']).strip()] = {'name': str(r.get('Name', '')).strip(), 'o': o, 'h': num(r.get('HighestPrice')),
                                       'l': num(r.get('LowestPrice')), 'c': c, 'v': num(r.get('TradeVolume')) or 0,
                                       'chg': num(r.get('Change'))}
    return out


def tpex_prices(d):
    data = get_json(f'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={slash(d)}&id=&response=json')
    if data is None:
        return None, True
    if str(data.get('date', '')) != d:
        return {}, False
    t = (data.get('tables') or [{}])[0]
    f = t.get('fields') or []
    if '代號' not in f or not t.get('data'):
        return {}, False
    ic, iname, icl, ichg = f.index('代號'), f.index('名稱'), f.index('收盤'), fidx(f, '漲跌')
    io, ih, il, iv = f.index('開盤'), f.index('最高'), f.index('最低'), f.index('成交股數')
    out = {}
    for r in t['data']:
        code = str(r[ic]).strip()
        o, c = num(r[io]), num(r[icl])
        if not code or o is None or c is None or c <= 0:
            continue
        out[code] = {'name': str(r[iname]).strip(), 'o': o, 'h': num(r[ih]), 'l': num(r[il]), 'c': c,
                     'v': num(r[iv]) or 0, 'chg': num(r[ichg]) if ichg is not None else None}
    return out, False


def twse_inst(d):
    data = None
    for url in (f'https://www.twse.com.tw/rwd/zh/fund/T86?date={d}&selectType=ALLBUT0999&response=json',
                f'https://www.twse.com.tw/fund/T86?response=json&date={d}&selectType=ALLBUT0999'):
        data = get_json(url)
        if data is not None:
            break
    if not data or not data.get('data'):
        return {}
    if data.get('date') and str(data['date']) != d:
        return {}
    f = data.get('fields') or []
    ic = fidx(f, '證券代號', 0)
    i_f1 = fidx(f, '外陸資買賣超股數(不含外資自營商)', 4)
    i_f2 = fidx(f, '外資自營商買賣超股數', 7)
    i_t = fidx(f, '投信買賣超股數', 10)
    i_d = fidx(f, '自營商買賣超股數', 11)
    out = {}
    for r in data['data']:
        code = str(r[ic]).strip()
        a, b, t, dl = num(r[i_f1]), num(r[i_f2]), num(r[i_t]), num(r[i_d])
        if a is None or t is None or dl is None:
            continue
        out[code] = (int(a + (b or 0)), int(t), int(dl))
    return out


def tpex_inst(d):
    data = get_json(f'https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?date={slash(d)}&type=Daily&response=json')
    if not data or str(data.get('date', '')) != d:
        return {}
    t = (data.get('tables') or [{}])[0]
    out = {}
    for r in t.get('data') or []:
        if len(r) < 24:
            continue
        code = str(r[0]).strip()
        fo, tr, de = num(r[10]), num(r[13]), num(r[22])
        if fo is None or tr is None or de is None:
            continue
        out[code] = (int(fo), int(tr), int(de))
    return out


def twse_margin(d):
    for url in (f'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d}&selectType=ALL&response=json',
                f'https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date={d}&selectType=ALL'):
        data = get_json(url)
        if data is None:
            continue
        if data.get('date') and str(data['date']) != d:
            return {}
        t = find_table(data, ['代號'])
        if not t:
            return {}
        return {str(r[0]).strip(): num(r[6]) for r in t['data'] if len(r) > 6}
    return None


def tpex_margin(d):
    data = get_json(f'https://www.tpex.org.tw/www/zh-tw/margin/balance?date={slash(d)}&id=&response=json')
    if data is None:
        return None
    if str(data.get('date', '')) != d:
        return {}
    t = (data.get('tables') or [{}])[0]
    return {str(r[0]).strip(): num(r[6]) for r in (t.get('data') or []) if len(r) > 6}


# ---------------------------------------------------------------- 重算(與原本 analyze.py / 排程手冊相同)
try:
    import numpy as _np      # 與原本 analyze.py 一樣用 numpy 平均,數字到小數第二位才會完全一致
except ImportError:
    _np = None


def mean(a):
    if not len(a):
        return None
    return float(_np.mean(_np.array(a, dtype=float))) if _np is not None else sum(a) / len(a)


def recompute(rec):
    c, h, l, v, d = rec['closes'], rec['highs'], rec['lows'], rec['vols'], rec['dates']
    n = len(c)
    rec['n_days'] = n
    if n < 10:
        rec['trend'] = 'data_insufficient'
        if n:
            rec.update({'date': d[-1], 'close': float(c[-1]), 'vol': int(v[-1])})
        return

    def ma(k):
        return mean(c[-min(k, n):])
    ma5, ma10, ma20 = ma(5), ma(10), ma(20)

    def pct(k):
        if n > k and c[-1 - k]:
            return round((c[-1] - c[-1 - k]) / c[-1 - k] * 100, 2)
        return None
    hi = max(h); lo = min(l)
    if n > 6:
        window = v[-11:-1] if n > 11 else v[:-1]
        av = mean(window) if len(window) else None
        vol_ratio = round(v[-1] / av, 2) if av and av > 0 else None
    else:
        vol_ratio = None
    rng = h[-1] - l[-1]
    close_pos = round((c[-1] - l[-1]) / rng, 2) if rng > 0 else 0.5
    ma5_prev = mean(c[-9:-4]) if n > 8 else None
    slope = (ma5 - ma5_prev) if ma5_prev is not None else 0
    last = c[-1]
    if last > ma5 > ma10 > ma20 and slope > 0:
        trend = 'uptrend'
    elif last < ma5 < ma10 < ma20 and slope < 0:
        trend = 'downtrend'
    elif last >= hi * 0.97 and last > ma5:
        trend = 'breakout_watch'
    elif last <= lo * 1.03 and last < ma5:
        trend = 'breakdown_watch'
    else:
        trend = 'consolidation'
    rec.update({
        'date': d[-1], 'close': float(last), 'ma5': round(ma5, 2), 'ma10': round(ma10, 2), 'ma20': round(ma20, 2),
        'chg_1d': pct(1), 'chg_5d': pct(5), 'chg_20d': pct(min(20, n - 1)),
        'vol': int(v[-1]), 'vol_ratio': vol_ratio, 'close_pos': close_pos,
        'period_high': float(hi), 'period_high_date': d[h.index(hi)],
        'period_low': float(lo), 'period_low_date': d[l.index(lo)],
        'trend': trend,
    })


# ---------------------------------------------------------------- 主流程
def weekdays_after(last, today):
    out, day = [], datetime.datetime.strptime(last, '%Y%m%d').date() + datetime.timedelta(days=1)
    end = datetime.datetime.strptime(today, '%Y%m%d').date()
    while day <= end:
        if day.weekday() < 5:
            out.append(day.strftime('%Y%m%d'))
        day += datetime.timedelta(days=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--extra', required=True)
    ap.add_argument('--quotes-dir', required=True)
    ap.add_argument('--max-days', type=int, default=20)
    ap.add_argument('--today', help='測試用,YYYYMMDD(台北日期)')
    a = ap.parse_args()

    now = datetime.datetime.now(TPE)
    today = a.today or now.strftime('%Y%m%d')
    hhmm = now.hour * 100 + now.minute if not a.today else 2359

    with open(a.data, encoding='utf-8') as f:
        data = json.load(f)
    with open(a.extra, encoding='utf-8') as f:
        extra = json.load(f)

    changed = False
    last_date = max(r['date'] for r in data.values() if r.get('date'))
    cands = weekdays_after(last_date, today)
    if cands and cands[-1] == today and hhmm < 1430:
        cands = cands[:-1]                       # 收盤資料大約 14:30 後才有
    if len(cands) > a.max_days:
        print(f'缺口 {len(cands)} 個平日,只補最近 {a.max_days} 個')
        cands = cands[-a.max_days:]
    print(f'價量最新日期 {last_date};這次嘗試:{cands or "(無)"}')

    latest_quotes = None
    for d in cands:
        tw, tw_err = twse_prices(d)
        if tw_err or not tw:
            alt = twse_prices_openapi(d)
            if alt:
                print(f'  {d} 上市 MI_INDEX 抓不到,改用開放資料 STOCK_DAY_ALL')
                tw, tw_err = alt, False
        tp, tp_err = tpex_prices(d)
        if tw_err or tp_err:
            # 某個市場是「連線失敗」而不是「沒資料」:這天先不寫,下次執行會重抓,避免留下一邊缺資料的日子
            print(f'  ✗ {d}:{"上市" if tw_err else "上櫃"}行情連線失敗,這天與之後的日期這次都不寫入,下次再補')
            break
        if not tw and not tp:
            print(f'  {d}:兩市場都沒有資料(休市或尚未公布),略過')
            continue
        if not tw or not tp:
            print(f'  ⚠ {d}:只有{"上市" if tw else "上櫃"}有資料,另一邊{"抓取失敗" if (tw_err or tp_err) else "沒有資料"}')
        ins_tw = twse_inst(d) if tw else {}
        ins_tp = tpex_inst(d) if tp else {}
        added = 0
        for market, px, ins in (('TWSE', tw or {}, ins_tw), ('TPEX', tp or {}, ins_tp)):
            for code, q in px.items():
                key = f'{market}_{code}'
                rec = data.get(key)
                if rec is None:
                    if market == 'TPEX' and not re.match(r'^[0-9]{4}$', code):
                        continue
                    rec = data[key] = {'code': code, 'name': q['name'], 'market': market,
                                       'closes': [], 'highs': [], 'lows': [], 'vols': [], 'dates': []}
                if rec['dates'] and rec['dates'][-1] >= d:
                    continue
                rec['name'] = q['name'] or rec.get('name')
                for k, val in (('dates', d), ('closes', q['c']), ('highs', q['h'] or q['c']),
                               ('lows', q['l'] or q['c']), ('vols', int(q['v']))):
                    rec[k].append(val)
                    del rec[k][:-HIST_WINDOW]
                added += 1
                if code in ins:
                    inst = rec.setdefault('inst', {'dates': [], 'foreign': [], 'trust': [], 'dealer': []})
                    if not inst['dates'] or inst['dates'][-1] < d:
                        for k, val in zip(('dates', 'foreign', 'trust', 'dealer'), (d,) + ins[code]):
                            inst[k].append(val)
                            del inst[k][:-HIST_WINDOW]
        print(f'  {d}:價量 上市 {len(tw or {})}、上櫃 {len(tp or {})};三大法人 上市 {len(ins_tw)}、上櫃 {len(ins_tp)};寫入 {added} 檔')
        if added:
            changed = True
            if tw and tp:
                latest_quotes = (d, tw, tp)

    if changed:
        for rec in data.values():
            recompute(rec)

    # ---- 融資餘額
    mg = extra.setdefault('margin', {'unit': 'lots', 'dates': [], 'bal': {}})
    m_last = mg['dates'][-1] if mg['dates'] else last_date
    m_cands = weekdays_after(m_last, today)
    if m_cands and m_cands[-1] == today and hhmm < 2130:
        m_cands = m_cands[:-1]
    m_cands = m_cands[-a.max_days:]
    for d in m_cands:
        tw = twse_margin(d)
        tp = tpex_margin(d)
        if tw is None or tp is None:
            print(f'  ✗ 融資 {d}:{"上市" if tw is None else "上櫃"}連線失敗,這天與之後的日期這次都不寫入,下次再補')
            break
        if not tw and not tp:
            print(f'  融資 {d}:沒有資料,略過')
            continue
        mg['dates'].append(d)
        n = len(mg['dates'])
        seen = set()
        for market, src in (('TWSE', tw or {}), ('TPEX', tp or {})):
            for code, bal in src.items():
                if not re.match(r'^[1-9][0-9]{3}$', code):
                    continue
                key = f'{market}_{code}'
                arr = mg['bal'].setdefault(key, [])
                arr.extend([None] * (n - 1 - len(arr)))
                arr.append(None if bal is None else int(bal))
                seen.add(key)
        for key, arr in mg['bal'].items():
            if key not in seen:
                arr.extend([None] * (n - len(arr)))
        changed = True
        print(f'  融資 {d}:上市 {len(tw or {})}、上櫃 {len(tp or {})}')
    if len(mg['dates']) > MARGIN_WINDOW:
        cut = len(mg['dates']) - MARGIN_WINDOW
        mg['dates'] = mg['dates'][cut:]
        for key in list(mg['bal']):
            mg['bal'][key] = mg['bal'][key][cut:]
    assert all(len(v) == len(mg['dates']) for v in mg['bal'].values()), '融資陣列長度與日期不一致'
    if mg['dates']:
        extra['asof'] = mg['dates'][-1]

    # ---- 月營收(最新一個月,每次覆寫)
    rev = extra.setdefault('rev', {'unit': 'thousand_twd', 'months': {}})
    for market, url in (('TWSE', 'https://openapi.twse.com.tw/v1/opendata/t187ap05_L'),
                        ('TPEX', 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O')):
        rows = get_json(url) or []
        upd = 0
        for r in rows:
            ym_roc, code = str(r.get('資料年月', '')).strip(), str(r.get('公司代號', '')).strip()
            v, yoy = num(r.get('營業收入-當月營收')), num(r.get('營業收入-去年同月增減(%)'))
            if len(ym_roc) < 4 or not code or v is None:
                continue
            ym = str(int(ym_roc[:-2]) + 1911) + ym_roc[-2:]
            key = f'{market}_{code}'
            yoy = None if yoy is None else round(yoy, 2)
            month = rev['months'].setdefault(ym, {})
            if month.get(key) != [int(v), None if yoy is None else round(yoy, 1)]:
                month[key] = [int(v), None if yoy is None else round(yoy, 1)]
                changed = True
            rec = data.get(key)
            if rec is not None:
                rv = rec.get('rev')
                if not isinstance(rv, dict) or not isinstance(rv.get('dates'), list):
                    rv = rec['rev'] = {'dates': [], 'values': [], 'yoy': []}
                ds = [str(x) for x in rv['dates']]
                if ds and ds[-1] == ym:
                    if rv['values'][-1] != int(v) or rv['yoy'][-1] != yoy:
                        rv['values'][-1], rv['yoy'][-1] = int(v), yoy
                        changed = True
                elif not ds or ds[-1] < ym:
                    rv['dates'].append(ym); rv['values'].append(int(v)); rv['yoy'].append(yoy)
                    for k in ('dates', 'values', 'yoy'):
                        del rv[k][:-REV_MONTHS_DATA]
                    changed = True
            upd += 1
        print(f'月營收 {market}:{upd} 筆')
    for ym in sorted(rev['months'])[:-REV_MONTHS_EXTRA]:
        del rev['months'][ym]

    # ---- 輸出
    if latest_quotes:
        d, tw, tp = latest_quotes
        os.makedirs(a.quotes_dir, exist_ok=True)
        with open(os.path.join(a.quotes_dir, 'twse.json'), 'w', encoding='utf-8') as f:
            json.dump([{'Date': roc(d), 'Code': c, 'ClosingPrice': q['c'], 'Change': q['chg']} for c, q in tw.items()], f, ensure_ascii=False)
        with open(os.path.join(a.quotes_dir, 'tpex.json'), 'w', encoding='utf-8') as f:
            json.dump([{'Date': roc(d), 'SecuritiesCompanyCode': c, 'Close': q['c'], 'Change': q['chg']} for c, q in tp.items()], f, ensure_ascii=False)
        print(f'已輸出 {d} 收盤價給股利估價雷達')

    if changed:
        with open(a.data, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        with open(a.extra, 'w', encoding='utf-8') as f:
            json.dump(extra, f, ensure_ascii=False, separators=(',', ':'))
    newest = max(r['date'] for r in data.values() if r.get('date'))
    print(f'價量資料至 {newest}、共 {len(data)} 檔;融資至 {extra.get("asof")};月營收月份 {sorted(rev["months"])}')
    if net_errors:
        print(f'網路錯誤 {len(net_errors)} 次(上面有網址與原因)')
    if net_errors and not changed:
        sys.exit(1)
    sys.exit(0 if changed else 2)


if __name__ == '__main__':
    main()
