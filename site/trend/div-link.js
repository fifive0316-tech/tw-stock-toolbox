/* 股利估價雷達 → 台股趨勢雷達 的資料連結
 * 資料直接讀網站裡 ../dividend/ 資料夾(股利估價雷達)的檔案。
 * 品質分數的算法與股利估價雷達 index.html 的 prepQuality() 相同（改那邊時這裡要一起改）。
 * 估值以「趨勢雷達最新收盤價」重算殖利率與分區（分區規則與 update_prices.py 相同）。
 */
(function(root){
'use strict';

var TREND = {uptrend:['上升',5], breakout_watch:['突破關注',4], consolidation:['盤整',3], breakdown_watch:['跌破關注',2], downtrend:['下降',1]};
var Q_MIN_CHECKS = 3;
var ZONE_LABEL = {cheap:'便宜', fair:'合理', expensive:'昂貴', review:'待覆核（推估殖利率超過 12%）'};
var NO_EST_LABEL = {loss_this_year:'今年推估虧損，不估股利', non_positive_estimate:'無配息率資料或推估股利不為正'};

function isNum(v){ return typeof v === 'number' && isFinite(v); }
function median(arr){
  if (!arr.length) return null;
  var a = arr.slice().sort(function(x, y){ return x - y; }), m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m-1] + a[m]) / 2;
}
function pctTxt(v, signed){
  if (v === null || v === undefined) return null;
  if (v > 999) return '>999%';
  if (v < -999) return '<-999%';
  return (signed && v > 0 ? '+' : '') + v.toFixed(1) + '%';
}
function r2(v){ return isNum(v) ? Math.round(v*100)/100 : null; }
function r1(v){ return isNum(v) ? Math.round(v*10)/10 : null; }
function getJson(path){
  return fetch(path).then(function(r){ return r.ok ? r.json() : null; }).catch(function(){ return null; });
}

var loadP = null, DB = null;

function load(){
  if (loadP) return loadP;
  // 獨立架站版:直接讀同一個網站裡「股利估價雷達」資料夾的檔案,不再另存複本
  var D = '../dividend/';
  loadP = Promise.all([getJson(D + 'stocks.json'), getJson(D + 'meta.json'), getJson(D + 'chips.json'),
                       getJson(D + 'industry.json'), getJson(D + 'fundamentals.json')])
    .then(function(res){
      var stocks = res[0];
      if (!Array.isArray(stocks)) { DB = null; return null; }
      DB = {meta: res[1], chips: res[2], industry: res[3], fund: res[4], map: {}};
      var indMap = (res[3] && res[3].map) || {};
      stocks.forEach(function(s){ s.industry = indMap[s.code] || null; DB.map[s.code] = s; });
      prepQuality(stocks);
      return DB;
    });
  return loadP;
}

