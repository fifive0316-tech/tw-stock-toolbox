#!/usr/bin/env python3
"""股利估價雷達 產業別對照檔

用法:
  python3 -I update_industry.py --twse twse_basic.json --tpex tpex_basic.json --out industry.json

twse_basic.json = https://openapi.twse.com.tw/v1/opendata/t187ap03_L        (上市公司基本資料,欄位「公司代號」「產業別」)
tpex_basic.json = https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O     (上櫃公司基本資料,欄位 SecuritiesCompanyCode / SecuritiesIndustryCode)

輸出 industry.json: {"asof": "YYYYMMDD", "map": {"2330": "半導體", ...}}
頁面載入時用代號對照,stocks.json 本身不存產業別,所以 CSV 合併或每日股價更新都不會動到它。
產業別很少變動,有新上市櫃公司或想重新整理時再跑一次即可。

結束代碼:0 = 已產生;1 = 來源筆數過少或格式不符,不應發布。
"""
import argparse, json, sys, datetime

# 證交所/櫃買中心共用的產業別代碼(短名稱)
INDUSTRY = {
    '01': '水泥', '02': '食品', '03': '塑膠', '04': '紡織纖維', '05': '電機機械', '06': '電器電纜',
    '08': '玻璃陶瓷', '09': '造紙', '10': '鋼鐵', '11': '橡膠', '12': '汽車', '14': '建材營造',
    '15': '航運', '16': '觀光餐旅', '17': '金融保險', '18': '貿易百貨', '19': '綜合', '20': '其他',
    '21': '化學', '22': '生技醫療', '23': '油電燃氣', '24': '半導體', '25': '電腦及週邊', '26': '光電',
    '27': '通信網路', '28': '電子零組件', '29': '電子通路', '30': '資訊服務', '31': '其他電子',
    '32': '文化創意', '33': '農業科技', '34': '電子商務', '35': '綠能環保', '36': '數位雲端',
    '37': '運動休閒', '38': '居家生活', '80': '管理股票', '91': '存託憑證',
}


def load(path, code_key, ind_key):
    with open(path, encoding='utf-8') as f:
        rows = json.load(f)
    out, unknown = {}, set()
    for r in rows:
        code, ind = str(r.get(code_key, '')).strip(), str(r.get(ind_key, '')).strip()
        if not code or not ind:
            continue
        name = INDUSTRY.get(ind)
        if name is None:
            unknown.add(ind)
            name = '代碼' + ind
        out[code] = name
    return out, unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--twse', required=True)
    ap.add_argument('--tpex', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    twse, u1 = load(a.twse, '公司代號', '產業別')
    tpex, u2 = load(a.tpex, 'SecuritiesCompanyCode', 'SecuritiesIndustryCode')
    print(f'上市 {len(twse)} 檔、上櫃 {len(tpex)} 檔')
    if u1 | u2:
        print('注意:出現對照表沒有的產業代碼', sorted(u1 | u2), '(頁面會顯示「代碼XX」,請補進 INDUSTRY 對照表)')
    if len(twse) < 500 or len(tpex) < 300:
        print('錯誤:來源筆數過少或欄位名稱不符,不發布。')
        sys.exit(1)
    m = dict(tpex)
    m.update(twse)
    asof = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime('%Y%m%d')
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump({'asof': asof, 'map': m}, f, ensure_ascii=False, separators=(',', ':'))
    print(f'已產生 {len(m)} 檔的產業別對照,日期 {asof}')


if __name__ == '__main__':
    main()
