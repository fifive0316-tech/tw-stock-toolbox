#!/usr/bin/env python3
"""股利估價雷達 合併後校正:股本變動換算 + 去年年度EPS + 重算 Q4 與估值

用法(每次 CSV / 估價表合併改過 stocks.json 的 EPS 之後都要跑一次;可重複執行,結果相同):
  python3 -I post_merge_fix.py --stocks stocks.json --twse-inc twse_inc.json --tpex-inc tpex_inc.json \
      --period 115Q3 --out stocks.out.json

twse_inc.json = https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci        (上市綜合損益表,欄位「基本每股盈餘(元)」是年初至當季累計)
tpex_inc.json = https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci     (上櫃)

為什麼需要:選股網站匯出的單季 EPS 是「當時公告」的數字。公司今年如果做了股票分割、配發股票股利或減資,
Q3 之後的 EPS 與股價是新股本,Q1、Q2 與去年的 EPS 還是舊股本,直接相加會把今年 EPS 高估或低估
(例:6669 緯穎 2026 年分割,Q1+Q2+Q3 相加 197.84,官方前三季累計只有 94.04)。

做法:
 A. 股本變動換算(只在官方資料的期別等於 --period、且該股 Q3 已是實際值時判斷):
    h1 = Q1+Q2,cum = 官方前三季累計 EPS,diff = cum − (h1 + Q3)
    條件:h1 ≥ 0.5、cum − Q3 > 0、|diff| > 0.1 且 |diff| > 5% × max(|cum|, |h1+Q3|)、
          k = (cum − Q3) ÷ h1 落在 0.05~2.5
    符合 → Q1、Q2、去年同季(q3_last_year)、去年EPS、last4_eps 的 25Q4/26Q1/26Q2、eps_hist 全部 × k,
    並記錄 share_adj = {"k":…, "cum":…, "orig": {換算前的原值}}。虧損或上半年獲利太小的公司不換算(k 不可靠)。
    重跑時會先用 share_adj.orig 還原再重新判斷;若某欄位已被新的合併覆寫成公告值(不等於「原值×k」),保留新值。
 B. 去年EPS:有 eps_last_year_annual(merge_xlsx.py 從估價表寫入的官方年度EPS)就用它,否則沿用原本的四季加總;
    有換算的個股再 × k。
 C. 所有個股依 CSV更新流程 的公式重算 Q4(三候選值中位數)、今年EPS、年增率、一次性標示、
    預估股利、便宜價/合理價、殖利率與分區(分區規則與 update_prices.py 相同)。

結束代碼:0 = 完成;1 = 來源筆數過少或格式不符。
"""
import argparse, json, statistics, sys

