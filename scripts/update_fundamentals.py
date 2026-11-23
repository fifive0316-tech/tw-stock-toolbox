#!/usr/bin/env python3
"""股利估價雷達 財報品質指標(ROE / 毛利率 / 營業利益率 / 負債比)

用法:
  python3 -I update_fundamentals.py --twse-inc twse_inc.json --twse-bal twse_bal.json \
      --tpex-inc tpex_inc.json --tpex-bal tpex_bal.json --current fundamentals.json --out fundamentals.new.json

--current 給線上目前的 fundamentals.json(每日排程一定要給)。開放資料只放「已申報最新一期」的公司:
新一季申報期剛開始時,資料集會縮到只剩已申報的幾十家,所以不能直接覆蓋,要逐檔合併:
  - 這次下載有、而且期別不比線上舊 → 用新的;
  - 這次下載沒有的代號 → 保留線上原本那一筆(上一期的數字)。
沒給 --current 視為第一次建立,此時來源筆數太少會直接報錯。

來源(官方開放資料,只有「最新一期」的累計數字,一般業格式):
  twse_inc.json = https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci          上市 綜合損益表
  twse_bal.json = https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci          上市 資產負債表
  tpex_inc.json = https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci       上櫃 綜合損益表
  tpex_bal.json = https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ci       上櫃 資產負債表
金控、銀行、保險、證券的報表格式不同(_fh/_basi/_ins/_bd),這支腳本不處理,頁面會顯示「—」。

輸出 fundamentals.json:
  {"asof": "YYYYMMDD", "period": "115Q3",
   "stocks": {"2330": {"p": "115Q3", "roe": 38.9, "gm": 66.8, "opm": 59.0, "debt": 29.9}, ...}}
  roe  = 歸屬母公司淨利(年初至當季累計) ÷ 歸屬母公司權益(期末) × (4 ÷ 季別) × 100   ← 年化,非四季滾動
  gm   = 營業毛利 ÷ 營業收入 × 100(累計)
  opm  = 營業利益 ÷ 營業收入 × 100(累計)
  debt = 負債總計 ÷ 資產總計 × 100(期末)
  算不出來的項目為 null(例如營收為 0、權益為負)。period 是最多公司所屬的期別,p 是個股自己的期別。

結束代碼:0 = 已產生,內容有變動,應發布;2 = 與線上內容相同(沒有新申報),不需要發布;
1 = 來源格式不符、讀不到檔案,或沒給 --current 時筆數過少,不應發布。
"""
import argparse, json, sys, datetime
from collections import Counter


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


def first(r, keys):
    for k in keys:
        if k in r:
            v = num(r[k])
            if v is not None:
                return v
    return None


def text(r, keys):
    for k in keys:
        if k in r and str(r[k]).strip():
            return str(r[k]).strip()
    return ''


CODE = ['公司代號', 'SecuritiesCompanyCode']
YEAR = ['年度', 'Year']
SEASON = ['季別', 'Season']


def load(path):
    with open(path, encoding='utf-8') as f:
        rows = json.load(f)
    return [r for r in rows if text(r, CODE)]


