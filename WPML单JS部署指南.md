# WPML 多语言站点 · 单 JS 部署与监控说明

## 背景
你的网站是用 WPML 实现的一套 WordPress 代码、多个语言域名（www / de / fr.bio-starch.com 等）。
各语言共享同一套主题与模板，因此**不能、也不必为每个语言域分别部署 tracker.js**。

## 核心机制（已支持）
tracker.js 加载时自动读取当前访问的域名：

    SITE = 脚本标签的 data-site 属性 || location.hostname

只要部署时**不写 data-site**，它就用浏览器当前所在的语言域名（如 de.bio-starch.com）作为站点标识上报。
后端对 www / de / fr 等域名按**主域归并展示**：看板下拉框只列出主域（bio-starch.com / hemp-land.com），选中主域后统计自动聚合其下所有子域，并在概览页「站点 / 语言分布」卡片与访客表、实时表的「站点」列中显示各子域（www / de / fr）的明细。这样既不会把几十个子域散成一长串，又能在统计时按语言区分。

## 推荐部署方式：动态注入 loader（一次粘贴，永不需 exclude）
在共享模板放一段极短的内联 loader（复制到 `header.php` 的 `</head>` 前，或通过主题的 `wp_head` 钩子）。
完整可复制片段见 `tracker-loader.html`：

    <script>
    (function () {
      var s = document.createElement('script');
      s.src = 'https://你的分析域名/tracker.js';
      s.defer = true;
      // 多语言/WPML：省略 data-site，tracker 自动按 location.hostname 区分 www/de/fr
      // s.setAttribute('data-site', 'example.com');
      s.setAttribute('data-endpoint', 'https://你的分析域名/api/event');
      document.head.appendChild(s);
    })();
    </script>

每个站点粘贴同一段即可，永久有效，无需去任何缓存插件后台加 exclude。

## 为什么它绕过了缓存插件的本地化
WP 缓存/合并插件（WP Rocket、Autoptimize、W3 Total Cache、WP-Optimize 等）在 **PHP 输出 HTML 阶段**
扫描页面里的 `<script src="...">` 并本地化/合并。本方案规避了这一点：
- 你粘贴的这段是**内联**的，页面初始 HTML 里没有外部 `src`，插件无从下手；
- 远程 tracker.js 是在**浏览器运行时**由 JS 动态创建的 `<script>` 才加载的，插件在输出阶段早已结束，看不到它；
- 显式带 `data-endpoint`，即便极端情况下被改写也不会算错上报地址。

因此一次粘贴、跨插件通用，不必 per-site exclude。

## 备选：完整内联 tracker（最稳，免疫一切）
若个别激进插件（如开启 "Delay JS"）仍拦截运行时 script，可把 `tracker.js` 全文直接内联进 header。
完全脱离外部文件，任何缓存/延迟插件都碰不到。代价：更新 tracker 逻辑时需重新粘贴整段（见 `tracker-loader.html` 底部注释）。

## 监控结果
部署后，看板站点列表会自动出现（各自独立统计：访客、页面、来源、地域等）：
- www.bio-starch.com
- de.bio-starch.com
- fr.bio-starch.com
- （以及其它语言域名）

## 注意事项
- 跨域上报：tracker.js 从 bio-starch.com 上报到分析域名属于跨域请求，后端 /api/event 已配置 CORS，可正常接收。
- 不要为每种语言分别嵌入不同 data-site 的脚本——单 JS 方案即可完成多语言区分。
- 不要在被本地化后的本地路径上依赖自动 ENDPOINT；始终用 loader 显式带 data-endpoint。
- 若将来改用「同一域名 + ?lang=xx 参数」模式（非域名级多语言），需另加 URL 参数识别，当前域名级方案无需处理。
