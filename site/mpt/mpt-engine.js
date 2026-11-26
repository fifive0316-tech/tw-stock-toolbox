/* MPT 計算核心(對應專題的 mpt_engine.py,改成在瀏覽器裡算,不需要後端)
   1. 報酬、風險、共變異   2. 隨機權重模擬   3. 求解 GMV、Max Sharpe、效率前緣   4. 回傳物件
   限制:只做多(權重 0~100%)、權重合計 100%。年化以 252 個交易日計。 */
(function (root) {
  'use strict';
  var DAYS = 252;

  /* ---------- 資料整理 ---------- */
  // data: prices.json;codes: 要用的代號;start/end: 'YYYYMMDD'
  // 只保留「所有選取標的都有價格」的交易日,再算日報酬
  function prepare(data, codes, start, end) {
    var idx = {};
    data.assets.forEach(function (a, i) { idx[a.code] = i; });
    var assets = codes.map(function (c) { return data.assets[idx[c]]; }).filter(Boolean);
    var dates = [], px = assets.map(function () { return []; });
    for (var t = 0; t < data.dates.length; t++) {
      var d = data.dates[t];
      if (d < start || d > end) continue;
      var ok = true;
      for (var k = 0; k < assets.length; k++) { if (assets[k].px[t] == null) { ok = false; break; } }
      if (!ok) continue;
      dates.push(d);
      for (k = 0; k < assets.length; k++) px[k].push(assets[k].px[t]);
    }
    var rets = [];               // rets[t][k]:第 t 天第 k 檔的日報酬
    for (t = 1; t < dates.length; t++) {
      var row = new Array(assets.length);
      for (k = 0; k < assets.length; k++) row[k] = px[k][t] / px[k][t - 1] - 1;
      rets.push(row);
    }
    return {
      codes: assets.map(function (a) { return a.code; }),
      names: assets.map(function (a) { return a.name; }),
      groups: assets.map(function (a) { return a.group; }),
      dates: dates, px: px, rets: rets
    };
  }

  /* ---------- 1. 報酬、風險、共變異(年化) ---------- */
  function stats(rets) {
    var T = rets.length, n = T ? rets[0].length : 0, mu = new Array(n).fill(0), i, j, t;
    for (t = 0; t < T; t++) for (i = 0; i < n; i++) mu[i] += rets[t][i];
    for (i = 0; i < n; i++) mu[i] /= T;
    var cov = [];
    for (i = 0; i < n; i++) cov.push(new Array(n).fill(0));
    for (t = 0; t < T; t++) {
      var r = rets[t];
      for (i = 0; i < n; i++) {
        var di = r[i] - mu[i];
        for (j = i; j < n; j++) cov[i][j] += di * (r[j] - mu[j]);
      }
    }
    for (i = 0; i < n; i++) for (j = i; j < n; j++) {
      cov[i][j] = cov[i][j] / (T - 1) * DAYS;
      cov[j][i] = cov[i][j];
    }
    var muA = mu.map(function (m) { return m * DAYS; });
    var vol = cov.map(function (row, k) { return Math.sqrt(row[k]); });
    var corr = cov.map(function (row, a) {
      return row.map(function (c, b) { return (vol[a] && vol[b]) ? c / (vol[a] * vol[b]) : 0; });
    });
    return { mu: muA, cov: cov, vol: vol, corr: corr, days: T };
  }

  function portRet(w, mu) { var s = 0; for (var i = 0; i < w.length; i++) s += w[i] * mu[i]; return s; }
  function portVar(w, cov) {
    var s = 0, n = w.length;
    for (var i = 0; i < n; i++) { if (!w[i]) continue; var r = 0; for (var j = 0; j < n; j++) r += cov[i][j] * w[j]; s += w[i] * r; }
    return Math.max(s, 0);
  }
  function evaluate(w, mu, cov, rf) {
    var r = portRet(w, mu), v = Math.sqrt(portVar(w, cov));
    return { w: w, ret: r, vol: v, sharpe: v > 0 ? (r - rf) / v : 0 };
  }

  /* ---------- 2. 隨機權重模擬 ---------- */
  function rng(seed) {             // mulberry32,固定種子讓每次結果一樣
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  // 一半用全部標的的均勻隨機權重,一半只挑部分標的(讓散點涵蓋集中持股的區域)
  function simulate(mu, cov, rf, count, seed) {
    var n = mu.length, rand = rng(seed || 20260101), out = { ret: [], vol: [], sharpe: [], w: [] };
    for (var s = 0; s < count; s++) {
      var w = new Array(n).fill(0), sum = 0, i;
      var pick = s % 2 === 0 ? n : 1 + Math.floor(rand() * Math.min(n, 4));
      var chosen = [];
      if (pick === n) { for (i = 0; i < n; i++) chosen.push(i); }
      else { var pool = []; for (i = 0; i < n; i++) pool.push(i); for (i = 0; i < pick; i++) chosen.push(pool.splice(Math.floor(rand() * pool.length), 1)[0]); }
      chosen.forEach(function (k) { var x = -Math.log(1 - rand()); w[k] = x; sum += x; });
      for (i = 0; i < n; i++) w[i] /= sum;
      var e = evaluate(w, mu, cov, rf);
      out.ret.push(e.ret); out.vol.push(e.vol); out.sharpe.push(e.sharpe); out.w.push(w);
    }
    return out;
  }

  /* ---------- 3. 最佳化(只做多) ---------- */
  // 投影到 {w ≥ 0, Σw = 1}(Duchi et al. 2008)
  function projectSimplex(v) {
    var n = v.length, u = v.slice().sort(function (a, b) { return b - a; }), css = 0, theta = 0;
    for (var i = 0; i < n; i++) {
      css += u[i];
      var t = (css - 1) / (i + 1);
      if (u[i] - t > 0) theta = t;
    }
    return v.map(function (x) { return Math.max(x - theta, 0); });
  }
  function maxEig(cov) {           // 冪次法求最大特徵值,決定梯度步長
    var n = cov.length, v = new Array(n).fill(1 / Math.sqrt(n)), lam = 0;
    for (var it = 0; it < 100; it++) {
      var y = new Array(n).fill(0), i, j;
      for (i = 0; i < n; i++) for (j = 0; j < n; j++) y[i] += cov[i][j] * v[j];
      var nrm = Math.sqrt(y.reduce(function (s, x) { return s + x * x; }, 0)) || 1;
      lam = nrm; v = y.map(function (x) { return x / nrm; });
    }
    return lam || 1;
  }
  // min ½ w'Σw − q·μ'w  (q = 0 → GMV;q 越大越追求報酬)— 加速投影梯度法(FISTA)
  function solveQ(mu, cov, q, L, w0) {
    var n = mu.length, w = w0 ? w0.slice() : new Array(n).fill(1 / n), y = w.slice(), tk = 1, step = 1 / L;
    for (var it = 0; it < 4000; it++) {
      var g = new Array(n), i, j;
      for (i = 0; i < n; i++) { var s = 0; for (j = 0; j < n; j++) s += cov[i][j] * y[j]; g[i] = s - q * mu[i]; }
      var wn = projectSimplex(y.map(function (x, k) { return x - step * g[k]; }));
      var tn = (1 + Math.sqrt(1 + 4 * tk * tk)) / 2, diff = 0;
      for (i = 0; i < n; i++) { y[i] = wn[i] + (tk - 1) / tn * (wn[i] - w[i]); diff = Math.max(diff, Math.abs(wn[i] - w[i])); }
      w = wn; tk = tn;
      if (diff < 1e-11 && it > 20) break;
    }
    return w;
  }
  function clean(w) {              // 去掉 0.01% 以下的雜訊權重
    var x = w.map(function (v) { return v < 1e-4 ? 0 : v; }), s = x.reduce(function (a, b) { return a + b; }, 0);
    return x.map(function (v) { return v / s; });
  }

  function optimize(mu, cov, rf, opts) {
    opts = opts || {};
    var n = mu.length, L = maxEig(cov);
    var gmv = evaluate(clean(solveQ(mu, cov, 0, L)), mu, cov, rf);
    var muMax = Math.max.apply(null, mu);
    // 找出讓解收斂到「最高報酬標的」的 q 上限
    var qHi = 1e-3, wHi = null;
    for (var k = 0; k < 40; k++) {
      wHi = solveQ(mu, cov, qHi, L, wHi);
      if (portRet(wHi, mu) >= muMax - 1e-6 * Math.max(1, Math.abs(muMax))) break;
      qHi *= 2;
    }
    // 效率前緣:q 從 0 到 qHi
    var P = opts.points || 60, frontier = [gmv], prev = gmv.w;
    for (k = 0; k <= P; k++) {
      var q = qHi * Math.pow(1e-4, 1 - k / P);
      prev = solveQ(mu, cov, q, L, prev);
      frontier.push(evaluate(clean(prev), mu, cov, rf));
    }
    // 最大 Sharpe:先在前緣上找最佳點,再對 log q 做黃金分割細調
    var bi = 0;
    frontier.forEach(function (p, i) { if (p.sharpe > frontier[bi].sharpe) bi = i; });
    var best = frontier[bi];
    if (bi > 0) {
      var qOf = function (i) { return i <= 0 ? qHi * 1e-4 * 0.5 : qHi * Math.pow(1e-4, 1 - (i - 1) / P); };
      var a = Math.log(qOf(bi - 1)), b = Math.log(qOf(Math.min(bi + 1, P + 1))), gr = (Math.sqrt(5) - 1) / 2;
      var f = function (lq) { return evaluate(solveQ(mu, cov, Math.exp(lq), L, best.w), mu, cov, rf); };
      var c = b - gr * (b - a), d = a + gr * (b - a), fc = f(c), fd = f(d);
      for (k = 0; k < 30; k++) {
        if (fc.sharpe > fd.sharpe) { b = d; d = c; fd = fc; c = b - gr * (b - a); fc = f(c); }
        else { a = c; c = d; fc = fd; d = a + gr * (b - a); fd = f(d); }
      }
      var cand = fc.sharpe > fd.sharpe ? fc : fd;
      cand = evaluate(clean(cand.w), mu, cov, rf);
      if (cand.sharpe > best.sharpe) best = cand;
    }
    frontier.sort(function (x, y) { return x.vol - y.vol; });
    return { gmv: gmv, maxSharpe: best, frontier: frontier, L: L, qHi: qHi, muMax: muMax };
  }

  // 前緣上報酬等於 target 的組合(二分搜尋 q)
  function targetReturn(mu, cov, rf, target, L, qHi) {
    var lo = 0, hi = qHi, w = null;
    for (var k = 0; k < 50; k++) {
      var mid = (lo + hi) / 2;
      w = solveQ(mu, cov, mid, L, w);
      if (portRet(w, mu) < target) lo = mid; else hi = mid;
    }
    return evaluate(clean(solveQ(mu, cov, hi, L, w)), mu, cov, rf);
  }

  /* ---------- 期間內回測(固定權重、每日再平衡) ---------- */
  function backtest(rets, w) {
    var v = 1, curve = [1], peak = 1, mdd = 0;
    for (var t = 0; t < rets.length; t++) {
      var r = 0;
      for (var i = 0; i < w.length; i++) r += w[i] * rets[t][i];
      v *= 1 + r; curve.push(v);
      if (v > peak) peak = v;
      mdd = Math.min(mdd, v / peak - 1);
    }
    var years = rets.length / DAYS;
    return { curve: curve, total: v - 1, cagr: years > 0 ? Math.pow(v, 1 / years) - 1 : 0, mdd: mdd };
  }

  var api = { DAYS: DAYS, prepare: prepare, stats: stats, simulate: simulate, optimize: optimize,
    targetReturn: targetReturn, evaluate: evaluate, backtest: backtest, projectSimplex: projectSimplex };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.MPT = api;
})(this);
