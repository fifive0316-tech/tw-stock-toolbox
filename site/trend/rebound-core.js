/* 跌深反彈評分核心（頁面與離線驗證共用）
 * 資料單位：r.vols、r.inst.* 為「股」；extra.margin.bal 為「張」。
 */
(function(root, factory){
  if(typeof module==='object' && module.exports) module.exports = factory();
  else root.ReboundCore = factory();
})(typeof self!=='undefined' ? self : this, function(){
'use strict';

var TH = {
  drop5: -15,        // A 近5日跌幅(%) 門檻
  relGap: 8,         // B 比全市場中位數多跌幾個百分點
  instPct: 2,        // C 近5日法人買超占成交量(%)
  trustDays: 3,      // D 近5日投信買超天數
  limit: -9.5,       // E 視為跌停的單日跌幅(%)
  offLow: 1.5,       // E 收盤高於當日最低(%)
  marginChg: -10,    // F 近5日融資餘額變化(%)
  marginMin: 100,    // F 融資餘額基期下限(張)，太小的不計
  revYoy: 20,        // G 月營收年增率(%)
  volRatio: 1.2      // H 當日量 / 前10日均量
};
var COND = [
  {k:'A', name:'急跌',       desc:'近5日跌幅達 15% 以上'},
  {k:'B', name:'弱於大盤',   desc:'跌幅比全市場中位數多 8 個百分點以上'},
  {k:'C', name:'法人逆勢買', desc:'近5日三大法人合計買超，且占成交量 2% 以上'},
  {k:'D', name:'投信連買',   desc:'近5日投信至少 3 天買超'},
  {k:'E', name:'打開跌停',   desc:'近5日曾跌停，當日未跌停且收盤高於最低價 1.5% 以上'},
  {k:'F', name:'融資大減',   desc:'近5日融資餘額減少 10% 以上'},
  {k:'G', name:'營收成長',   desc:'當時已公布的最新月營收年增 20% 以上'},
  {k:'H', name:'量增換手',   desc:'當日成交量為前10日均量 1.2 倍以上'}
];

function isStock(code){ return /^[1-9][0-9]{3}$/.test(code); }

function idxMap(arr){
  var m = {}; for(var i=0;i<arr.length;i++) m[arr[i]] = i; return m;
}
function di(r){ return r._di || (r._di = idxMap(r.dates||[])); }
function ii(r){ return r._ii || (r._ii = idxMap((r.inst && r.inst.dates)||[])); }

function chgAt(r, i, k){
  if(i-k<0) return null;
  var a = r.closes[i-k], b = r.closes[i];
  if(!a || b==null) return null;
  return (b-a)/a*100;
}

function allDates(ALL){
  var seen = {};
  ALL.forEach(function(r){ var d=r.dates||[]; for(var i=0;i<d.length;i++) seen[d[i]]=1; });
  return Object.keys(seen).sort();
}

function median(a){
  if(!a.length) return null;
  var s = a.slice().sort(function(x,y){return x-y;});
  var m = s.length>>1;
  return s.length%2 ? s[m] : (s[m-1]+s[m])/2;
}
function mean(a){ if(!a.length) return null; var s=0; for(var i=0;i<a.length;i++) s+=a[i]; return s/a.length; }

/* 全市場個股 5 日漲跌的中位數（當作大盤基準） */
function marketMedian5(ALL, date, cache){
  if(cache && cache[date]!==undefined) return cache[date];
  var v = [];
  ALL.forEach(function(r){
    if(!isStock(r.code)) return;
    var i = di(r)[date]; if(i===undefined) return;
    var c = chgAt(r, i, 5); if(c!==null) v.push(c);
  });
  var m = median(v);
  if(cache) cache[date] = m;
  return m;
}

/* 訊號日當下「已公布」的最新營收月份：每月 10 日前公布上月營收 */
function knownRevMonth(date){
  var y = +date.slice(0,4), m = +date.slice(4,6), d = +date.slice(6,8);
  var back = d>10 ? 1 : 2;
  m -= back; while(m<=0){ m+=12; y--; }
  return String(y) + (m<10?'0':'') + m;
}
function revYoyAt(r, date, extra){
  var ym = knownRevMonth(date);
  var rev = r.rev;
  if(rev && rev.dates){
    for(var i=rev.dates.length-1;i>=0;i--){
      if(String(rev.dates[i])===ym){ return (rev.yoy && rev.yoy[i]!=null) ? rev.yoy[i] : null; }
    }
  }
  // extra.rev.months = { '202610': { 'TPEX_6223': [當月營收(千元), 年增率%] } }
  var mo = extra && extra.rev && extra.rev.months && extra.rev.months[ym];
  if(mo){
    var x = mo[r._key || (r.market+'_'+r.code)];
    if(x && x[1]!=null) return x[1];
  }
  return null;
}

function marginAt(r, date, extra){
  if(!extra || !extra.margin) return null;
  var mg = extra.margin;
  var md = mg._di || (mg._di = idxMap(mg.dates));
  var j = md[date]; if(j===undefined) return null;
  var arr = mg.bal[r._key || (r.market+'_'+r.code)];
  if(!arr) return null;
  // 往前找第 5 個「該股有交易」的日子對應的融資餘額；簡化為融資序列往前 5 筆
  if(j-5<0) return null;
  var now = arr[j], base = arr[j-5];
  if(now==null || base==null) return null;
  return {now:now, base:base, chg: base>=TH.marginMin ? (now-base)/base*100 : null};
}

function scoreAt(r, date, ctx){
  if(!isStock(r.code)) return null;
  var i = di(r)[date];
  if(i===undefined || i<5) return null;
  var c = r.closes, h = r.highs, l = r.lows, v = r.vols;
  var drop5 = chgAt(r, i, 5);
  if(drop5===null) return null;
  var chg1 = chgAt(r, i, 1);
  var med = marketMedian5(ctx.ALL, date, ctx.medCache);

  // 法人近 5 個交易日
  var instNet = null, instPct = null, trustDays = null, fNet = null, tNet = null;
  if(r.inst && r.inst.dates){
    var im = ii(r), n=0, sum=0, td=0, fs=0, ts=0, vsum=0;
    for(var k=0;k<5;k++){
      var d = r.dates[i-k], j = im[d];
      vsum += v[i-k] || 0;
      if(j===undefined) continue;
      var f = r.inst.foreign[j]||0, t = r.inst.trust[j]||0, dl = r.inst.dealer[j]||0;
      sum += f+t+dl; fs += f; ts += t; n++;
      if(t>0) td++;
    }
    if(n>0){ instNet = sum; fNet = fs; tNet = ts; trustDays = td; instPct = vsum>0 ? sum/vsum*100 : null; }
  }

  // 近 5 日是否曾跌停（含當日之前 4 天），當日是否打開
  var hadLimit = false;
  for(var q=1;q<=4;q++){ var cq = chgAt(r, i-q, 1); if(cq!==null && cq<=TH.limit) hadLimit = true; }
  var offLow = l[i]>0 ? (c[i]-l[i])/l[i]*100 : null;

  // 量比
  var volRatio = null;
  if(i>=10){
    var base = mean(v.slice(i-10, i));
    if(base>0) volRatio = v[i]/base;
  }

  var mg = marginAt(r, date, ctx.extra);
  var revYoy = revYoyAt(r, date, ctx.extra);

  var conds = {
    A: drop5<=TH.drop5,
    B: med===null ? null : drop5 <= med-TH.relGap,
    C: instNet===null ? null : (instNet>0 && instPct!==null && instPct>=TH.instPct),
    D: trustDays===null ? null : trustDays>=TH.trustDays,
    E: (chg1===null||offLow===null) ? null : (hadLimit && chg1>TH.limit && offLow>=TH.offLow),
    F: (!mg || mg.chg===null) ? null : mg.chg<=TH.marginChg,
    G: revYoy===null ? null : revYoy>=TH.revYoy,
    H: volRatio===null ? null : volRatio>=TH.volRatio
  };
  var score=0, max=0;
  for(var key in conds){ if(conds[key]!==null){ max++; if(conds[key]) score++; } }

  return {
    r:r, date:date, i:i, score:score, max:max, conds:conds,
    close:c[i], chg1:chg1, drop5:drop5, med5:med,
    instNet:instNet, instPct:instPct, fNet:fNet, tNet:tNet, trustDays:trustDays,
    marginNow: mg?mg.now:null, marginChg: mg?mg.chg:null,
    revYoy:revYoy, revMonth:knownRevMonth(date), volRatio:volRatio, offLow:offLow, hadLimit:hadLimit
  };
}

function scanDate(ALL, date, extra, medCache){
  var ctx = {ALL:ALL, extra:extra, medCache:medCache||{}};
  var out = [];
  ALL.forEach(function(r){ var s = scoreAt(r, date, ctx); if(s) out.push(s); });
  return out;
}

function fwd(r, i, n){
  if(i+n >= r.closes.length) return null;
  var a = r.closes[i], b = r.closes[i+n];
  if(!a || b==null) return null;
  return (b-a)/a*100;
}

function bucketOf(s){
  if(!s.conds.A) return null;
  if(s.score>=6) return '6+';
  if(s.score===5) return '5';
  if(s.score===4) return '4';
  return '≤3';
}
var BUCKETS = ['6+','5','4','≤3'];
var HORIZONS = [1,3,5];

function summarize(vals){
  if(!vals.length) return {n:0, avg:null, med:null, win:null};
  var w = 0; for(var i=0;i<vals.length;i++) if(vals[i]>0) w++;
  return {n:vals.length, avg:mean(vals), med:median(vals), win:w/vals.length*100};
}

/* rowsByDate: {date: scanDate 結果}；回傳各分數組與全體個股在各持有天數的報酬統計 */
function backtest(rowsByDate, dates){
  var acc = {};
  BUCKETS.concat(['急跌全部','全體個股']).forEach(function(b){ acc[b] = {}; HORIZONS.forEach(function(hz){ acc[b][hz] = []; }); });
  dates.forEach(function(d){
    (rowsByDate[d]||[]).forEach(function(s){
      var b = bucketOf(s);
      HORIZONS.forEach(function(hz){
        var f = fwd(s.r, s.i, hz); if(f===null) return;
        acc['全體個股'][hz].push(f);
        if(b){ acc[b][hz].push(f); acc['急跌全部'][hz].push(f); }
      });
    });
  });
  var out = {};
  for(var b in acc){ out[b] = {}; HORIZONS.forEach(function(hz){ out[b][hz] = summarize(acc[b][hz]); }); }
  return out;
}

return {
  TH:TH, COND:COND, BUCKETS:BUCKETS, HORIZONS:HORIZONS,
  isStock:isStock, allDates:allDates, marketMedian5:marketMedian5,
  scoreAt:scoreAt, scanDate:scanDate, fwd:fwd, bucketOf:bucketOf, backtest:backtest,
  knownRevMonth:knownRevMonth, median:median, mean:mean
};
});
