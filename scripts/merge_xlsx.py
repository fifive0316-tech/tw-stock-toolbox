#!/usr/bin/env python3
"""股利估價雷達 用使用者的估價表 xlsx(個股評價與快速估算表)補資料

用法:
  python3 -I merge_xlsx.py --xlsx <估價表.xlsx> --year 2026 --quarter 3 \
      --stocks stocks.json --fundamentals fundamentals.json --industry industry.json \
      --out-stocks stocks.x.json --out-fundamentals fundamentals.x.json

只做三件事,其餘欄位不動(股價、Q1/Q2、月營收、配息率都不碰):
 1. 當季 EPS:stocks.json 裡當季仍是推估值的個股,若估價表已有公告數字,換成實際值。
    判斷「已公告」:<年>Q<季>公告基本每股盈餘 與 <年>Q<季>稅後權益報酬率 不同時為 0/空白
    (尚未申報的公司兩欄都是 0)。目前只支援第 3 季(q3 欄位)。
 2. eps_last_year_annual:估價表的「<去年>每股盈餘(元)」(官方年度EPS),0 或空白視為沒有資料。
    之後由 post_merge_fix.py 用它取代「去年四季加總」。
 3. fundamentals.json 缺的個股(官方開放資料沒有的,例如金融業與尚未收錄的公司)用估價表補,
    並標 "src": "x":
      roe  = 近四季ROE(注意:官方來源那些是「當年累計年化」,定義不同)
      gm   = <年>Q<季>毛利率(單季;官方來源是累計)
      opm  = <年>Q<季>營業利益率(單季)
      debt = 負債率(季)(與官方算法相同)
    金融保險業只補 roe(毛利率、營益率、負債比對金融業沒有比較意義)。
    已經有官方資料的個股不動;之後官方資料收錄了,update_fundamentals.py 會自動用官方數字蓋掉。

欄位用表頭文字找(忽略空白與換行),找不到就報錯結束。結束代碼:0 = 完成;1 = 錯誤。
"""
import argparse, json, re, sys

try:
    import openpyxl
except ImportError:
    print('錯誤:需要 openpyxl(pip install openpyxl --break-system-packages)'); sys.exit(1)


def num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(',', '').strip())
    except ValueError:
        return None


def norm(h):
    return re.sub(r'\s+', '', str(h)) if h is not None else ''


def load_sheet(wb, name, header_row):
    if name not in wb.sheetnames:
        print(f'錯誤:找不到分頁「{name}」'); sys.exit(1)
    rows = [list(r) for r in wb[name].iter_rows(values_only=True)]
    return [norm(h) for h in rows[header_row - 1]], rows[header_row:]


