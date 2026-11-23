"""把使用者「個股評價與快速估算表」xlsx 的估價快照寫進趨勢雷達 data.json 的 val 欄位。
用法: python3 -I merge_val2.py <xlsx> <data.json> <out.json> <asof YYYYMMDD>
欄位依表頭文字找（去掉開頭日期），不依固定欄號。
"""
import json, re, sys
import openpyxl

XLSX, DATA, OUT, ASOF = sys.argv[1:5]

wb = openpyxl.load_workbook(XLSX, data_only=True, read_only=True)

def norm(h):
    h = str(h or '').replace('\n', '').strip()
    h = re.sub(r'^\d{6,8}', '', h)          # 去掉開頭 20261116 / 202611 之類的日期
    return h

ws = wb['三大估價法與PEG']
hdr = [norm(x) for x in list(ws.iter_rows(min_row=3, max_row=3, values_only=True))[0]]

def col(pattern, nth=0):
    hits = [i for i, h in enumerate(hdr) if re.search(pattern, h)]
    if len(hits) <= nth:
        raise SystemExit(f'找不到欄位: {pattern}')
    return hits[nth]

C = {
    'pe': col(r'^交易所公告本益比$'),
    'pb': col(r'^股價淨值比$'),
    'mcap': col(r'^總市值\(億\)$'),
    'close': col(r'^收盤價$'),
    'beta': col(r'^Beta係數\(250D\)$'),
    'bvps': col(r'公告每股淨值'),
    'inst_eps': col(r'^機構估稅後EPS\(元\)$'),
    'inst_eps_next': col(r'^明年機構估稅後EPS$'),
    'inst_eps_growth': col(r'^預估年稅後EPS成長\(%\)$'),
    'combo': col(r'^綜合估價$'),
    'pe_low_price': col(r'^本益比法計算\(最低本益比\)$'),
    'pe_med_price': col(r'^本益比法計算\(中位數\)$'),
    'k_price': col(r'^K值法計算'),
    'yield_price': col(r'^殖利率法計算'),
    'roe4': col(r'^近四季ROE$'),
    'payout5': col(r'^近五年平均現金發放率$'),
    'est_cash_div': col(r'^預估現金股利$'),
    'dy': col(r'^交易所公告殖利率$'),
    'yield5': col(r'^近五年平均現金殖利率$'),
    'pe_hi5': col(r'最高:本益比$'),
    'pe_lo5': col(r'最低:本益比$'),
    'pe_med5': col(r'^近五年中位本益比'),
    'peg': col(r'^PEG$'),
    'cagr5': col(r'^年複合成長率$'),
    'cash_ratio': col(r'^獲利含金率'),
    'ocf': col(r'^營運現金流量\(億'),
    'ni4': col(r'^近四季稅後淨利（億'),
    'opm_q': col(r'^營益率'),
    'debt_q': col(r'^負債率'),
    'vol1y': col(r'近一年歷史波動率'),
}
note_cols = [i for i, h in enumerate(hdr) if re.match(r'^備註$', h)]
rev_note_col = note_cols[-1] if note_cols else None   # 最新一個月的營收備註

def num(v, zero_null=True, pos_only=False):
    if v is None or isinstance(v, str) or isinstance(v, bool):
        return None
    try:
        v = float(v)
    except Exception:
        return None
    if v != v:
        return None
    if zero_null and v == 0:
        return None
    if pos_only and v <= 0:
        return None
    return v

def rnd(v, d=2):
    return None if v is None else round(v, d)

# 外資持股比
dash = wb['儀表板數據區']
dh = [norm(x) for x in list(dash.iter_rows(min_row=2, max_row=2, values_only=True))[0]]
c_code = dh.index('股票代號')
c_fp = dh.index('外資持股比率(%)')
foreign = {}
for row in dash.iter_rows(min_row=3, values_only=True):
    if row[c_code]:
        foreign[str(row[c_code])] = num(row[c_fp], zero_null=False)

with open(DATA, encoding='utf-8') as f:
    data = json.load(f)

updated, missing = 0, []
for row in ws.iter_rows(min_row=4, values_only=True):
    code = row[0]
    if not code:
        continue
    code = str(code)
    key = 'TWSE_' + code if 'TWSE_' + code in data else ('TPEX_' + code if 'TPEX_' + code in data else None)
    if not key:
        missing.append(code)
        continue
    g = lambda k, **kw: num(row[C[k]], **kw)
    close = g('close', pos_only=True)
    mcap = g('mcap', pos_only=True)
    market_cap = mcap * 1e8 if mcap else None
    note = row[rev_note_col] if rev_note_col is not None else None
    note = note.strip() if isinstance(note, str) and note.strip() not in ('', '無', '無。', '0') else None
    data[key]['val'] = {
        'pe': rnd(g('pe')), 'pb': rnd(g('pb')), 'dividend_yield': rnd(g('dy')),
        'market_cap': market_cap,
        'shares_outstanding': (market_cap / close) if (market_cap and close) else None,
        'foreign_pct': foreign.get(code),
        'asof': ASOF,
        'snap_close': close,
        'bvps': rnd(g('bvps')),
        'combo': rnd(g('combo', pos_only=True)),
        'pe_low_price': rnd(g('pe_low_price', pos_only=True)),
        'pe_med_price': rnd(g('pe_med_price', pos_only=True)),
        'k_price': rnd(g('k_price', pos_only=True)),
        'yield_price': rnd(g('yield_price', pos_only=True)),
        'inst_eps': rnd(g('inst_eps')), 'inst_eps_next': rnd(g('inst_eps_next')),
        'inst_eps_growth': rnd(g('inst_eps_growth'), 1),
        'roe4': rnd(g('roe4', zero_null=False)), 'payout5': rnd(g('payout5'), 1),
        'est_cash_div': rnd(g('est_cash_div')), 'yield5': rnd(g('yield5')),
        'pe_hi5': rnd(g('pe_hi5')), 'pe_lo5': rnd(g('pe_lo5')), 'pe_med5': rnd(g('pe_med5')),
        'peg': rnd(g('peg')), 'cagr5': rnd(None if g('cagr5', zero_null=False) is None else g('cagr5', zero_null=False) * 100, 1),
        'cash_ratio': rnd(g('cash_ratio', zero_null=False)), 'ocf': rnd(g('ocf')), 'ni4': rnd(g('ni4')),
        'opm_q': rnd(g('opm_q', zero_null=False)), 'debt_q': rnd(g('debt_q')),
        'beta': rnd(g('beta', zero_null=False), 3), 'vol1y': rnd(g('vol1y')),
        'rev_note': note,
    }
    updated += 1

print('columns', {k: hdr[v] for k, v in C.items()})
print('rev_note column', hdr[rev_note_col] if rev_note_col is not None else None, rev_note_col)
print('updated', updated, 'missing', len(missing), missing[:15])
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('saved', OUT)
