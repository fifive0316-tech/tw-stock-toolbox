#!/usr/bin/env python3
"""每日自動更新總控(GitHub Actions 每個交易日晚上執行;也可以在自己電腦手動跑)

用法(在專案最上層資料夾執行):
  python3 scripts/daily.py

依序做:
 1. 台股趨勢雷達:價量、三大法人、融資、月營收(scripts/update_trend.py)
 2. 股利估價雷達:收盤價、殖利率、評價分區(update_prices.py;股價優先用第 1 步抓到的官方收盤價)
 3. 股利估價雷達:月營收 → 重算 Q4 推估與估值(update_div_revenue.py + post_merge_fix.py)
 4. 股利估價雷達:財報指標 ROE/毛利率/營益率/負債比(update_fundamentals.py)
 5. 股利估價雷達:近十日籌碼、趨勢分類、近 3 月營收年增(update_chips.py)
(MPT 投資組合的全市場價格由 .github/workflows/mpt.yml 另外執行 scripts/update_mpt.py)
每一步失敗都不會影響其他步驟;最後印出摘要。有任何步驟出錯時結束代碼為 1(GitHub 會寄信通知),
但已經成功的步驟一樣會被存檔發布。
"""
import json, os, shutil, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SC = os.path.join(ROOT, 'scripts')
DIV = os.path.join(ROOT, 'site', 'dividend')
TR = os.path.join(ROOT, 'site', 'trend')
WORK = os.path.join(ROOT, 'work')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
FIN_PERIOD = '115Q3'    # ← post_merge_fix.py 用的期別(民國年Q季);年報(第4季)出來後要跟著調整公式

summary, errors = [], []


def run(name, args):
    print(f'\n===== {name} =====', flush=True)
    p = subprocess.run([sys.executable, '-I'] + args, cwd=ROOT, capture_output=True, text=True)
    out = (p.stdout or '') + (p.stderr or '')
    print(out.rstrip(), flush=True)
    return p.returncode, out


