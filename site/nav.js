/* 台股工具箱:三個工具共用的分頁列。
   用法:在各工具 index.html 的 <body> 後第一行放 <script src="../nav.js"></script>
   要新增分頁時,在 TABS 加一筆即可(dir 是 site/ 底下的資料夾名稱)。 */
(function () {
  var TABS = [
    { dir: 'trend', label: '台股趨勢雷達', short: '趨勢雷達' },
    { dir: 'dividend', label: '股利估價雷達', short: '股利估價' },
    { dir: 'mpt', label: 'MPT 投資組合', short: 'MPT 組合' }
  ];
  var path = location.pathname.replace(/index\.html$/, '');
  var current = '';
  TABS.forEach(function (t) { if (path.indexOf('/' + t.dir + '/') !== -1) current = t.dir; });

  var css = ''
    + '.tbx-nav{--tbx-bg:#2a2218;--tbx-fg:#e9dfc8;--tbx-mut:#b3a687;--tbx-act:var(--ink,var(--bg,#f3efe6));--tbx-act-fg:var(--text,#2a2420);--tbx-acc:#d2a94f;'
    + 'background:var(--tbx-bg);color:var(--tbx-fg);display:flex;align-items:center;gap:6px;'
    + 'padding:6px max(12px,env(safe-area-inset-left,0px)) 0;font:500 13px/1 "Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;'
    + 'overflow-x:auto;scrollbar-width:none;position:relative;z-index:30}'
    + '.tbx-nav::-webkit-scrollbar{display:none}'
    + '.tbx-brand{flex:none;font-weight:700;letter-spacing:.06em;color:var(--tbx-acc);padding:0 10px 6px 2px;font-size:13px}'
    + '.tbx-nav a{flex:none;color:var(--tbx-mut);text-decoration:none;padding:9px 14px 10px;border-radius:9px 9px 0 0;white-space:nowrap}'
    + '.tbx-nav a:hover{color:var(--tbx-fg);background:rgba(255,255,255,.06)}'
    + '.tbx-nav a[aria-current="page"]{background:var(--tbx-act);color:var(--tbx-act-fg);font-weight:700}'
    + '.tbx-nav a:focus-visible{outline:2px solid var(--tbx-acc);outline-offset:-2px}'
    + '.tbx-nav .s{display:none}'
    + '@media (max-width:520px){.tbx-brand{display:none}.tbx-nav a .l{display:none}.tbx-nav a .s{display:inline}.tbx-nav a{padding:9px 12px 10px}}'
    + '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .tbx-nav{--tbx-bg:#0a0907}}'
    + ':root[data-theme="dark"] .tbx-nav{--tbx-bg:#0a0907}';

  var st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  var nav = document.createElement('nav');
  nav.className = 'tbx-nav';
  nav.setAttribute('aria-label', '台股工具箱');
  var html = '<span class="tbx-brand">台股工具箱</span>';
  TABS.forEach(function (t) {
    html += '<a href="../' + t.dir + '/"' + (t.dir === current ? ' aria-current="page"' : '') + '>'
      + '<span class="l">' + t.label + '</span><span class="s">' + t.short + '</span></a>';
  });
  nav.innerHTML = html;

  var me = document.currentScript;
  if (me && me.parentNode) me.parentNode.insertBefore(nav, me);
  else document.body.insertBefore(nav, document.body.firstChild);
})();
