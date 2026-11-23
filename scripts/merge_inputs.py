#!/usr/bin/env python3
"""把 inputs/ 資料夾裡你上傳的檔案合併進兩個雷達(GitHub Actions 在你上傳檔案後自動執行)

用法(在專案最上層資料夾執行):
  python3 scripts/merge_inputs.py

認得的檔案(依內容判斷,檔名不拘):
  1. 估價表 xlsx(「個股評價與快速估算表」,含「三大估價法與PEG」分頁)
       → 股利估價雷達:補當季實際 EPS、去年年度 EPS、缺的財報指標(merge_xlsx.py)
       → 趨勢雷達:更新三大估價法快照 val(merge_val_xlsx.py)
  2. EPS CSV:「財報快照」格式(有「財報季度」「EPS(元)」欄)或逐季格式(有「26Q3EPS(元)」欄)
       → 第 3 季已公告的個股,Q3 換成實際值
  3. 股利分配率 CSV(有「2026分配率」這類欄位)→ 更新逐年配息率、近三年中位數/平均
  月營收 CSV 不需要上傳:每日排程會自動從官方開放資料更新。
合併後一律執行 post_merge_fix.py(股本變動換算、去年年度EPS、重算 Q4 與估值)。
處理完的檔案會從 inputs/ 刪除(工作流程負責提交),處理紀錄寫在 inputs/處理紀錄.txt。

⚠ 年度設定:目前公式針對 2026 年(Q1~Q3 實際、Q4 推估、前三季累計 115Q3)。
   2027 年第一季財報出來前要更新 YEAR、QUARTER、post_merge_fix.py 與 update_div_revenue.py 的年度常數。
結束代碼:0 = 有合併;2 = 沒有可處理的檔案;1 = 有錯誤。
"""
import csv, datetime, glob, io, json, os, re, shutil, statistics, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SC = os.path.join(ROOT, 'scripts')
DIV = os.path.join(ROOT, 'site', 'dividend')
TR = os.path.join(ROOT, 'site', 'trend')
INP = os.path.join(ROOT, 'inputs')
WORK = os.path.join(ROOT, 'work_inputs')
YEAR, QUARTER = 2026, 3          # ← 目前合併的「當季」
FIN_PERIOD = f'{YEAR - 1911}Q{QUARTER}'
QKEY = f'{YEAR % 100}Q{QUARTER}'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
TPE = datetime.timezone(datetime.timedelta(hours=8))
log = []