def download(url, path, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            json.loads(data.decode('utf-8'))
            with open(path, 'wb') as f:
                f.write(data)
            return True
        except Exception as e:      # noqa: BLE001  網路問題一律重試
            print(f'  下載失敗({i + 1}/{tries}):{url} → {e}', flush=True)
            time.sleep(5 * (i + 1))
    return False


def w(name):
    return os.path.join(WORK, name)


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)

    # 1. 趨勢雷達
    code, _ = run('台股趨勢雷達', [os.path.join(SC, 'update_trend.py'), '--data', os.path.join(TR, 'data.json'),
                                  '--extra', os.path.join(TR, 'extra.json'), '--quotes-dir', WORK])
    if code == 0:
        summary.append('趨勢雷達:已更新')
    elif code == 2:
        summary.append('趨勢雷達:沒有新資料')
    else:
        errors.append('趨勢雷達:抓取有錯誤(見上方紀錄)')

    # 2. 股利估價雷達股價
    twse, tpex = w('twse.json'), w('tpex.json')
    if not (os.path.exists(twse) and os.path.exists(tpex)):
        print('\n第 1 步沒有輸出收盤價,改下載官方開放資料')
        ok = download('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL', twse) and \
             download('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes', tpex)
        if not ok:
            twse = tpex = None
            errors.append('股利估價雷達股價:開放資料下載失敗')
    if twse:
        code, out = run('股利估價雷達 股價', [os.path.join(SC, 'update_prices.py'), '--stocks', os.path.join(DIV, 'stocks.json'),
                                         '--twse', twse, '--tpex', tpex, '--current-meta', os.path.join(DIV, 'meta.json'),
                                         '--out-stocks', w('stocks.p.json'), '--out-meta', w('meta.p.json')])
        if code == 0:
            shutil.copy(w('stocks.p.json'), os.path.join(DIV, 'stocks.json'))
            shutil.copy(w('meta.p.json'), os.path.join(DIV, 'meta.json'))
            summary.append('股利估價雷達股價:已更新 ' + next((l for l in out.splitlines() if l.startswith('評價分布')), ''))
        elif code == 2:
            summary.append('股利估價雷達股價:沒有比現在更新的收盤價')
        else:
            errors.append('股利估價雷達股價:update_prices.py 失敗')

    # 3、4 共用的財報開放資料
    fin = {}
    for key, url in (('twse_inc', 'https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci'),
                     ('twse_bal', 'https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci'),
                     ('tpex_inc', 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci'),
                     ('tpex_bal', 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ci'),
                     ('rev_L', 'https://openapi.twse.com.tw/v1/opendata/t187ap05_L'),
                     ('rev_O', 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O')):
        if download(url, w(key + '.json')):
            fin[key] = w(key + '.json')

    # 3. 月營收 → 重算估值
    if 'rev_L' in fin and 'rev_O' in fin:
        code, _ = run('股利估價雷達 月營收', [os.path.join(SC, 'update_div_revenue.py'), '--stocks', os.path.join(DIV, 'stocks.json'),
                                         '--twse-rev', fin['rev_L'], '--tpex-rev', fin['rev_O'], '--out', w('stocks.r.json')])
        if code == 0:
            if 'twse_inc' in fin and 'tpex_inc' in fin:
                c2, out = run('股利估價雷達 重算估值', [os.path.join(SC, 'post_merge_fix.py'), '--stocks', w('stocks.r.json'),
                                                   '--twse-inc', fin['twse_inc'], '--tpex-inc', fin['tpex_inc'],
                                                   '--period', FIN_PERIOD, '--out', w('stocks.f.json')])
                if c2 == 0:
                    shutil.copy(w('stocks.f.json'), os.path.join(DIV, 'stocks.json'))
                    summary.append('股利估價雷達月營收:已更新並重算估值')
                else:
                    errors.append('股利估價雷達月營收:重算估值失敗(post_merge_fix.py),營收沒有寫入')
            else:
                errors.append('股利估價雷達月營收:財報資料下載失敗,營收沒有寫入')
        elif code == 2:
            summary.append('股利估價雷達月營收:沒有變動')
        else:
            errors.append('股利估價雷達月營收:update_div_revenue.py 失敗')
    else:
        errors.append('股利估價雷達月營收:開放資料下載失敗')

    # 4. 財報指標
    if all(k in fin for k in ('twse_inc', 'twse_bal', 'tpex_inc', 'tpex_bal')):
        code, out = run('股利估價雷達 財報指標', [os.path.join(SC, 'update_fundamentals.py'), '--twse-inc', fin['twse_inc'],
                                             '--twse-bal', fin['twse_bal'], '--tpex-inc', fin['tpex_inc'], '--tpex-bal', fin['tpex_bal'],
                                             '--current', os.path.join(DIV, 'fundamentals.json'), '--out', w('fund.json')])
        if code == 0:
            shutil.copy(w('fund.json'), os.path.join(DIV, 'fundamentals.json'))
            summary.append('財報指標:' + next((l for l in out.splitlines() if l.startswith('合併')), '已更新'))
        elif code == 1:
            errors.append('財報指標:update_fundamentals.py 失敗')
    else:
        errors.append('財報指標:開放資料下載失敗')

    # 5. 籌碼
    code, out = run('股利估價雷達 籌碼', [os.path.join(SC, 'update_chips.py'), '--stocks', os.path.join(DIV, 'stocks.json'),
                                     '--radar', os.path.join(TR, 'data.json'), '--out', w('chips.json')])
    if code == 0:
        shutil.copy(w('chips.json'), os.path.join(DIV, 'chips.json'))
        summary.append('籌碼:' + next((l for l in out.splitlines() if l.startswith('籌碼資料日期')), '已更新'))
    else:
        errors.append('籌碼:update_chips.py 失敗')

    shutil.rmtree(WORK, ignore_errors=True)
    print('\n===== 摘要 =====')
    for s in summary:
        print('✓ ' + s)
    for e in errors:
        print('✗ ' + e)
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
