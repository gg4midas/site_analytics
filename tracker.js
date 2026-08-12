/*
 * 站点流量统计 · 埋点脚本（first-party, 无第三方依赖）
 * 嵌入方式（放在 </body> 前）：
 *   <script src="https://你的分析域名/tracker.js" data-site="example.com" defer></script>
 * 进阶：若脚本被 WP 缓存/合并插件本地化分发，推荐用「动态注入 loader」部署（见 tracker-loader.html
 *      / 部署指南）：运行时创建 <script> 加载远程文件并显式带 data-endpoint，缓存插件在 HTML 输出阶段
 *      看不到外部 src，因此不会本地化，也无需在每个站点的插件里配 exclude。
 *      也可手动指定上报端点：data-endpoint="https://你的分析域名/api/event"
 * 说明：
 *   - 自动从当前页面读取 site（优先取脚本标签 data-site，否则用 location.hostname）
 *   - 多语言/分域名站点（如 WPML 一套代码、www/de/fr 多域名）：只须在共享模板部署一次本脚本、
 *     省略 data-site，tracker 会用当前访问域名(location.hostname)自动区分各语言站点，无需每域各部署一份
 *   - 生成稳定的访客 ID（localStorage，1 年）与会话 ID（sessionStorage）
 *   - 上报 pageview（页面加载 / SPA 路由变更）与 pagehide（含停留时长）
 *   - 真实浏览器才执行 JS，爬虫 / 监控探针绝大多数不会触发，信噪比高
 *   - 可设 data-respect-dnt="true" 尊重浏览器「不跟踪」设置
 */