REVIEW_YIELD = 12.0
H1_MIN, DIFF_ABS, DIFF_REL, K_MIN, K_MAX = 0.5, 0.1, 0.05, 0.05, 2.5
THIS_YEAR = '26'      # last4_eps / rev_this_year 的年份前綴;跨年度時要改
PREV_Q4 = '25Q4'


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(',', '')
    if s in ('', '--', '-', 'N/A'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def calc_q4(s, q3, c_last_year):
    q1, q2 = s.get('q1'), s.get('q2')
    if q1 is None or q2 is None or q3 is None:
        return None, None
    rm = {x['m']: x['rev'] for x in (s.get('rev_this_year') or [])}
    octs = [rm.get(THIS_YEAR + 'M%02d' % m) for m in (10, 11, 12)]
    octs = [v for v in octs if v is not None]
    oct_avg = sum(octs) / len(octs) if octs else None
    q3m = [rm.get(THIS_YEAR + 'M%02d' % m) for m in (7, 8, 9)]
    q3_ok = all(v is not None for v in q3m) and sum(q3m) > 0
    a = q3 if (q3 <= 0 or oct_avg is None or not q3_ok) else q3 * clamp(oct_avg / (sum(q3m) / 3), 0.7, 1.3)
    avg3 = (q1 + q2 + q3) / 3
    ytd = [rm.get(THIS_YEAR + 'M%02d' % m) for m in range(1, 10)]
    ytd_ok = all(v is not None for v in ytd) and sum(ytd) > 0
    b = avg3 if (avg3 <= 0 or oct_avg is None or not ytd_ok) else avg3 * clamp(oct_avg / (sum(ytd) / 9), 0.7, 1.3)
    cands = [a, b] + ([c_last_year] if c_last_year is not None else [])
    return round(statistics.median(cands), 2), {'q3_rev': round(a, 2), 'ytd_rev': round(b, 2), 'last_year': c_last_year}


def finish(s):
    q = [s.get('q1'), s.get('q2'), s.get('q3'), s.get('q4')]
    s['eps_this_year'] = round(sum(q), 2) if all(v is not None for v in q) else None
    e, last = s['eps_this_year'], s.get('eps_last_year')
    s['eps_yoy_pct'] = round((e - last) / abs(last) * 100, 1) if (e is not None and last not in (None, 0)) else None
    reasons, yoy, ry = [], s['eps_yoy_pct'], s.get('rev_yoy_pct')
    if e is not None and e > 0 and last is not None:
        if last <= 0:
            reasons.append('turnaround')
        if 0 < last < 0.5 and yoy is not None and yoy >= 100:
            reasons.append('low_base')
        if last > 0 and yoy is not None and yoy >= 50 and ry is not None and yoy > 3 * max(ry, 10):
            reasons.append('eps_rev_gap')
    s['oneoff_reasons'], s['oneoff_warning'] = reasons, bool(reasons)
    pm = s.get('payout_median3')
    s['payout_used'] = min(pm, 100) if pm is not None else None
    s['payout_capped'] = pm is not None and pm > 100
    est = cheap = fair = yld = zone = reason = review = None
    if e is not None and e <= 0:
        reason = 'loss_this_year'
    elif e is not None:
        if pm is None or pm <= 0:
            reason = 'non_positive_estimate'
        else:
            est = round(e * s['payout_used'] / 100, 2)
            if est <= 0:
                est, reason = None, 'non_positive_estimate'
    if est is not None:
        cheap, fair = round(est * 16.5, 2), round(est * 20, 2)
        p = s.get('price')
        if p:
            yld = round(est / p * 100, 2)
            if yld > REVIEW_YIELD:
                zone, review = 'review', 'high_yield'
            else:
                zone = 'cheap' if p <= cheap else ('fair' if p <= fair else 'expensive')
    s.update(est_dividend=est, cheap_price=cheap, fair_price=fair, yield_pct=yld,
             valuation_zone=zone, review_reason=review, no_est_reason=reason)


def sc(v, k):
    return None if v is None else round(v * k, 2)


def restore(s):
    """把上一次換算過的欄位還原成公告值;已被新合併覆寫的欄位(≠ 原值×k)保留現值"""
    adj = s.pop('share_adj', None)
    if not adj:
        return
    k, o = adj['k'], adj['orig']
    for f in ('q1', 'q2', 'q3_last_year', 'eps_last_year'):
        if f in o and s.get(f) == sc(o[f], k):
            s[f] = o[f]
    for x in s.get('last4_eps') or []:
        ov = (o.get('l4') or {}).get(x['q'])
        if ov is not None and x['eps'] == sc(ov, k):
            x['eps'] = ov
    oh = o.get('eps_hist')
    if oh and s.get('eps_hist') and len(oh) == len(s['eps_hist']):
        for cur, orig in zip(s['eps_hist'], oh):
            if cur[0] == orig[0] and cur[1] == sc(orig[1], k):
                cur[1] = orig[1]


def main():
    ap = argparse.ArgumentParser()
    for k in ('stocks', 'twse-inc', 'tpex-inc', 'period', 'out'):
        ap.add_argument('--' + k, required=True)
    a = ap.parse_args()
    try:
        yr, season = a.period.split('Q')
        int(yr), int(season)
    except ValueError:
        print('錯誤:--period 格式應為 115Q3'); sys.exit(1)
    if season != '3':
        print('錯誤:目前只支援第 3 季(前三季累計)'); sys.exit(1)

    cum = {}
    for path, ck, yk, sk in ((a.twse_inc, '公司代號', '年度', '季別'), (a.tpex_inc, 'SecuritiesCompanyCode', 'Year', 'Season')):
        with open(path, encoding='utf-8') as f:
            for r in json.load(f):
                code = str(r.get(ck, '')).strip()
                if code and str(r.get(yk, '')).strip() == yr and str(r.get(sk, '')).strip() == season:
                    v = num(r.get('基本每股盈餘（元）'))
                    if v is not None:
                        cum[code] = v
    print(f'官方 {a.period} 累計EPS:{len(cum)} 檔')
    if len(cum) < 1000:
        print('錯誤:官方資料筆數過少(期別不符或抓取失敗),不處理。'); sys.exit(1)

    with open(a.stocks, encoding='utf-8') as f:
        stocks = json.load(f)

    adjusted, annual_used = [], 0
    for s in stocks:
        restore(s)
        base_last = s.get('eps_last_year')
        if s.get('eps_last_year_annual') is not None:
            base_last = s['eps_last_year_annual']
            annual_used += 1
        s['eps_last_year'] = base_last

        q1, q2, q3, c = s.get('q1'), s.get('q2'), s.get('q3'), cum.get(s['code'])
        if s.get('q3_source') == 'actual' and None not in (q1, q2, q3) and c is not None:
            h1, tot = q1 + q2, q1 + q2 + q3
            diff, rest = c - tot, c - q3
            if h1 >= H1_MIN and rest > 0 and abs(diff) > DIFF_ABS and abs(diff) > DIFF_REL * max(abs(c), abs(tot)):
                k = round(rest / h1, 4)     # 存檔與換算用同一個四捨五入後的 k,重跑時才還原得回來
                if K_MIN <= k <= K_MAX:
                    l4 = {x['q']: x['eps'] for x in (s.get('last4_eps') or []) if x['q'] != THIS_YEAR + 'Q3'}
                    orig = {'q1': q1, 'q2': q2, 'q3_last_year': s.get('q3_last_year'), 'eps_last_year': base_last,
                            'l4': l4, 'eps_hist': [list(x) for x in (s.get('eps_hist') or [])]}
                    s['q1'], s['q2'] = sc(q1, k), sc(q2, k)
                    s['q3_last_year'] = sc(s.get('q3_last_year'), k)
                    s['eps_last_year'] = sc(base_last, k)
                    for x in s.get('last4_eps') or []:
                        if x['q'] != THIS_YEAR + 'Q3':
                            x['eps'] = sc(x['eps'], k)
                    for x in s.get('eps_hist') or []:
                        x[1] = sc(x[1], k)
                    s['share_adj'] = {'k': k, 'cum': c, 'orig': orig}
                    adjusted.append((s['code'], s['name'], round(k, 3)))

        c4 = next((x['eps'] for x in (s.get('last4_eps') or []) if x['q'] == PREV_Q4), None)
        q4, cand = calc_q4(s, s.get('q3'), c4)
        s['q4'], s['q4_candidates'] = q4, cand
        s['q4_source'] = 'estimated_median' if q4 is not None else None
        finish(s)

    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, separators=(',', ':'))
    zones = {}
    for s in stocks:
        zones[s['valuation_zone']] = zones.get(s['valuation_zone'], 0) + 1
    print(f'去年EPS改用年度數字 {annual_used} 檔;股本變動換算 {len(adjusted)} 檔')
    print('換算名單(代號 名稱 k):', '、'.join(f'{c} {n} {k}' for c, n, k in sorted(adjusted, key=lambda x: x[2])))
    print(f"評價分布:便宜 {zones.get('cheap', 0)}、合理 {zones.get('fair', 0)}、昂貴 {zones.get('expensive', 0)}、待覆核 {zones.get('review', 0)}、無資料 {zones.get(None, 0)}")


if __name__ == '__main__':
    main()
