// site_analytics v1.6.0 i18n dictionary + t()/applyI18n (split from index.html)
var SA_LANG = (function(){ var l = localStorage.getItem('sa_lang'); return (l==='en'||l==='zh') ? l : 'zh'; })();
var I18N_EN = {
'网站流量统计':'Website Analytics',
'概览':'Overview','访客':'Visitors','内容':'Content','性能':'Performance','来源':'Sources','地域':'Geo','实时监控':'Realtime',
'渠道来源':'Traffic sources','地理分布':'Geography',
'刷新':'Refresh','深色':'Dark','浅色':'Light',
'语言':'Language','主题':'Theme','账户':'Account','时间范围':'Time range',
'切换到浅色':'Switch to light theme','切换到深色':'Switch to dark theme',
'+ 添加站点':'+ Add Site','应用':'Apply','至':'to',
'用户管理':'User Management','改密码':'Change Password','退出':'Log out','（管理员）':' (Admin)',
'普通用户':'Viewer','管理员':'Admin','启用':'Active','已停用':'Disabled','停用':'Disable',
'设为管理员':'Make Admin','设为普通':'Make Viewer','重置密码':'Reset Password','（当前登录）':' (current)',
'创建用户':'Create User','普通用户（只读）':'Viewer (read-only)','暂无用户。':'No users yet.',
'用户名（2-32 位）':'Username (2-32 chars)','密码（至少 6 位）':'Password (min 6 chars)',
'普通用户可查看全部分析数据但不能修改任何设置；管理员拥有全部权限。首个注册的账户自动成为管理员。':'Viewers can see all analytics but cannot change anything; admins have full access. The first registered account automatically becomes an admin.',
'操作失败：':'Operation failed: ','创建失败：':'Create failed: ','修改失败：':'Change failed: ',
'确定删除用户「{n}」？':'Delete user "{n}"?','为 {n} 设置新密码（至少 6 位）：':'Set a new password for {n} (min 6 chars):',
'请输入原密码：':'Current password:','请输入新密码（至少 6 位）：':'New password (min 6 chars):','密码已修改。':'Password changed.',
'已创建用户 {n}。':'User {n} created.','请输入用户名与密码':'Please enter username and password','密码至少 6 位':'Password must be at least 6 characters',
'保存保留期':'Save Retention','立即清理过期数据':'Clean Expired Now',
'复制':'Copy','复制埋点代码':'Copy embed code','添加站点':'Add Site','重新生成令牌':'Regenerate token','启用令牌':'Enable token',
'展开已屏蔽访客':'Show blocked visitors','收起已屏蔽访客':'Hide blocked visitors','恢复':'Restore',
'加载中…':'Loading…',
'访问分析摘要':'Traffic Summary',
'访问趋势（浏览量 / 访客）':'Visits Trend (Pageviews / Visitors)',
'访问深度分布（按访问页面数）':'Visit Depth (by pages per visit)',
'站点 / 语言分布（同一主域下各子域，按独立访客）':'Site / Language Distribution',
'新访客 vs 回访客（按区间首次到访）':'New vs Returning (first-seen in period)',
'设备分布':'Device Distribution',
'落地页 TOP（访客首屏页面）':'Top Landing Pages',
'退出页 TOP（访客末屏页面）':'Top Exit Pages',
'页面平均停留时长 TOP（基于离开页上报时长）':'Top Avg. Dwell Time',
'热门页面 TOP':'Top Pages',
'潜在目标访客':'Potential Target Visitors',
'访客会话':'Visitor Sessions',
'浏览器分布':'Browser Distribution',
'其他':'Other',
'全部热门页面（按访问量）':'All Top Pages (by views)',
'页面性能 · Core Web Vitals（区间 75 分位，采集自真实访客浏览器）':'Core Web Vitals (p75, from real visitors)',
'各页面性能（按采样数）':'Per-page Performance (by samples)',
'来源类型分布':'Source Type Distribution',
'来源类型明细（按独立访客）':'Source Types Detail (by unique visitors)',
'具体来源域名 TOP（按独立访客）':'Top Referrer Domains',
'世界地图 · 独立访客热力分布':'World Map · Unique Visitor Heatmap',
'国家 / 地区排行（按独立访客）':'Top Countries / Regions',
'国家 → 城市明细':'Country → City Detail',
'实时访客流':'Realtime Visitors',
'时间窗口':'Time Window',
'站点管理':'Site Management',
'① 复制下面这段通用代码，粘贴到你的网站（如 WP 主题 header 的 <code></head></code> 前）':'① Copy this snippet into your site (e.g. before <code></head></code> in your WP theme header)',
'一段代码即可监控所有语言域名（www / de / fr 等），自动按访问域名区分，无需为每个域名单独部署；并会自动绕过缓存插件本地化，不必逐个站点配 exclude。域名已自动生成为当前看板地址，无需手动替换。':'One snippet monitors all language domains (www / de / fr etc.), auto-separated by visited domain—no per-domain deployment; it also bypasses cache-plugin localization automatically. The domain is auto-filled from the current dashboard URL.',
'要监控的域名，如 example.com（可选）':'Domain to monitor, e.g. example.com (optional)',
'备注名（可选）':'Label (optional)',
'部署上方代码后，访问各域名即会自动出现在站点列表与下拉框中；在此可删除不再需要的站点（含其全部数据）。':'After deploying the code above, each domain auto-appears in the site list and dropdown. You can delete unneeded sites (with all their data) here.',
'② 数据保留策略':'② Data Retention Policy',
'系统会按保留期自动清理超过期限的原始访问事件（启动与运行时执行），以控制数据库体积。默认保留 720 天。':'The system auto-purges raw visit events older than the retention period (on startup and runtime) to control DB size. Default: 720 days.',
'天':'days',
'③ 已屏蔽访客（机房 / 数据中心流量自动排除）':'③ Blocked Visitors (datacenter / hosting traffic auto-excluded)',
'系统会自动排除机房 / 数据中心网络（云主机、托管、CDN 等）的访客，不计入任何统计；其原始数据被保留、可恢复。需要查看或恢复误判时，展开下方列表即可。':'The system auto-excludes visitors from datacenter / hosting networks (cloud, hosting, CDN, etc.) from all stats; their raw data is kept and recoverable. Expand the list below to review or restore false positives.',
'正在获取站点列表…':'Loading site list…',
'暂无站点数据。请先在被统计网页中嵌入 tracker.js 埋点脚本，产生真实访问事件后数据会自动刷新。':'No site data yet. Embed the tracker.js snippet on your pages; data refreshes once real visits occur.',
'获取站点失败：':'Failed to load sites: ',
'今天':'Today','昨天':'Yesterday','过去2天':'Last 2 days','过去7天':'Last 7 days','过去14天':'Last 14 days','过去28天':'Last 28 days','过去60天':'Last 60 days','过去90天':'Last 90 days','自定义日期范围':'Custom range',
'{y}-{m}':'{y}-{m}',
'请选择开始和结束日期':'Please select start and end date',
'正在加载统计数据…':'Loading stats…',
'统计失败：':'Stats failed: ',
'加载失败：':'Load failed: ',
'已暂停':'Paused','自动刷新':'Auto-refresh','自动刷新中（查看访客详情时会自动暂停）':'Auto-refreshing (pauses when viewing visitor details)','自动刷新已暂停（关闭访客详情/弹窗后恢复）':'Auto-refresh paused (resumes after closing details/modal)',
'刷新中…':'Refreshing…',
'独立访客':'Unique Visitors','独立访客: ':'Unique Visitors: ','浏览量（PV）':'Pageviews (PV)','人均页面数':'Pages / Visit','平均停留':'Avg. Duration','跳出率':'Bounce Rate','当前在线':'Online Now',
'浏览量':'Pageviews','访客':'Visitors','浏览量(上期)':'Pageviews (prev)','访客(上期)':'Visitors (prev)',
'暂无子域数据':'No subdomain data','暂无数据':'No data',
'暂无访客数据':'No visitor data',
'落地页':'Landing','退出页':'Exit',
'次数':'Count',
'页面 URL':'Page URL','平均停留':'Avg. Dwell','访问次数':'Views',
'当前周期暂无性能采样数据（需新访客浏览器上报页面性能指标）':'No performance samples this period (requires real visitor browsers to report metrics)',
'FCP':'FCP','LCP':'LCP','TTFB':'TTFB','CLS':'CLS','Speed Index':'Speed Index','Speed Index (估算)':'Speed Index (est.)',
'采样':'Samples',
'性能数据精度说明':'Performance data accuracy',
'FCP/LCP/TTFB/CLS 为真实访客浏览器测量（RUM），头部取 75 分位（p75）；采样少则波动大，请看右上「采样」数。Speed Index 为估算值，非 Lighthouse 实测，请勿作绝对值解读。TTFB 不含建连/TLS/重定向（系统性偏小）；LCP/CLS 在访客短停留时可能偏低。':'FCP/LCP/TTFB/CLS are real-user measurements (RUM), header uses p75; small samples fluctuate, see the Samples count. Speed Index is an estimate, not Lighthouse-measured, do not read as absolute. TTFB excludes connection/TLS/redirect (systematically low); LCP/CLS may be low for short visits.',
'全部':'All','桌面':'Desktop','手机':'Mobile','平板':'Tablet',
'设备':'Device','状态':'Status',
'直接访问':'Direct',
'访客':'Visitor','来路':'Source','设备 / 浏览器':'Device / Browser','运营商':'ISP','地区':'Region','页面':'Pages','停留':'Duration','最近活跃':'Last Active',
'新访客':'New Visitor','回访客':'Returning Visitor',
'疑似数据采集':'Suspected data collection','疑似爬虫/抓取':'Suspected crawler/scraper','浏览量畸高':'High pageviews',
'数据中心/云主机网络，疑似数据采集/抓取':'Datacenter/cloud network, suspected data collection/scraping',
'数据中心/云主机网络且浏览量畸高，疑似数据采集/抓取':'Datacenter/cloud network with abnormally high pageviews, suspected data collection/scraping',
'单访客浏览量畸高，疑似爬虫':'Single visitor with abnormally high pageviews, suspected crawler',
'访问页面（{n} 个不同页面 · 共 {m} 次动作）':'Visited pages ({n} distinct · {m} actions)',
'路径':'Path','最后访问':'Last visit',
'上期':'Prev','日期':'Date','新访客':'New','回访客':'Returning','来源类型':'Source Type','来源域名':'Referrer Domain','访问量':'Pageviews',
'全部来源':'All sources','按来源筛选访客':'Filter visitors by source',
'暂无被屏蔽的访客。':'No blocked visitors.',
'恢复失败：':'Restore failed: ','未知错误':'Unknown error','未知':'Unknown','请求失败，请重试':'Request failed, please retry',
'该窗口内暂无访问记录':'No visits in this window',
'时间':'Time','站点':'Site','PV / 页':'PV / Page',
'近 {n} 分钟 PV':'Last {n} min PV','近 {n} 分钟':'Last {n} min','监听中':'Monitoring','实时':'Live',
'未配置 GeoIP 数据库':'GeoIP database not configured',
'提示：请下载 GeoLite2-City.mmdb 放到 geoip/ 目录并重启 app.py。':'Hint: download GeoLite2-City.mmdb into geoip/ and restart app.py.',
'未安装 maxminddb 库':'maxminddb library not installed',
'提示：pip install maxminddb 后可启用访客地域与运营商(ISP)识别。':'Hint: run "pip install maxminddb" to enable GeoIP and ISP (operator) recognition.',
'所选周期内暂无地域数据':'No geo data in selected period',
'暂无地域数据':'No geo data',
'高':'High','低':'Low',
'提示：GeoIP 已启用，只有加载 GeoIP 之后新产生的访问才会显示地域。':'Hint: GeoIP is enabled; only visits after GeoIP load show regions.',
'颜色越深表示该国家/地区的独立访客越多。仅展示所选周期内有访问的国家。':'Darker = more unique visitors. Only countries with visits in the period are shown.',
'国家 / 地区':'Country / Region','占比':'Share',
'城市数':'Cities',
'下的城市':"'s cities",
'来源筛选：':'Source filter: ','清除筛选':'Clear filter','仅看：':'Showing: ',
'保留天数至少为 30 天':'Retention must be at least 30 days',
'已保存：保留 {n} 天':'Saved: retention {n} days',
'已保存数据保留期为 {n} 天。':'Saved data retention to {n} days.',
'保存失败':'Save failed','保存失败：':'Save failed: ','清理失败：':'Cleanup failed: ',
'已清理 {n} 条过期事件':'Cleaned {n} expired events',
'清理失败':'Cleanup failed',
'还没有手动添加的站点。添加后会自动生成埋点代码，复制嵌入目标网站即可开始统计。':'No manually added sites yet. After adding, the tracking snippet is generated—copy and embed it to start.',
'上移':'Move up','下移':'Move down',
'拖动排序':'Drag to reorder','删除':'Delete','保存排序失败：':'Failed to save order: ',
'请输入要监控的域名':'Please enter the domain to monitor',
'添加失败：':'Add failed: ',
'已添加 {n}，请在弹窗中复制埋点代码嵌入目标网站。':'Added {n}. Copy the tracking snippet from the dialog and embed it.',
'确定删除站点「{n}」及其全部访问数据？\n此操作不可恢复。':'Delete site "{n}" and ALL its visit data? This cannot be undone.',
'已删除站点 {n}（含全部访问数据）。':'Deleted site {n} (with all visit data).',
'删除失败：':'Delete failed: ',
'位':'',' 秒':' sec',' 分 ':' min ',' 时 ':' hr ',' 分':' min',
'访问 URL 含产品页（/product、/products 等）或联系页（contact 等）及其法/德/意/荷/西/日/韩多语种变体的访客，视为潜在目标访客':'Visitors whose URL contains a product page (/product, /products, etc.) or contact page and their multilingual variants (FR/DE/IT/NL/ES/JA/KO) are treated as potential target visitors',
'指标（对齐 PageSpeed Insights 字段数据）：FCP 首次内容绘制、LCP 最大内容绘制、TTFB 首字节时间、CLS 累计布局偏移、Speed Index 速度指数，单位均为秒（CLS 无量纲）。顶部汇总卡采用 75 分位（p75，与 PSI 一致），比均值更抗极端值；下方表格按页面展示均值。颜色阈值：绿=良好 / 黄=需改进 / 红=差。Speed Index 为浏览器端按视觉完成度估算值（非 Lighthouse 逐帧计算），仅供趋势参考。聚合时已过滤大于 60 秒的异常值及大于 2 的 CLS。自动刷新 60 秒一次，展开访客详情/打开弹窗时自动暂停，可点右上角「刷新」手动刷新。':'Metrics (aligned with PageSpeed Insights field data): FCP, LCP, TTFB, CLS, Speed Index, all in seconds (CLS dimensionless). Top cards use the 75th percentile (p75, consistent with PSI), more robust to outliers than the mean; the table shows per-page means. Color thresholds: green=good / yellow=needs improvement / red=poor. Speed Index is a browser-estimated visual-completeness value (not Lighthouse frame-by-frame), for trend reference only. Aggregation filters outliers > 60s and CLS > 2. Auto-refresh every 60s; pauses when expanding visitor details or opening a modal; click "Refresh" (top-right) to refresh manually.',
'说明：以每位访客的「落地来源」（窗口内首条访问的 Referrer）为唯一归属，因此各来源独立访客数之和 = 概览总独立访客数，不会重复计数。':'Note: each visitor is attributed to their landing source (first Referrer in the window) as the unique owner, so the sum of per-source unique visitors equals the overview total, with no double counting.',
'说明：仅当访客来自「带 Referrer」的站点才能识别来源；若对方站点设置了 <code>Referrer-Policy: no-referrer</code> 或浏览器未发送来路，则归为「直接访问」。搜索引擎 / AI 工具 / 社交媒体的识别依赖来路域名，无法穿透无来路的流量——这是所有 first-party 埋点统计的共性。各域名仅展示 TOP 15，其独立访客数之和可能小于总独立访客数。':'Note: a visitor\'s source is only identified when they arrive from a site that sends a Referrer; if the source site sets <code>Referrer-Policy: no-referrer</code> or the browser sends no referrer, it is counted as "Direct". Search engines / AI tools / social media are identified by referrer domain and cannot be detected through refererless traffic—this is common to all first-party analytics. Only the top 15 domains are shown; their unique-visitor sums may be less than the total.',
'仅展示所选窗口内的事件，并按时间倒序（最新在最前）。数据由访客浏览器实时上报。':'Shows only events within the selected window, sorted newest-first. Data is reported in real time by visitor browsers.',
'未获取到站点':'No sites retrieved',
'预设':'Presets','月份':'Month',
'流量异常：当前区间浏览量':'Traffic anomaly: pageviews ',
' 较上一等长区间':' vs previous equal-length period ',
' 增长约':' up ~',
'%，可能为推广活动或异常爬虫，建议核查。':'% — possibly a campaign or bot surge; please verify.',
' 下降约':' down ~',
'%，请关注站点可用性与收录情况。':'% — check site availability and indexing.',
' 个疑似异常':' suspicious',
' 个疑似数据采集':' datacenter/collection',
' 个浏览量畸高':' high-pageview',
'手动屏蔽':'manually blocked',
'清除筛选':'clear',
'来源筛选：':'Source filter: ',
'仅看：':'Showing: ',
'近5分钟':'Last 5 min',
'近10分钟':'Last 10 min','近30分钟':'Last 30 min',
'搜索引擎':'Search Engines','AI 工具':'AI Tools','社交媒体':'Social Media','外部链接':'External Links','直接访问':'Direct',
'④ 潜在目标访客规则':'④ Potential Target Visitor Rules',
'定义哪些被访问页面视为「潜在目标访客」。每行一个路径片段或 * 通配符模式（不区分大小写、已做 URL 解码），命中任一即标记。':'Define which visited pages count as "Potential Target Visitors". One path fragment or * wildcard pattern per line (case-insensitive, URL-decoded); a hit on any marks the visitor.',
'每行一个模式，留空则恢复默认（内置多语种产品/联系页关键词）。':'One pattern per line. Leave empty to restore the default (built-in multilingual product/contact keywords).',
'⑤ 统计时区':'⑤ Statistics Timezone',
'按该时区聚合与展示「自然日 / 小时」维度（影响概览趋势、月份与日期标签）。默认东八区（UTC+8）。':'Aggregation and display of daily/hourly dimensions use this timezone (affects overview trend, months and date labels). Default: UTC+8.',
'时区偏移（小时，相对 UTC，可带小数，范围 -12 ~ +14）':'Timezone offset (hours from UTC, decimals allowed, range -12 ~ +14)',
'保存设置':'Save Settings','已保存设置。':'Settings saved.','恢复默认':'Restore Defaults',
'加载更多':'Load more',
'已重新生成「{n}」的部署令牌，请用新代码重新嵌入。':'Regenerated deploy token for "{n}"; re-embed the new snippet.',
'时区偏移应在 -12 ~ +14 之间':'Timezone offset must be between -12 and +14',
'生成失败：':'Generation failed: ',
'确定重新生成「{n}」的部署令牌？\n生成后须用新代码重新嵌入该站点，旧令牌立即失效。':'Regenerate the deploy token for "{n}"?\nAfter regeneration you must re-embed the new snippet; the old token is immediately invalidated.',
'性能数据来自真实访客浏览器测量（RUM）；指标（对齐 PageSpeed Insights 字段数据）：FCP 首次内容绘制、LCP 最大内容绘制、TTFB 首字节时间、CLS 累计布局偏移、Speed Index 速度指数，单位均为秒（CLS 无量纲）。顶部汇总卡采用 75 分位（p75，与 PSI 一致），比均值更抗极端值；下方表格按页面展示均值。颜色阈值：绿=良好 / 黄=需改进 / 红=差。Speed Index 为浏览器端按视觉完成度估算值（非 Lighthouse 逐帧计算），仅供趋势参考。聚合时已过滤大于 60 秒的异常值及大于 2 的 CLS。TTFB 不含建连/TLS/重定向（系统性偏小）。自动刷新 60 秒一次，展开访客详情/打开弹窗时自动暂停，可点右上角「刷新」手动刷新。':'Perf data is measured by real visitor browsers (RUM). Metrics (aligned with PageSpeed Insights field data): FCP First Contentful Paint, LCP Largest Contentful Paint, TTFB Time To First Byte, CLS Cumulative Layout Shift, Speed Index — all in seconds (CLS dimensionless). Top cards use the 75th percentile (p75, consistent with PSI), more robust to outliers than the mean; the table shows per-page means. Color thresholds: green=good / yellow=needs improvement / red=poor. Speed Index is a browser-estimated visual-completeness value (not Lighthouse frame-by-frame), for trend reference only. Aggregation filters outliers > 60s and CLS > 2. TTFB excludes connection/TLS/redirect (systematically low). Auto-refresh every 60s; pauses when expanding visitor details or opening a modal; click "Refresh" (top-right) to refresh manually.'
};
/* 窄屏短标签（v1.8 顶栏）：时间范围下拉在 ≤760px 时用短文案，保证主控与工具条同排不换行 */
var I18N_SHORT_ZH = {'今天':'今天','昨天':'昨天','过去2天':'2天','过去7天':'7天','过去14天':'14天',
  '过去28天':'28天','过去60天':'60天','过去90天':'90天','自定义日期范围':'自定义'};
