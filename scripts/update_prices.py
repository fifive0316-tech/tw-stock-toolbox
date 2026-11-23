#!/usr/bin/env python3
"""股利估價雷達 每日股價更新

用法:
  python3 -I update_prices.py --stocks stocks.json --twse twse.json --tpex tpex.json \
      --current-meta meta.json --out-stocks stocks.new.json --out-meta meta.new.json

twse.json = https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL
tpex.json = https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes

只更新:price / chg / chg_pct / yield_pct / valuation_zone。
EPS、預估股利、便宜價、合理價等基本面欄位維持不變(那些要靠使用者上傳的 CSV 更新)。
殖利率 = 預估股利 ÷ 現價 × 100,四捨五入到小數 2 位。
評價規則(與 CSV 合併時一致,2026-11-12 起):殖利率 > 12% → review(待覆核,不列入便宜);
否則 price <= 便宜價 → cheap;<= 合理價 → fair;否則 expensive。

交易日判斷(2026-11-13 起,排程改為隔天早上執行):不再要求資料日期等於執行當天,
改用資料本身的日期:上市、上櫃兩份資料必須是同一個交易日,而且要比線上 meta.json 的
price_date 新才更新;meta.json 的 price_date 寫入資料本身的交易日。
--current-meta 給線上目前的 meta.json(沒有這個檔案就省略,視為第一次更新)。

結束代碼:0 = 已更新;2 = 沒有比線上更新的收盤資料(休市、尚未公布、或兩邊日期不一致),不應發布;1 = 其他錯誤。
"""
import argparse, json, re, sys

REVIEW_YIELD = 12.0  # 推估殖利率超過這個百分比 → 待覆核


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(',', '').replace('+', '')
    s = s.replace('X', '')
    if s in ('', '--', '---', '-', 'N/A'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def roc_to_ad(s):
    """'1151109' 或 '115/11/09' → '20261109';無法解析回傳 None"""
    if not s:
        return None
    digits = re.sub(r'\D', '', str(s))
    if len(digits) == 7:
        return str(int(digits[:3]) + 1911) + digits[3:]
    if len(digits) == 8:
        return digits
    return None


def load_feed(path, code_keys, close_keys, change_keys, date_keys):
    with open(path, encoding='utf-8') as f:
        rows = json.load(f)
    out, dates = {}, set()
    for r in rows:
        code = next((str(r[k]).strip() for k in code_keys if k in r), None)
        if not code:
            continue
        close = next((num(r[k]) for k in close_keys if k in r), None)
        change = next((num(r[k]) for k in change_keys if k in r), None)
        d = next((roc_to_ad(r[k]) for k in date_keys if k in r), None)
        if d:
            dates.add(d)
        if close is None or close <= 0:
            continue
        out[code] = (close, change)
    return out, dates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stocks', required=True)
    ap.add_argument('--twse', required=True)
    ap.add_argument('--tpex', required=True)
    ap.add_argument('--current-meta', help='線上目前的 meta.json;用它的 price_date 判斷有沒有新資料')
    ap.add_argument('--out-stocks', required=True)
    ap.add_argument('--out-meta', required=True)
    a = ap.parse_args()

    twse, twse_dates = load_feed(a.twse, ['Code'], ['ClosingPrice'], ['Change'], ['Date'])
    tpex, tpex_dates = load_feed(a.tpex, ['SecuritiesCompanyCode', 'Code'], ['Close', 'ClosingPrice'],
                                 ['Change'], ['Date'])

    print(f'TWSE 筆數 {len(twse)},日期 {sorted(twse_dates) or "(無日期欄位)"}')
    print(f'TPEx 筆數 {len(tpex)},日期 {sorted(tpex_dates) or "(無日期欄位)"}')

    if len(twse) < 500 or len(tpex) < 300:
        print('錯誤:來源資料筆數過少,可能抓取失敗。')
        sys.exit(1)
    # 兩份資料都要帶單一日期,且是同一個交易日
    for name, ds in (('TWSE', twse_dates), ('TPEx', tpex_dates)):
        if len(ds) != 1:
            print(f'錯誤:{name} 資料的日期欄位異常 {sorted(ds)},無法判斷交易日。')
            sys.exit(1)
    twse_date, tpex_date = next(iter(twse_dates)), next(iter(tpex_dates))
    if twse_date != tpex_date:
        print(f'TWSE 資料日期 {twse_date} 與 TPEx 資料日期 {tpex_date} 不一致,其中一邊尚未公布,不更新。')
        sys.exit(2)
    data_date = twse_date
    current = ''
    if a.current_meta:
        try:
            with open(a.current_meta, encoding='utf-8') as f:
                current = str(json.load(f).get('price_date') or '')
        except (OSError, ValueError) as e:
            print(f'錯誤:讀不到線上的 meta.json({e})。')
            sys.exit(1)
    print(f'資料交易日 {data_date};線上股價日期 {current or "(無)"}')
    if current and data_date <= current:
        print(f'資料交易日 {data_date} 沒有比線上的 {current} 新(休市或尚未公布),不更新。')
        sys.exit(2)

    with open(a.stocks, encoding='utf-8') as f:
        stocks = json.load(f)

    quotes = dict(tpex)
    quotes.update(twse)  # 同代號以上市為準(實務上不會重複)
    updated, missing = 0, []
    zones = {'cheap': 0, 'fair': 0, 'expensive': 0, 'review': 0, None: 0}
    for r in stocks:
        q = quotes.get(r['code'])
        if q:
            close, change = q
            r['price'] = close
            if change is not None:
                prev = close - change
                r['chg'] = round(change, 2)
                r['chg_pct'] = round(change / prev * 100, 2) if prev > 0 else None
            else:
                r['chg'] = None
                r['chg_pct'] = None
            updated += 1
        else:
            missing.append(r['code'])
        p, e, c, fair = r.get('price'), r.get('est_dividend'), r.get('cheap_price'), r.get('fair_price')
        if p and e is not None and c is not None and fair is not None and e > 0:
            r['yield_pct'] = round(e / p * 100, 2)
            if r['yield_pct'] > REVIEW_YIELD:
                r['valuation_zone'] = 'review'
                r['review_reason'] = 'high_yield'
            else:
                r['valuation_zone'] = 'cheap' if p <= c else ('fair' if p <= fair else 'expensive')
                r['review_reason'] = None
        zones[r.get('valuation_zone')] = zones.get(r.get('valuation_zone'), 0) + 1

    with open(a.out_stocks, 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, separators=(',', ':'))
    meta = {'price_date': data_date, 'updated_count': updated, 'missing_count': len(missing)}
    with open(a.out_meta, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)

    print(f'已更新 {updated} / {len(stocks)} 檔股價;找不到報價 {len(missing)} 檔(多為停牌或已下市)')
    if missing:
        print('找不到報價(前 20):', ', '.join(missing[:20]))
    print(f"評價分布:便宜 {zones['cheap']}、合理 {zones['fair']}、昂貴 {zones['expensive']}、待覆核 {zones['review']}、無資料 {zones[None]}")
    if updated < len(stocks) * 0.8:
        print('錯誤:更新比例低於 80%,不發布。')
        sys.exit(1)


if __name__ == '__main__':
    main()