def col(headers, text, sheet, start=0):
    t = norm(text)
    for i, h in enumerate(headers):
        if i >= start and h == t:
            return i
    print(f'錯誤:分頁「{sheet}」找不到欄位「{text}」'); sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xlsx', required=True)
    ap.add_argument('--year', type=int, required=True)
    ap.add_argument('--quarter', type=int, required=True)
    for k in ('stocks', 'fundamentals', 'industry', 'out-stocks', 'out-fundamentals'):
        ap.add_argument('--' + k, required=True)
    a = ap.parse_args()
    if a.quarter != 3:
        print('錯誤:目前只支援第 3 季'); sys.exit(1)
    Y, Q = a.year, a.quarter
    yq = f'{Y}Q{Q}'

    wb = openpyxl.load_workbook(a.xlsx, read_only=True, data_only=True)
    S1, S2 = '三大估價法與PEG', '儀表板數據區'
    h1, r1 = load_sheet(wb, S1, 3)
    h2, r2 = load_sheet(wb, S2, 2)
    c_code = col(h1, '股票代號', S1)
    c_eps = col(h1, f'{yq}公告基本每股盈餘(元)', S1)
    c_roeq = col(h1, f'{yq}稅後權益報酬率(%)', S1)
    c_ann = col(h1, f'{Y - 1}每股盈餘(元)', S1)
    c_roe4 = col(h1, '近四季ROE', S1)
    c_debt = col(h1, '負債率(%)（季）', S1)
    d_code = col(h2, '股票代號', S2)
    # 這個分頁左邊是單一個股的儀表板顯示區,表頭文字會重複;全市場資料在「股票代號」欄之後
    d_gm = col(h2, f'{yq}毛利率(%)', S2, d_code)
    d_opm = col(h2, f'{yq}營業利益率(%)', S2, d_code)

    def key(v):
        return str(v).strip() if v not in (None, '') else None

    xa = {key(r[c_code]): r for r in r1 if r and len(r) > c_debt and key(r[c_code])}
    xb = {key(r[d_code]): r for r in r2 if r and len(r) > d_opm and key(r[d_code])}
    print(f'估價表:{S1} {len(xa)} 檔、{S2} {len(xb)} 檔')
    if len(xa) < 1000:
        print('錯誤:估價表筆數過少,不處理。'); sys.exit(1)

    with open(a.stocks, encoding='utf-8') as f:
        stocks = json.load(f)
    with open(a.fundamentals, encoding='utf-8') as f:
        fund = json.load(f)
    with open(a.industry, encoding='utf-8') as f:
        ind = json.load(f).get('map', {})

    def reported(r):
        e, ro = num(r[c_eps]), num(r[c_roeq])
        return (e not in (None, 0)) or (ro not in (None, 0))

    filled, annual, not_rep, absent = 0, 0, [], []
    for s in stocks:
        r = xa.get(s['code'])
        if not r:
            if s.get('q3_source') != 'actual':
                absent.append(s['code'])
            continue
        v = num(r[c_ann])
        if v not in (None, 0):
            s['eps_last_year_annual'] = v
            annual += 1
        if s.get('q3_source') != 'actual':
            e = num(r[c_eps])
            if e is not None and reported(r):
                s['q3'] = e
                s['q3_source'] = 'actual'
                s['q3_candidates'] = None
                s['data_confidence'] = 'high'
                s['last4_eps'] = [x for x in s.get('last4_eps', []) if x['q'] != f'{Y % 100}Q{Q}'] + [{'q': f'{Y % 100}Q{Q}', 'eps': e}]
                filled += 1
            else:
                not_rep.append(s['code'])
    print(f'當季EPS:{filled} 檔由推估換成實際;估價表顯示尚未申報 {len(not_rep)} 檔;估價表沒有這檔 {len(absent)} 檔')
    print(f'去年年度EPS(eps_last_year_annual):{annual} 檔')

    p_now, p_prev = f'{Y - 1911}Q{Q}', f'{Y - 1911}Q{Q - 1}'
    fs, add_full, add_fin = fund['stocks'], 0, 0
    for s in stocks:
        c = s['code']
        if c in fs and fs[c].get('src') != 'x':
            continue                      # 已有官方資料,不動
        r, rb = xa.get(c), xb.get(c)
        if not r:
            continue

        def nz(v):
            v = num(v)
            return round(v, 1) if v not in (None, 0) else None
        rec = {'p': p_now if reported(r) else p_prev, 'roe': nz(r[c_roe4]), 'gm': None, 'opm': None, 'debt': None, 'src': 'x'}
        if ind.get(c) != '金融保險':
            rec['gm'] = nz(rb[d_gm]) if rb else None
            rec['opm'] = nz(rb[d_opm]) if rb else None
            rec['debt'] = nz(r[c_debt])
            add_full += 1
        else:
            add_fin += 1
        if all(rec[k] is None for k in ('roe', 'gm', 'opm', 'debt')):
            continue
        fs[c] = rec
    print(f'財報指標補值:一般業 {add_full} 檔(四項)、金融保險 {add_fin} 檔(只補 ROE);fundamentals 共 {len(fs)} 檔')

    with open(a.out_stocks, 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, separators=(',', ':'))
    with open(a.out_fundamentals, 'w', encoding='utf-8') as f:
        json.dump(fund, f, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main()
