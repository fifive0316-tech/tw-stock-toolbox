#!/usr/bin/env python3
"""股利估價雷達 近十日籌碼更新

用法:
  python3 -I update_chips.py --stocks stocks.json --radar data.json --out chips.json

data.json = 「台股趨勢雷達」artifact (https://claude.ai/artifact/3yRUz5AQWiu4vdwxbzXpbu) 的 data.json。
對 stocks.json 裡的每一檔,取趨勢雷達中最近 10 個有成交的交易日:
  d = 日期(YYYYMMDD)、v = 成交量(股)、f/t/s = 外資/投信/自營商買賣超(股);某日沒有法人資料則為 null(不補 0)。
頁面顯示時自行除以 1000 換算成「張」。

輸出 chips.json: {"asof": "YYYYMMDD", "n_days": 10, "stocks": {"2330": {"d":[...],"v":[...],"f":[...],"t":[...],"s":[...],"tr":"uptrend","ry":41.2,"rm":"202610"}, ...}}
asof = 趨勢雷達資料的最新日期;若趨勢雷達當天沒更新,asof 會停在前一次的日期,這是正常情況,照樣輸出。

2026-11-16 起每檔多帶三個「品質指標」用的欄位(頁面的品質分數會用到,缺了就顯示「—」):
  tr = 趨勢雷達的趨勢分類(uptrend / downtrend / breakout_watch / breakdown_watch / consolidation / data_insufficient)
  ry = 近 3 個月營收合計的年增率(%);rm = 這 3 個月的最後一個月(YYYYMM)
       今年的月營收取 stocks.json 的 rev_this_year(億元),去年同月取趨勢雷達 data.json 的 rev(千元);
       兩邊重疊的月份若相差超過 5%(口徑不同),或 stocks.json 沒有營收,就改成全部用趨勢雷達自己的最近 3 個月。
       去年同期合計不是正數、或月份湊不齊 → null。

結束代碼:0 = 已產生;1 = 對得上的股票不到八成(資料可能有問題),不應發布。
"""
import argparse, json, sys

N_DAYS = 10


def rev3_yoy(stock, rec):
    """近 3 個月營收年增率(%) 與所用的最後一個月份;算不出來回傳 (None, None)"""
    rev = rec.get('rev') or {}
    rdates = [str(x) for x in (rev.get('dates') or [])]
    rvals = rev.get('values') or []
    radar = {d: v / 1e5 for d, v in zip(rdates, rvals) if v is not None}   # 千元 → 億元

    def prev_year(ym):
        return str(int(ym[:4]) - 1) + ym[4:]

    def calc(now, months):
        if len(months) < 3:
            return None, None
        last3 = months[-3:]
        # 三個月必須連續
        for a, b in zip(last3, last3[1:]):
            y, m = int(a[:4]), int(a[4:])
            nxt = '%04d%02d' % ((y, m + 1) if m < 12 else (y + 1, 1))
            if b != nxt:
                return None, None
        if any(prev_year(m) not in radar for m in last3):
            return None, None
        cur = sum(now[m] for m in last3)
        base = sum(radar[prev_year(m)] for m in last3)
        if base <= 0:
            return None, None
        return round((cur / base - 1) * 100, 1), last3[-1]

    # 今年月營收:stocks.json 的 rev_this_year,月份格式 26M10 → 202610
    own = {}
    for x in (stock.get('rev_this_year') or []):
        m, v = str(x.get('m') or ''), x.get('rev')
        if v is not None and len(m) == 5 and m[2] == 'M':
            own['20' + m[:2] + m[3:]] = float(v)
    if own:
        overlap = [m for m in own if m in radar and radar[m] > 0]
        consistent = all(abs(own[m] / radar[m] - 1) <= 0.05 for m in overlap) if overlap else False
        if consistent:
            y, m = calc(own, sorted(own))
            if y is not None:
                return y, m
    return calc(radar, sorted(radar))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stocks', required=True)
    ap.add_argument('--radar', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    with open(a.stocks, encoding='utf-8') as f:
        stocks = json.load(f)
    with open(a.radar, encoding='utf-8') as f:
        radar = json.load(f)

    # 同一代號若同時出現在上市與上櫃(極少數),取資料較新、較長的那一筆
    by = {}
    for rec in radar.values():
        code = rec.get('code')
        if not code or not rec.get('dates'):
            continue
        cur = by.get(code)
        key = (rec['dates'][-1], len(rec['dates']))
        if cur is None or key > (cur['dates'][-1], len(cur['dates'])):
            by[code] = rec

    out, asof, with_inst, with_rev = {}, '', 0, 0
    for s in stocks:
        rec = by.get(s['code'])
        if not rec:
            continue
        dates = rec['dates'][-N_DAYS:]
        vols = rec['vols'][-N_DAYS:]
        inst = rec.get('inst') or {}
        idx = {d: i for i, d in enumerate(inst.get('dates') or [])}

        def series(name):
            arr = inst.get(name) or []
            return [int(arr[idx[d]]) if d in idx and idx[d] < len(arr) and arr[idx[d]] is not None else None for d in dates]

        row = {'d': dates, 'v': [int(x) for x in vols], 'f': series('foreign'), 't': series('trust'), 's': series('dealer')}
        if any(x is not None for x in row['f']):
            with_inst += 1
        row['tr'] = rec.get('trend') or None
        row['ry'], row['rm'] = rev3_yoy(s, rec)
        if row['ry'] is not None:
            with_rev += 1
        out[s['code']] = row
        if dates[-1] > asof:
            asof = dates[-1]

    print(f'籌碼資料日期 {asof};對上 {len(out)} / {len(stocks)} 檔,其中 {with_inst} 檔近十日內有三大法人資料')
    print(f'品質指標:{sum(1 for v in out.values() if v.get("tr"))} 檔有趨勢分類、{with_rev} 檔算得出近3月營收年增')
    if len(out) < len(stocks) * 0.8:
        print('錯誤:對得上的股票不到八成,不發布籌碼檔。')
        sys.exit(1)
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump({'asof': asof, 'n_days': N_DAYS, 'stocks': out}, f, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main()