/* 與股利估價雷達 prepQuality() 相同的 9 項檢核 */
function prepQuality(data){
  var fund = (DB.fund && DB.fund.stocks) || {};
  var chips = (DB.chips && DB.chips.stocks) || {};
  var pool = {gm:{}, opm:{}}, all = {gm:[], opm:[]};
  data.forEach(function(r){
    var f = fund[r.code];
    if (!f) return;
    ['gm','opm'].forEach(function(k){
      if (!isNum(f[k])) return;
      all[k].push(f[k]);
      var ind = r.industry || '未分類';
      (pool[k][ind] = pool[k][ind] || []).push(f[k]);
    });
  });
  var allMed = {gm: median(all.gm), opm: median(all.opm)};
  function indMed(k, ind){
    var a = pool[k][ind || '未分類'];
    return (a && a.length >= 5) ? {v: median(a), scope: '同產業'} : {v: allMed[k], scope: '全市場'};
  }

  data.forEach(function(r){
    var f = fund[r.code] || null, c = chips[r.code] || null, checks = [];
    function add(k, label, std, text, pass){ checks.push({k:k, label:label, std:std, text:text, pass:pass}); }

    var pby = r.payout_by_year || {}, streak = null;
    var years = Object.keys(pby).filter(function(y){ return isNum(pby[y]); }).sort();
    if (years.length){
      streak = 0;
      for (var y = +years[years.length-1]; y >= 2000; y--){
        var pv = pby[String(y)];
        if (!isNum(pv) || pv === 0) break;
        streak++;
      }
    }
    add('div', '連續配息', '5 年以上', streak === null ? null : streak + ' 年', streak === null ? null : streak >= 5);

    var qs = (r.eps_hist || []).map(function(x){ return x[1]; });
    (r.last4_eps || []).forEach(function(x){ if (!x.estimated) qs.push(x.eps); });
    qs = qs.filter(isNum);
    var pos = qs.filter(function(v){ return v > 0; }).length, nq = qs.length;
    add('profit', '獲利穩定', '近 12 季已公告單季EPS虧損不超過 1 季', nq ? pos + '/' + nq + ' 季獲利' : null, nq >= 8 ? (nq - pos) <= 1 : null);

    var ry = (c && isNum(c.ry)) ? c.ry : null;
    var rm = (c && c.rm) ? '（至 ' + c.rm.slice(0,4) + '/' + c.rm.slice(4) + '）' : '';
    add('rev', '營收動能', '近 3 個月營收合計高於去年同期' + rm, pctTxt(ry, true), ry === null ? null : ry > 0);

    var inst = null;
    if (c && c.f && c.t){
      var tot = 0, any = false;
      c.f.concat(c.t).forEach(function(x){ if (isNum(x)){ tot += x; any = true; } });
      if (any) inst = Math.round(tot / 1000);
    }
    add('inst', '法人動向', '近十個交易日外資+投信合計買超', inst === null ? null : (inst > 0 ? '+' : '') + inst.toLocaleString('zh-TW') + ' 張', inst === null ? null : inst > 0);

    var tr = (c && TREND[c.tr]) ? TREND[c.tr] : null;
    add('trend', '趨勢', '不是「下降」或「跌破關注」', tr ? tr[0] : null, tr ? tr[1] >= 3 : null);

    r.roe = (f && isNum(f.roe)) ? f.roe : null;
    r.gm = (f && isNum(f.gm)) ? f.gm : null;
    r.opm = (f && isNum(f.opm)) ? f.opm : null;
    r.debt = (f && isNum(f.debt)) ? f.debt : null;
    r.fin_period = f ? f.p : null;
    r.fin_src = f ? (f.src || null) : null;
    add('roe', r.fin_src === 'x' ? 'ROE(近四季)' : 'ROE(年化)', '10% 以上', pctTxt(r.roe), r.roe === null ? null : r.roe >= 10);
    var mg = indMed('gm', r.industry), mo = indMed('opm', r.industry);
    r.gm_med = mg; r.opm_med = mo;
    add('gm', '毛利率', '不低於' + mg.scope + '中位數' + (isNum(mg.v) ? ' ' + mg.v.toFixed(1) + '%' : ''),
        pctTxt(r.gm), (r.gm === null || !isNum(mg.v)) ? null : r.gm >= mg.v);
    add('opm', '營業利益率', '為正，且不低於' + mo.scope + '中位數' + (isNum(mo.v) ? ' ' + mo.v.toFixed(1) + '%' : ''),
        pctTxt(r.opm), (r.opm === null || !isNum(mo.v)) ? null : (r.opm > 0 && r.opm >= mo.v));
    add('debt', '負債比', '低於 60%', pctTxt(r.debt), r.debt === null ? null : r.debt < 60);

    var pass = 0, n = 0;
    checks.forEach(function(x){ if (x.pass !== null){ n++; if (x.pass) pass++; } });
    r.q_checks = checks;
    r.q_n = n;
    r.q_pass = n >= Q_MIN_CHECKS ? pass : null;
  });
}

function get(code){ return (DB && DB.map[code]) || null; }
function priceDate(){ return (DB && DB.meta && DB.meta.price_date) || null; }

/* 用最新收盤價重算的估值數字 */
function valuationAt(s, close){
  var out = {close: close};
  var est = s.est_dividend;
  if (isNum(est) && est > 0 && isNum(close) && close > 0){
    out.yield = r2(est / close * 100);
    out.zone = out.yield > 12 ? 'review' : (close <= s.cheap_price ? 'cheap' : (close <= s.fair_price ? 'fair' : 'expensive'));
    out.vsFair = isNum(s.fair_price) && s.fair_price > 0 ? r1((close / s.fair_price - 1) * 100) : null;
    out.vsCheap = isNum(s.cheap_price) && s.cheap_price > 0 ? r1((close / s.cheap_price - 1) * 100) : null;
  } else {
    out.yield = null; out.zone = null; out.vsFair = null; out.vsCheap = null;
  }
  var l4 = s.last4_eps || [], sum = 0, ok = l4.length === 4, anyEst = false;
  l4.forEach(function(x){ if (isNum(x.eps)) sum += x.eps; else ok = false; if (x.estimated) anyEst = true; });
  out.ttmEps = ok ? r2(sum) : null;
  out.ttmHasEstimate = anyEst;
  out.peTtm = (ok && sum > 0 && close > 0) ? r1(close / sum) : null;
  out.peFwd = (isNum(s.eps_this_year) && s.eps_this_year > 0 && close > 0) ? r1(close / s.eps_this_year) : null;
  return out;
}