var I18N_SHORT_EN = {'今天':'Today','昨天':'Yest.','过去2天':'2d','过去7天':'7d','过去14天':'14d',
  '过去28天':'28d','过去60天':'60d','过去90天':'90d','自定义日期范围':'Custom'};
function ts(k){
  var m = (SA_LANG==='en') ? I18N_SHORT_EN : I18N_SHORT_ZH;
  return (m[k]!=null) ? m[k] : t(k);
}
function t(k, sub){
  var s = (SA_LANG==='en' && I18N_EN[k]!=null) ? I18N_EN[k] : k;
  if(sub!=null){
    if(typeof sub === 'object'){
      for(var p in sub){ if(Object.prototype.hasOwnProperty.call(sub,p)){ s = s.split('{'+p+'}').join(String(sub[p])); } }
    } else {
      s = s.split('{n}').join(String(sub));
    }
  }
  return s;
}
function applyI18n(){
  document.title = t('网站流量统计');
  var nodes = document.querySelectorAll('[data-i18n]');
  for(var i=0;i<nodes.length;i++){ nodes[i].textContent = t(nodes[i].getAttribute('data-i18n')); }
  var attrs = document.querySelectorAll('[data-i18n-attr]');
  for(var j=0;j<attrs.length;j++){
    var el = attrs[j];
    var spec = el.getAttribute('data-i18n-attr').split(';');
    for(var s=0;s<spec.length;s++){
      var kv = spec[s].split(':');
      if(kv.length===2){ el.setAttribute(kv[0].trim(), t(kv[1].trim())); }
    }
  }
  var htmls = document.querySelectorAll('[data-i18n-html]');
  for(var h2=0;h2<htmls.length;h2++){ htmls[h2].innerHTML = t(htmls[h2].getAttribute('data-i18n-html')); }
  var tb = document.getElementById('langToggle');
  if(tb) tb.textContent = (SA_LANG==='en') ? '中' : 'EN';
}