def main():
    ap = argparse.ArgumentParser()
    for k in ('twse-inc', 'twse-bal', 'tpex-inc', 'tpex-bal', 'out'):
        ap.add_argument('--' + k, required=True)
    ap.add_argument('--current', help='線上目前的 fundamentals.json;給了就逐檔合併,不會讓資料變少')
    a = ap.parse_args()

    current = None
    if a.current:
        try:
            with open(a.current, encoding='utf-8') as f:
                current = json.load(f)
            if not isinstance(current.get('stocks'), dict):
                raise ValueError('沒有 stocks 欄位')
        except (OSError, ValueError, AttributeError) as e:
            print(f'錯誤:讀不到線上的 fundamentals.json({e}),不發布。')
            sys.exit(1)

    inc_rows = load(a.twse_inc) + load(a.tpex_inc)
    bal_rows = load(a.twse_bal) + load(a.tpex_bal)
    print(f'損益表 {len(inc_rows)} 筆、資產負債表 {len(bal_rows)} 筆')
    if current is None and (len(inc_rows) < 1000 or len(bal_rows) < 1000):
        print('錯誤:來源筆數過少,可能抓取失敗或欄位名稱改了,不發布。')
        sys.exit(1)
    if current is not None and (not inc_rows or not bal_rows):
        print('錯誤:來源沒有任何帶公司代號的資料(抓取失敗或欄位名稱改了),不發布。')
        sys.exit(1)

    bal = {}
    for r in bal_rows:
        bal[text(r, CODE)] = {
            'p': text(r, YEAR) + 'Q' + text(r, SEASON),
            'assets': first(r, ['資產總計', '資產總額']),
            'liab': first(r, ['負債總計', '負債總額']),
            'equity': first(r, ['歸屬於母公司業主之權益合計', '歸屬於母公司業主權益合計', '歸屬於母公司業主之權益']),
        }

    def pkey(p):
        """'115Q3' → (115, 3);格式不符回傳 (0, 0)"""
        try:
            y, q = str(p).split('Q')
            return int(y), int(q)
        except ValueError:
            return 0, 0

    out = {}
    for r in inc_rows:
        code = text(r, CODE)
        try:
            season = int(text(r, SEASON))
        except ValueError:
            continue
        if season not in (1, 2, 3, 4):
            continue
        p = text(r, YEAR) + 'Q' + str(season)
        rev = first(r, ['營業收入'])
        gp = first(r, ['營業毛利（毛損）淨額', '營業毛利（毛損）'])
        op = first(r, ['營業利益（損失）'])
        ni = first(r, ['淨利（淨損）歸屬於母公司業主', '淨利（損）歸屬於母公司業主'])
        b = bal.get(code)
        if b and b['p'] != p:   # 兩張表期別不同就不混用
            b = None
        rec = {'p': p, 'roe': None, 'gm': None, 'opm': None, 'debt': None}
        if rev and rev > 0:
            if gp is not None:
                rec['gm'] = round(gp / rev * 100, 1)
            if op is not None:
                rec['opm'] = round(op / rev * 100, 1)
        if b:
            if ni is not None and b['equity'] and b['equity'] > 0:
                rec['roe'] = round(ni / b['equity'] * (4 / season) * 100, 1)
            if b['assets'] and b['assets'] > 0 and b['liab'] is not None:
                rec['debt'] = round(b['liab'] / b['assets'] * 100, 1)
        out[code] = rec

    if not out:
        print('錯誤:沒有任何可用的期別(欄位名稱可能改了),不發布。')
        sys.exit(1)
    fresh = Counter(v['p'] for v in out.values())
    print(f'這次下載可用 {len(out)} 檔;期別分布 {dict(fresh)}')

    if current is not None:
        merged, newer, added, kept = dict(current['stocks']), 0, 0, 0
        for code, rec in out.items():
            old = merged.get(code)
            if old is None:
                merged[code] = rec
                added += 1
            elif pkey(rec['p']) >= pkey(old.get('p')):
                if rec != old:
                    newer += 1
                merged[code] = rec
            else:
                kept += 1      # 線上那筆期別比較新(不應發生),保留線上的
        carried = sum(1 for c in merged if c not in out)
        print(f'合併:新增 {added} 檔、更新 {newer} 檔、沿用線上舊資料 {carried} 檔' + (f'、來源期別較舊而略過 {kept} 檔' if kept else ''))
        if merged == current['stocks']:
            print('與線上內容相同(沒有新的申報資料),不需要發布。')
            sys.exit(2)
        out = merged

    periods = Counter(v['p'] for v in out.values())
    period = periods.most_common(1)[0][0]
    full = sum(1 for v in out.values() if all(v[k] is not None for k in ('roe', 'gm', 'opm', 'debt')))
    asof = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime('%Y%m%d')
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump({'asof': asof, 'period': period, 'stocks': out}, f, ensure_ascii=False, separators=(',', ':'))
    print(f'已產生 {len(out)} 檔;期別分布 {dict(periods)};四項都算得出來的有 {full} 檔;抓取日 {asof}')


if __name__ == '__main__':
    main()