function quarterList(s){
  var q = (s.eps_hist || []).map(function(x){ return {q: x[0], eps: x[1], estimated: false}; });
  (s.last4_eps || []).forEach(function(x){ q.push({q: x.q, eps: x.eps, estimated: !!x.estimated}); });
  return q;
}

/* ---------- 頁面區塊 ---------- */
function esc(s){ var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
function n2(v, d){ return isNum(v) ? v.toLocaleString('zh-TW', {minimumFractionDigits: d, maximumFractionDigits: d}) : '–'; }
function fmtD(d){ return (d && d.length === 8) ? d.slice(0,4) + '/' + d.slice(4,6) + '/' + d.slice(6,8) : (d || '–'); }
function kv(k, v, cls, sub){
  return '<div class="kv"><div class="k">' + k + '</div><div class="v tabular' + (cls ? ' ' + cls : '') + '">' + v + '</div>' + (sub ? '<div class="v small">' + sub + '</div>' : '') + '</div>';
}
function signCls(v){ return !isNum(v) ? 'flat' : (v > 0 ? 'up' : (v < 0 ? 'down' : 'flat')); }

function sectionHtml(r){
  var label = '<div class="section-label">股利估值與財報品質（股利估價雷達）</div>';
  if (!DB) return label + '<div class="inst-empty">股利估價雷達的資料目前讀不到（檔案尚未同步），這一區暫時無法顯示。</div>';
  var s = get(r.code);
  if (!s) return label + '<div class="inst-empty">股利估價雷達沒有收錄這檔（ETF、特別股、權證、存託憑證等不在範圍內）。</div>';
  var v = valuationAt(s, r.close);
  var zoneTxt = v.zone ? ZONE_LABEL[v.zone] : (s.no_est_reason ? NO_EST_LABEL[s.no_est_reason] || '無法估算' : '無法估算');
  var zoneCls = '';
  var eps = '';
  var ql = quarterList(s).slice(-4);
  if (ql.length) eps = ql.map(function(x){ return x.q + ' ' + n2(x.eps, 2) + (x.estimated ? '(估)' : ''); }).join('　');
  var qBadge = s.q_pass === null || s.q_pass === undefined ? '–' : s.q_pass + ' / ' + s.q_n;
  var fails = (s.q_checks || []).filter(function(x){ return x.pass === false; }).map(function(x){ return x.label; });
  var html = label
    + '<div class="kv-grid">'
    +   kv('今年EPS（含推估）', n2(s.eps_this_year, 2) + ' 元', null, isNum(s.eps_yoy_pct) ? '年增 ' + (s.eps_yoy_pct > 0 ? '+' : '') + s.eps_yoy_pct.toFixed(1) + '%' : null)
    +   kv('推估股利', isNum(s.est_dividend) ? n2(s.est_dividend, 2) + ' 元' : '–', null, isNum(s.payout_used) ? '配息率 ' + s.payout_used.toFixed(1) + '%' : null)
    +   kv('便宜價（×16.5）', n2(s.cheap_price, 2), null, isNum(v.vsCheap) ? '現價 ' + (v.vsCheap > 0 ? '+' : '') + v.vsCheap.toFixed(1) + '%' : null)
    +   kv('合理價（×20）', n2(s.fair_price, 2), null, isNum(v.vsFair) ? '現價 ' + (v.vsFair > 0 ? '+' : '') + v.vsFair.toFixed(1) + '%' : null)
    +   kv('推估殖利率（現價）', isNum(v.yield) ? v.yield.toFixed(2) + '%' : '–')
    +   kv('評價分區（現價）', esc(zoneTxt), zoneCls)
    +   kv('本益比（近四季）', isNum(v.peTtm) ? v.peTtm.toFixed(1) + ' 倍' : '–', null, v.ttmHasEstimate ? '含推估季度' : null)
    +   kv('品質分數', qBadge, null, fails.length ? '未達：' + esc(fails.join('、')) : null)
    +   kv('ROE（年化）', pctTxt(s.roe) || '–', null, s.fin_period ? s.fin_period : null)
    +   kv('負債比', pctTxt(s.debt) || '–')
    +   kv('毛利率', pctTxt(s.gm) || '–', null, s.gm_med && isNum(s.gm_med.v) ? s.gm_med.scope + '中位數 ' + s.gm_med.v.toFixed(1) + '%' : null)
    +   kv('營業利益率', pctTxt(s.opm) || '–', null, s.opm_med && isNum(s.opm_med.v) ? s.opm_med.scope + '中位數 ' + s.opm_med.v.toFixed(1) + '%' : null)
    + '</div>'
    + (eps ? '<div class="mini-table-note" style="margin:-8px 0 6px">近四季EPS：' + esc(eps) + '</div>' : '')
    + '<div class="mini-table-note" style="margin-bottom:16px">股利估價雷達股價日 ' + fmtD(priceDate()) + '；殖利率、分區、本益比以本頁最新收盤 ' + n2(r.close, 2) + '（' + fmtD(r.date) + '）重算。'
    + (s.oneoff_warning ? '<b>估值提醒：今年獲利可能含一次性因素，推估股利可能偏高。</b>' : '')
    + '</div>';
  return html;
}

/* ---------- 給 AI 報告的資料 ---------- */
function aiContext(r){
  if (!DB) return {狀態: '股利估價雷達資料讀不到'};
  var s = get(r.code);
  if (!s) return {狀態: '股利估價雷達未收錄此檔'};
  var v = valuationAt(s, r.close);
  return {
    股利估價雷達股價日: priceDate(),
    產業: s.industry,
    股利估值: {
      方法說明: '推估股利=今年EPS(已公告季度+營收推估季度)×近三年配息率中位數(上限100%)；便宜價=推估股利×16.5、合理價=推估股利×20；殖利率>12%列待覆核',
      今年EPS_含推估: s.eps_this_year, 去年EPS: r2(s.eps_last_year), EPS年增率百分比: s.eps_yoy_pct,
      今年各季EPS: {Q1: s.q1, Q2: s.q2, Q3: s.q3, Q3來源: s.q3_source === 'actual' ? '已公告' : '推估', Q4_推估: s.q4},
      近三年配息率中位數百分比: s.payout_median3, 採用配息率百分比: s.payout_used, 配息率逐年: s.payout_by_year,
      推估股利_元: s.est_dividend, 便宜價: s.cheap_price, 合理價: s.fair_price,
      以最新收盤計_推估殖利率百分比: v.yield, 以最新收盤計_評價分區: v.zone ? ZONE_LABEL[v.zone] : null,
      現價相對合理價百分比: v.vsFair, 現價相對便宜價百分比: v.vsCheap,
      無法估算原因: s.no_est_reason ? NO_EST_LABEL[s.no_est_reason] : null,
      一次性獲利提醒: s.oneoff_warning ? (s.oneoff_reasons || []) : null,
      高配息率提醒: !!s.high_payout_warning,
      今年累計營收年增率百分比: s.rev_yoy_pct
    },
    本益比: {近四季EPS合計: v.ttmEps, 近四季含推估季度: v.ttmHasEstimate, 近四季本益比: v.peTtm, 以今年推估EPS計之本益比: v.peFwd},
    近12季單季EPS: quarterList(s).map(function(x){ return [x.q, x.eps, x.estimated ? '推估' : '已公告']; }),
    財報品質: {
      財報期別: s.fin_period, ROE年化百分比: s.roe, 毛利率百分比: s.gm, 營業利益率百分比: s.opm, 負債比百分比: s.debt,
      毛利率比較基準: s.gm_med && isNum(s.gm_med.v) ? s.gm_med.scope + '中位數 ' + s.gm_med.v.toFixed(1) + '%' : null,
      營益率比較基準: s.opm_med && isNum(s.opm_med.v) ? s.opm_med.scope + '中位數 ' + s.opm_med.v.toFixed(1) + '%' : null,
      品質分數: s.q_pass === null || s.q_pass === undefined ? null : s.q_pass + '/' + s.q_n,
      九項檢核: (s.q_checks || []).map(function(x){ return [x.label, x.text, x.pass === null ? '無資料' : (x.pass ? '達標' : '未達標')]; })
    }
  };
}

root.DivLink = {load: load, get: get, priceDate: priceDate, sectionHtml: sectionHtml, aiContext: aiContext, valuationAt: valuationAt};
})(typeof self !== 'undefined' ? self : this);