(function () {
  'use strict';

  // 查找自身脚本标签
  function selfTag() {
    if (document.currentScript) return document.currentScript;
    var s = document.getElementsByTagName('script');
    for (var i = 0; i < s.length; i++) {
      if (/tracker(\.min)?\.js(\?|$)/.test(s[i].src)) return s[i];
    }
    return null;
  }

  var tag = selfTag();
  var SITE = (tag && tag.getAttribute('data-site')) || location.hostname;
  var ENDPOINT = (tag && tag.getAttribute('data-endpoint')) ||
                 (tag ? tag.src.split('/tracker')[0] : location.origin) + '/api/event';
  var RESPECT_DNT = !!(tag && tag.getAttribute('data-respect-dnt') === 'true');
  var DEBUG = !!(tag && tag.getAttribute('data-debug') === 'true');
  if (DEBUG) console.log('[tracker] site=' + SITE + ' endpoint=' + ENDPOINT);

  // 尊重 Do Not Track
  if (RESPECT_DNT && (navigator.doNotTrack === '1' || navigator.doNotTrack === 'yes' ||
      window.doNotTrack === '1')) {
    return;
  }

  // 无头 / 自动化浏览器（双重保险，服务端也会再过滤 UA）
  if (navigator.webdriver) return;

  var VKEY = 'ssa_visitor';
  var SKEY = 'ssa_session';

  function uid() {
    var s = (Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
    var h = 0;
    for (var i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) >>> 0; }
    return h.toString(36) + s;
  }

  // ---- 跨子域共享：把访客/会话 ID 存到主域 cookie，使 www/de/fr 等同一主域下
  //      的不同语言站点能识别为同一访客（localStorage/sessionStorage 按 origin 隔离，
  //      会导致多语言站点把同一真实用户重复计数，UV/会话数虚高）。----
  function cookieDomain() {
    var h = (location.hostname || '').toLowerCase();
    if (h === 'localhost' || /^\d+(\.\d+){3}$/.test(h)) return '';   // 本机/纯 IP 无法跨域共享
    var parts = h.split('.');
    if (parts.length <= 2) return '';                               // 无子域/单标签，无需跨域
    return '.' + parts.slice(-2).join('.');                         // 取注册父域，如 .example.com
  }
  function readCookie(k) {
    var m = document.cookie.match(new RegExp('(?:^|; )' + k + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : '';
  }
  function writeCookie(k, v, maxAge) {
    var d = cookieDomain();
    var s = k + '=' + encodeURIComponent(v) + '; path=/; max-age=' + maxAge +
            '; SameSite=Lax' + (d ? ('; domain=' + d) : '');
    document.cookie = s;
  }

  function getVisitor() {
    try {
      var v = readCookie('ssa_visitor');
      if (v) return v;
      v = uid();
      writeCookie('ssa_visitor', v, 365 * 24 * 3600);   // 1 年，跨子域共享
      try { localStorage.setItem(VKEY, v); } catch (e) {}
      return v;
    } catch (e) { return uid(); }
  }

  function getSession() {
    try {
      var s = readCookie('ssa_session');
      if (s) { writeCookie('ssa_session', s, 1800); return s; }   // 滑动续期 30 分钟
      s = uid();
      writeCookie('ssa_session', s, 1800);
      try { sessionStorage.setItem(SKEY, s); } catch (e) {}
      return s;
    } catch (e) { return uid(); }
  }

  var visitor = getVisitor();
  var session = getSession();
  var startTime = Date.now();

  function send(ev) {
    ev.site = SITE;
    ev.visitor = visitor;
    ev.session = session;
    ev.ts = Date.now();
    ev.ua = navigator.userAgent;
    ev.lang = navigator.language || '';
    ev.screen = (window.screen ? (window.screen.width + 'x' + window.screen.height) : '');
    var body;
    try { body = JSON.stringify(ev); } catch (e) { return; }
    if (DEBUG) console.log('[tracker] send ->', ENDPOINT, ev);
    // 优先 fetch(keepalive)：页面加载初期 sendBeacon 在部分浏览器/隐私扩展下不稳定会丢首屏 pageview
    if (window.fetch) {
      try {
        var pr = fetch(ENDPOINT, { method: 'POST', body: body, headers: { 'Content-Type': 'application/json' }, keepalive: true });
        if (DEBUG && pr && pr.then) {
          pr.then(function (r) { console.log('[tracker] POST status', r.status); })
            .catch(function (e) { console.warn('[tracker] fetch failed, fallback', e); beaconFallback(body, ev); });
        }
        return;
      } catch (e) { /* fallthrough */ }
    }
    beaconFallback(body, ev);
  }

  function beaconFallback(body, ev) {
    // sendBeacon 兜底（卸载时仍可靠）
    if (navigator.sendBeacon) {
      try {
        navigator.sendBeacon(ENDPOINT, new Blob([body], { type: 'application/json' }));
        if (DEBUG) console.log('[tracker] beacon sent');
        return;
      } catch (e) { /* fallthrough */ }
    }
    // Image GET 兜底（字段以 query 传递）
    try {
      var qs = [];
      for (var k in ev) {
        if (ev.hasOwnProperty(k)) qs.push(encodeURIComponent(k) + '=' + encodeURIComponent(ev[k]));
      }
      var img = new Image();
      img.onerror = function () { if (DEBUG) console.warn('[tracker] image beacon failed'); };
      img.src = ENDPOINT + '?' + qs.join('&');
    } catch (e) { /* ignore */ }
  }


  function pageview() {
    send({ type: 'pageview', path: location.pathname + location.search, ref: document.referrer || '' });
  }

  // 首屏上报
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(pageview, 0);
  } else {
    window.addEventListener('DOMContentLoaded', function () { pageview(); });
  }

  // 停留时长上报
  function reportDuration() {
    var dur = Date.now() - startTime;
    if (dur < 0) dur = 0;
    send({ type: 'pagehide', path: location.pathname + location.search, duration: dur });
  }
  window.addEventListener('pagehide', reportDuration);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') reportDuration();
  });

  // SPA 路由变更（history.pushState / replaceState / popstate）
  function hook(h) {
    var orig = history[h];
    if (!orig) return;
    history[h] = function () {
      var r = orig.apply(this, arguments);
      setTimeout(pageview, 0);
      return r;
    };
  }
  hook('pushState'); hook('replaceState');
  window.addEventListener('popstate', function () { setTimeout(pageview, 0); });

  // ---- 页面性能（对齐 PageSpeed Insights 指标：FCP / LCP / TTFB / CLS / Speed Index） ----
  function collectPerf() {
    if (!('performance' in window) || !window.performance || !window.performance.getEntriesByType) return;
    var m = { fcp: 0, lcp: 0, cls: 0, ttfb: 0, speed_index: 0 };
    var nav = null;
    try {
      nav = window.performance.getEntriesByType('navigation')[0];
      if (nav && nav.responseStart && nav.requestStart) m.ttfb = (nav.responseStart - nav.requestStart) / 1000;
    } catch (e) {}
    try {
      if ('PerformanceObserver' in window) {
        try {
          new PerformanceObserver(function (list) {
            var es = list.getEntries();
            for (var i = 0; i < es.length; i++) {
              if (es[i].name === 'first-contentful-paint') m.fcp = es[i].startTime / 1000;
            }
          }).observe({ type: 'paint', buffered: true });
        } catch (e) {}
        try {
          new PerformanceObserver(function (list) {
            var es = list.getEntries();
            if (es.length) m.lcp = es[es.length - 1].startTime / 1000;
          }).observe({ type: 'largest-contentful-paint', buffered: true });
        } catch (e) {}
        try {
          new PerformanceObserver(function (list) {
            var es = list.getEntries();
            for (var i = 0; i < es.length; i++) {
              if (!es[i].hadRecentInput) m.cls += (es[i].value || 0);
            }
          }).observe({ type: 'layout-shift', buffered: true });
        } catch (e) {}
      }
    } catch (e) {}

    // Speed Index 估算：以「视觉完成度曲线下方面积」积分得到（浏览器端无法获取逐帧截图，
    // 用 FCP/LCP/TTFB 作为完成度拐点近似 Lighthouse 的 Speed Index，仅供趋势参考）。
    function computeSpeedIndex() {
      var end = 0;
      try { if (nav && nav.loadEventEnd) end = (nav.loadEventEnd - nav.startTime) / 1000; } catch (e) {}
      if (end <= 0) end = window.performance.now() / 1000;
      if (end <= 0) end = 1;
      var pts = [[0, 0]];
      if (m.ttfb > 0 && m.ttfb < end) pts.push([m.ttfb, 0]);
      if (m.fcp > 0 && m.fcp < end) pts.push([m.fcp, 0.10]);
      if (m.lcp > 0 && m.lcp < end) pts.push([m.lcp, 0.85]);
      pts.push([end, 1]);
      pts.sort(function (a, b) { return a[0] - b[0]; });
      var si = 0;
      for (var j = 1; j < pts.length; j++) {
        var t0 = pts[j - 1][0], v0 = pts[j - 1][1], t1 = pts[j][0], v1 = pts[j][1];
        if (t1 <= t0) continue;
        si += (1 - (v0 + v1) / 2) * (t1 - t0);   // 梯形积分：(1 - 完成度均值) × Δt
      }
      return si;
    }

    var sentFlag = false;
    function sendOnce() {
      if (sentFlag) return;
      sentFlag = true;
      m.speed_index = Math.round(computeSpeedIndex() * 1000) / 1000;
      send({ type: 'perf', path: location.pathname + location.search, meta: JSON.stringify(m) });
    }
    // 页面卸载前发送；若 3 秒内未卸载则主动发一次（捕获 LCP/CLS 终值）
    window.addEventListener('pagehide', sendOnce);
    setTimeout(sendOnce, 3000);
  }
  collectPerf();

  // 暴露调试接口（可选）
  window.__ssa = { site: SITE, visitor: visitor, session: session, endpoint: ENDPOINT };
})();
