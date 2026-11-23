#!/usr/bin/env python3
"""股利估價雷達 月營收自動更新(取代原本每月手動上傳的月營收 CSV)

用法:
  python3 scripts/update_div_revenue.py --stocks site/dividend/stocks.json \
      --twse-rev rev_L.json --tpex-rev rev_O.json --out stocks.rev.json

twse-rev = https://openapi.twse.com.tw/v1/opendata/t187ap05_L        上市公司每月營業收入彙總表(最新一個月,千元)
tpex-rev = https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O     上櫃

更新每檔的:
  rev_this_year  該月份(格式 26M10)的單月營收,單位億元 = 千元 ÷ 100,000
  rev_total_year 累計營收(億元)
  rev_yoy_pct    累計營收年增率(%)
只處理 THIS_YEAR 這一年的月份。營收改變後要再跑 post_merge_fix.py,Q4 推估與估值才會跟著重算。

結束代碼:0 = 有變動;2 = 沒有變動;1 = 來源格式不符。
"""
import argparse, json, sys

THIS_YEAR = 2026      # ← 跨年度時要和 post_merge_fix.py 的 THIS_YEAR 一起改


def num(v):
    try:
        return float(str(v).replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    for k in ('stocks', 'twse-rev', 'tpex-rev', 'out'):
        ap.add_argument('--' + k, required=True)
    a = ap.parse_args()
    rows = []
    for p in (a.twse_rev, a.tpex_rev):
        with open(p, encoding='utf-8') as f:
            rows += json.load(f)
    by, months = {}, set()
    for r in rows:
        code, ym = str(r.get('公司代號', '')).strip(), str(r.get('資料年月', '')).strip()
        v = num(r.get('營業收入-當月營收'))
        if not code or len(ym) < 4 or v is None:
            continue
        y, m = int(ym[:-2]) + 1911, int(ym[-2:])
        months.add((y, m))
        by[code] = (y, m, v, num(r.get('累計營業收入-當月累計營收')), num(r.get('累計營業收入-前期比較增減(%)')))
    print(f'官方月營收 {len(by)} 檔,月份 {sorted(months)}')
    if len(by) < 1000:
        print('錯誤:筆數過少,不處理。'); sys.exit(1)

    with open(a.stocks, encoding='utf-8') as f:
        stocks = json.load(f)
    changed, skipped_year = 0, 0
    for s in stocks:
        x = by.get(s['code'])
        if not x:
            continue
        y, m, v, cum, cum_yoy = x
        if y != THIS_YEAR:
            skipped_year += 1
            continue
        key = f'{y % 100:02d}M{m:02d}'
        rev = round(v / 1e5, 2)
        lst = s.setdefault('rev_this_year', [])
        hit = next((e for e in lst if e.get('m') == key), None)
        before = json.dumps([lst, s.get('rev_total_year'), s.get('rev_yoy_pct')], ensure_ascii=False)
        if hit:
            hit['rev'] = rev
        else:
            lst.append({'m': key, 'rev': rev})
            lst.sort(key=lambda e: e['m'])
        if cum is not None:
            s['rev_total_year'] = round(cum / 1e5, 1)
        if cum_yoy is not None:
            s['rev_yoy_pct'] = round(cum_yoy, 1)
        if json.dumps([lst, s.get('rev_total_year'), s.get('rev_yoy_pct')], ensure_ascii=False) != before:
            changed += 1
    if skipped_year:
        print(f'⚠ {skipped_year} 檔的最新月份不是 {THIS_YEAR} 年,沒有寫入(跨年度時要改 THIS_YEAR 與估值公式)')
    print(f'月營收有變動 {changed} 檔')
    if not changed:
        sys.exit(2)
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main()
