# 台股工具箱(獨立架站版)

「台股趨勢雷達」、「股利估價雷達」與「MPT 投資組合」三合一的台股工具箱:

- **一個網址、三個分頁**:打開網站直接進入台股趨勢雷達,上方分頁列可切換到股利估價雷達、MPT 投資組合。

- **網頁**放在 GitHub Pages,有自己的固定網址,手機電腦都能開。
- **每天自動更新**由 GitHub Actions 執行(免費),不需要任何 AI,也不需要你的電腦開著。
- **個股分析**改用 Gemini:在趨勢雷達點個股 →「✨ 複製 Gemini 分析提示詞」→ 貼到 Gemini。

資料是 2026-11-20 收盤的快照,架好之後會從下一個交易日開始自動更新。

---

## 資料夾內容

| 位置 | 內容 |
|---|---|
| `site/` | 網站本身:`index.html`(自動轉到趨勢雷達)、`nav.js` 共用分頁列、`trend/` 趨勢雷達、`dividend/` 股利估價雷達、`mpt/` MPT 投資組合 |
| `scripts/` | 自動更新用的 Python 程式(`daily.py` 是總控) |
| `inputs/` | 你上傳 CSV / 估價表 xlsx 的地方,上傳後自動合併 |
| `.github/workflows/` | GitHub 自動執行的設定:每日更新、合併上傳檔、發布網站 |
| `gemini/` | 建立 Gemini「Gem」用的指令與知識檔 |

---

## 一、架設(第一次,約 20 分鐘)

1. **註冊 GitHub**:到 https://github.com 免費註冊並登入。
2. **建立儲存庫**:右上角「+」→「New repository」。
   - Repository name 填 `tw-stock-toolbox`(可自訂,網址會用到)。
   - 選 **Public**(免費帳號的 GitHub Pages 只能用公開儲存庫,見最後「注意事項」)。
   - 勾「Add a README file」,按「Create repository」。
3. **上傳檔案**:在儲存庫頁面按「Add file → Upload files」,把解壓縮後**資料夾裡面的所有東西**(`site`、`scripts`、`inputs`、`gemini`、`.github`、`README.md`、`.gitignore`)一起拖進去,按「Commit changes」。
   - 請用 Chrome 或 Edge 拖曳整個資料夾,子資料夾才會一起上傳。
   - 上傳後確認看得到 `.github/workflows` 裡有四個 `.yml` 檔;如果沒有,單獨再拖一次 `.github` 資料夾。
4. **開啟網站發布**:「Settings」→ 左側「Pages」→「Build and deployment」的 Source 選 **GitHub Actions**。
5. **允許自動存檔**:「Settings」→「Actions」→「General」→ 最下方「Workflow permissions」選 **Read and write permissions** → Save。
6. **第一次發布**:上方「Actions」分頁 → 左側「發布網站」→ 右側「Run workflow」→ 綠色按鈕。約 1 分鐘後完成。
7. **打開網站**:`https://你的帳號.github.io/tw-stock-toolbox/`(Settings → Pages 也會顯示網址)。
8. **試跑每日更新**:「Actions」→「每日資料更新」→「Run workflow」。約 5~15 分鐘,完成後網頁的資料日期會變成最新交易日。

之後每個交易日台北時間約 21:40 自動跑一次,隔天早上 08:30 再補跑一次。GitHub 的排程常延遲數十分鐘,屬正常現象。

---

## 二、日常使用

### MPT 投資組合(現代投資組合理論)
依莊瑞南老師「運用現代投資組合理論分析台股 ETF 與大型股之風險報酬與最優配置」專題製作,原本的 Flask + MySQL + yfinance 架構改成:

| 專題原架構 | 本站做法 |
|---|---|
| `data_update.py` 用 yfinance 抓股價寫入 MySQL | `scripts/update_mpt.py` 每個交易日從 Yahoo Finance(yfinance 同一來源)抓**全市場**(上市+上櫃+ETF,約 2,300 檔)2015 年起的還原權息收盤價,每檔一個檔案放在 `site/mpt/px/` |
| `mpt_engine.py`(numpy/scipy):報酬、風險、共變異、3000 組隨機權重、GMV、Max Sharpe | `site/mpt/mpt-engine.js` 在瀏覽器裡計算,結果已與 scipy SLSQP 比對一致 |
| `app.py` + `main.js` + `index.html` | `site/mpt/index.html`:選股、期間、風險偏好(保守/平衡/積極)、效率前緣圖、權重、回測、相關係數 |