def num(v):
    s = str(v if v is not None else '').replace(',', '').replace('+', '').strip()
    if s in ('', '-', '--', 'N/A'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def read_csv(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp950', 'big5'):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(enc))))
        except UnicodeDecodeError:
            continue
    raise ValueError('無法辨識 CSV 編碼(請用 UTF-8 或 Big5 匯出)')


def run(args):
    p = subprocess.run([sys.executable, '-I'] + args, cwd=ROOT, capture_output=True, text=True)
    out = (p.stdout or '') + (p.stderr or '')
    print(out.rstrip(), flush=True)
    return p.returncode, out


def download(url, path):
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            json.loads(data.decode('utf-8'))
            open(path, 'wb').write(data)
            return True
        except Exception as e:      # noqa: BLE001
            print('  下載失敗', url, e)
    return False


def load_stocks():
    with open(os.path.join(DIV, 'stocks.json'), encoding='utf-8') as f:
        return json.load(f)


def save_stocks(stocks):
    with open(os.path.join(DIV, 'stocks.json'), 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, separators=(',', ':'))


def set_q_actual(s, eps):
    s['q3'] = eps
    s['q3_source'] = 'actual'
    s['q3_candidates'] = None
    s['data_confidence'] = 'high'
    s['last4_eps'] = [x for x in (s.get('last4_eps') or []) if x['q'] != QKEY] + [{'q': QKEY, 'eps': eps}]


def merge_eps_csv(rows, name):
    stocks = load_stocks()
    by = {s['code']: s for s in stocks}
    cols = rows[0].keys()
    newly = 0
    if '財報季度' in cols and 'EPS(元)' in cols:
        for r in rows:
            s = by.get(str(r.get('代號', '')).strip())
            if s and str(r.get('財報季度', '')).strip() == QKEY:
                e = num(r.get('EPS(元)'))
                if e is not None:
                    newly += s.get('q3_source') != 'actual'
                    set_q_actual(s, e)
    else:
        col = f'{QKEY}EPS(元)'
        for r in rows:
            s = by.get(str(r.get('代號', '')).strip())
            e = num(r.get(col))
            if s and e is not None:
                newly += s.get('q3_source') != 'actual'
                set_q_actual(s, e)
    save_stocks(stocks)
    msg = f'{name}:EPS 檔,{QKEY} 由推估改為實際 {newly} 檔'
    print(msg); log.append(msg)


def merge_payout_csv(rows, name):
    stocks = load_stocks()
    by = {s['code']: s for s in stocks}
    years = sorted(int(m.group(1)) for c in rows[0].keys() for m in [re.match(r'^(\d{4})分配率$', c.strip())] if m)
    last3 = [str(y) for y in years if y <= YEAR][-3:]
    n = 0
    for r in rows:
        s = by.get(str(r.get('代號', '')).strip())
        if not s:
            continue
        pby = s.setdefault('payout_by_year', {})
        for y in years:
            pby[str(y)] = num(r.get(f'{y}分配率'))
        vals = [(y, pby.get(y)) for y in last3 if pby.get(y) is not None]
        s['payout_years_used'] = [y for y, _ in vals]
        v = [x for _, x in vals]
        s['payout_avg3'] = round(sum(v) / len(v), 2) if v else None
        s['payout_median3'] = round(statistics.median(v), 2) if v else None
        s['high_payout_warning'] = bool(v) and s['payout_avg3'] > 100
        if '平均股利(元)' in r:
            s['avg_div_hist'] = num(r.get('平均股利(元)'))
        if '股利發放頻率' in r:
            s['div_freq'] = str(r.get('股利發放頻率') or '').strip() or s.get('div_freq')
        n += 1
    save_stocks(stocks)
    msg = f'{name}:股利分配率檔,更新 {n} 檔(近三年用 {"、".join(last3)})'
    print(msg); log.append(msg)


def merge_xlsx(path, name):
    tmp_s, tmp_f = os.path.join(WORK, 'stocks.x.json'), os.path.join(WORK, 'fund.x.json')
    code, out = run([os.path.join(SC, 'merge_xlsx.py'), '--xlsx', path, '--year', str(YEAR), '--quarter', str(QUARTER),
                     '--stocks', os.path.join(DIV, 'stocks.json'), '--fundamentals', os.path.join(DIV, 'fundamentals.json'),
                     '--industry', os.path.join(DIV, 'industry.json'), '--out-stocks', tmp_s, '--out-fundamentals', tmp_f])
    if code != 0:
        raise RuntimeError('merge_xlsx.py 失敗')
    shutil.copy(tmp_s, os.path.join(DIV, 'stocks.json'))
    shutil.copy(tmp_f, os.path.join(DIV, 'fundamentals.json'))
    # 趨勢雷達估價快照:日期取表頭「YYYYMMDD收盤價」
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    hdr = [str(x or '') for x in next(wb['三大估價法與PEG'].iter_rows(min_row=3, max_row=3, values_only=True))]
    asof = next((m.group(1) for h in hdr for m in [re.match(r'^(\d{8})收盤價', h)] if m), None)
    if not asof:
        raise RuntimeError('找不到估價表的日期(表頭「YYYYMMDD收盤價」)')
    tmp_d = os.path.join(WORK, 'data.v.json')
    code, out2 = run([os.path.join(SC, 'merge_val_xlsx.py'), path, os.path.join(TR, 'data.json'), tmp_d, asof])
    if code != 0:
        raise RuntimeError('merge_val_xlsx.py 失敗')
    shutil.copy(tmp_d, os.path.join(TR, 'data.json'))
    line = next((l for l in out.splitlines() if l.startswith('當季EPS')), '')
    msg = f'{name}:估價表({asof}),{line};趨勢雷達估價快照已更新'
    print(msg); log.append(msg)


def main():
    files = [p for p in sorted(glob.glob(os.path.join(INP, '*'))) if os.path.isfile(p)
             and not os.path.basename(p).startswith(('.', 'README', '處理紀錄'))]
    if not files:
        print('inputs/ 沒有要處理的檔案'); sys.exit(2)
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    done, failed = [], []
    for p in files:
        name = os.path.basename(p)
        print(f'\n===== {name} =====', flush=True)
        try:
            if name.lower().endswith(('.xlsx', '.xlsm')):
                merge_xlsx(p, name)
            elif name.lower().endswith('.csv'):
                rows = read_csv(p)
                if not rows:
                    raise ValueError('CSV 沒有資料列')
                cols = [c.strip() for c in rows[0].keys()]
                if ('財報季度' in cols and 'EPS(元)' in cols) or f'{QKEY}EPS(元)' in cols:
                    merge_eps_csv(rows, name)
                elif any(re.match(r'^\d{4}分配率$', c) for c in cols):
                    merge_payout_csv(rows, name)
                elif any('營收' in c for c in cols):
                    log.append(f'{name}:月營收檔不需要上傳(每天自動從官方資料更新),略過')
                    print(log[-1])
                else:
                    raise ValueError('認不出這是哪一種 CSV(表頭:' + '、'.join(cols[:8]) + '…)')
            else:
                raise ValueError('只接受 .xlsx 或 .csv')
            done.append(p)
        except Exception as e:      # noqa: BLE001
            failed.append(name)
            log.append(f'{name}:✗ 處理失敗:{e}')
            print(log[-1])

    if done:
        ok = all(download(u, os.path.join(WORK, k)) for k, u in (
            ('twse_inc.json', 'https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci'),
            ('tpex_inc.json', 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci')))
        if ok:
            code, out = run([os.path.join(SC, 'post_merge_fix.py'), '--stocks', os.path.join(DIV, 'stocks.json'),
                             '--twse-inc', os.path.join(WORK, 'twse_inc.json'), '--tpex-inc', os.path.join(WORK, 'tpex_inc.json'),
                             '--period', FIN_PERIOD, '--out', os.path.join(WORK, 'stocks.f.json')])
            if code == 0:
                shutil.copy(os.path.join(WORK, 'stocks.f.json'), os.path.join(DIV, 'stocks.json'))
                log.append('重算估值:' + next((l for l in out.splitlines() if l.startswith('評價分布')), '完成'))
            else:
                log.append('✗ 重算估值失敗(post_merge_fix.py),請看執行紀錄')
                failed.append('post_merge_fix')
        else:
            log.append('✗ 官方財報資料下載失敗,這次沒有重算估值;下次排程或重新執行時會再算')
            failed.append('download')
        for p in done:
            os.remove(p)

    stamp = datetime.datetime.now(TPE).strftime('%Y-%m-%d %H:%M')
    with open(os.path.join(INP, '處理紀錄.txt'), 'a', encoding='utf-8') as f:
        f.write(f'\n[{stamp}]\n' + '\n'.join(log) + '\n')
    shutil.rmtree(WORK, ignore_errors=True)
    print('\n' + '\n'.join(log))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