- 選標的用**可搜尋的下拉選單**:輸入代號、名稱或產業(例:`2330`、`台積`、`半導體`),最多同時選 40 檔;也有「專題 14 檔」「ETF + 權值股」「高股息 ETF」「電子權值」快速鍵。網頁只下載你選到的標的價格檔。
- 全市場清單跟著趨勢雷達(`site/trend/data.json`)走,新上市的股票、ETF 會自動加入。
- **價格檔不放進 git**(約 2,300 個檔、每天都變,放進去儲存庫會暴增),而是由「MPT 全市場資料」這個 Action 存在 GitHub Actions 的快取,發布網站時一起上傳。
  - **第一次架站**:完成上面「一、架設」後,到「Actions」→「MPT 全市場資料」→「Run workflow」跑一次(約 5~15 分鐘),MPT 分頁才會有資料。
  - 之後每個交易日台北時間約 22:10 自動更新(隔天 08:50 補跑);只抓最近 40 天,遇到除權息才整段重抓。
  - 快取 7 天沒用到會被 GitHub 清掉(例如排程被停用),此時 MPT 分頁會顯示「資料還沒建立」,再手動跑一次即可自動重建。
- 保守 = GMV、平衡 = 最大夏普、積極 = 效率前緣上介於最大夏普與最高報酬標的之間的組合。

### 篩選價值股
打開股利估價雷達,選「便宜」、品質「7 項以上」、本益比「12 倍以下」,再切到「品質欄位」逐項看。

### 用 Gemini 分析個股
1. 先照下面「三、建立 Gemini Gem」做一次。
2. 在趨勢雷達搜尋代號、點開個股,按「✨ 複製 Gemini 分析提示詞」。
3. 打開 Gemini、選你的 Gem,貼上送出。

### 每月 / 每季要做的事(上傳檔案)
在 GitHub 儲存庫打開 `inputs` 資料夾 →「Add file → Upload files」→ 拖入檔案 →「Commit changes」。約 3~5 分鐘後自動合併並重新發布,結果寫在 `inputs/處理紀錄.txt`。

| 檔案 | 什麼時候上傳 |
|---|---|
| 估價表 xlsx(個股評價與快速估算表) | 有新版時(更新三大估價法快照、補實際 EPS 與缺的財報指標) |
| EPS CSV | 每季財報公告後(約 5/15、8/14、11/14) |
| 股利分配率 CSV | 每年股利政策公告後(約 3~6 月) |

月營收**不用上傳**,每天自動從證交所、櫃買中心的官方資料更新,並重算 Q4 推估與便宜價。

### 出錯時
GitHub 會寄信通知。到「Actions」點那次紅色的執行 → 點「update」→ 展開「抓資料並更新兩個雷達」,最下方「摘要」會寫哪一步失敗。單一步驟失敗不影響其他步驟,隔天通常會自動補上。

---

## 三、建立 Gemini Gem

1. 打開 https://gemini.google.com → 左側「Gem 管理員」(Gems)→「新增 Gem」。
2. 名稱:`台股分析師`。
3. 「指令」欄:貼上 `gemini/Gem指令.txt` 的全部內容。
4. 「知識」欄:上傳 `gemini/` 裡三個 `知識*.md` 檔。
5. 儲存。之後分析個股時從左側選這個 Gem。

需要「上傳 CSV 做兩部分報告」時,直接在這個 Gem 的對話裡上傳 CSV 並說「幫我評估 2330 台積電」即可(Gemini 每次最多 10 個檔案、每檔 100MB)。

---

## 四、注意事項與限制

- **公開**:免費版 GitHub Pages 需要公開儲存庫,知道網址的人都能看到網頁與資料(都是公開市場資料加上推算結果)。你上傳的 CSV / xlsx 合併後會被刪除,但仍留在 Git 歷史紀錄裡;若介意,可改用付費的 GitHub Pro(私人儲存庫也能用 Pages)。
- **證交所可能擋國外主機**:GitHub 的主機在美國。若證交所網站擋住,上市股價會改用官方開放資料(晚一點才有、沒有三大法人),摘要會出現「上市 … 連線失敗」。真的長期失敗時,可以在自己電腦安裝 Python 3,在這個資料夾執行 `pip install numpy openpyxl` 與 `python scripts/daily.py`,再用 GitHub Desktop 把變動上傳。
- **年度設定**:估值公式目前針對 2026 年(Q1~Q3 實際、Q4 推估,官方前三季累計期別 115Q3)。**2027 年 5 月第一季財報出來前**需要更新程式的年度常數與季別欄位(`scripts/merge_inputs.py` 的 `YEAR/QUARTER`、`post_merge_fix.py` 與 `update_div_revenue.py` 的 `THIS_YEAR`、`daily.py` 的 `FIN_PERIOD`,以及 `stocks.json` 的季度欄位);屆時可以把這份 README 和相關程式貼給 Gemini 或其他 AI 協助修改。
- **儲存庫會慢慢變大**:每天會提交約 20MB 的資料檔變動,一年後可能接近 1GB。GitHub 建議單一儲存庫小於 1~5GB;太大時可以建一個新儲存庫,只上傳目前的檔案。
- **排程停用**:公開儲存庫若 60 天沒有任何活動,GitHub 會自動停用排程;每日更新本身會產生提交,通常不會觸發,但若收到停用通知,到「Actions」重新啟用即可。
- **估價表快照、EPS 推估**的定義與限制,請看網頁底部的「計算方式」或 `gemini/知識1_估值方法與品質分數.md`。
- 本工具僅為量化篩選,不構成投資建議。
