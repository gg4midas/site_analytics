# -*- coding: utf-8 -*-
"""
站点流量统计（埋点版 / 不基于日志）
=====================================
通过网页内嵌的轻量 JS 追踪脚本（tracker.js）主动上报真实访客行为，
由真实浏览器执行，天然规避日志中爬虫 / 监控 / 回源等噪音。

启动：python3 app.py --port 8899            # 不鉴权（推荐配合反向代理 + 访问控制）
      python3 app.py --port 8899 --token 你的令牌   # 额外加一层令牌（可选，非必需）
嵌入：<script src="https://你的分析域名/tracker.js" data-site="example.com" defer></script>
面板：http://服务器IP:8899/   （启用令牌时为 http://服务器IP:8899/?token=你的令牌）

特性：
- 零必需第三方依赖（仅 Python 标准库；GeoIP 为可选增强，需 maxminddb + GeoLite2）
- 客户端埋点：PV / 独立访客 / 会话 / 跳出率 / 平均停留时长 / 设备 / 浏览器 / 来路
- 访客地域分布（国家 / 城市，需配置 GeoLite2；缺失则自动禁用，不影响其它功能）
- SQLite 事件存储，按天聚合
- 公开上报端点（/api/event，CORS 开放），查询接口可选 token 鉴权
- 自动剔除 webdriver / 已知爬虫 UA
- 反向代理下通过 X-Forwarded-For / X-Real-IP 还原真实访客 IP
"""
import os
import re
import sys
import json
import sqlite3
import ipaddress
import traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

# GeoIP 为可选能力：安装了 maxminddb 且提供 GeoLite2 mmdb 才启用，否则优雅降级
try:
    import maxminddb
    _HAS_GEO = True
except Exception:
    maxminddb = None
    _HAS_GEO = False

# ======================== 配置 ========================
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DEFAULT_PORT = 8899
DEFAULT_HOST = '127.0.0.1'
DEFAULT_TOKEN = ''
# 版本（供控制台「关于 / 版本」选项读取；发布新版时请同步更新此值，并同步 sa-console.sh 的 CONSOLE_VER）
VERSION = "1.3.2"
# GeoIP 数据库（GeoLite2-City.mmdb，需自行下载；缺失则地理定位自动禁用）
DEFAULT_GEO_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'geoip', 'GeoLite2-City.mmdb')
# ASN 数据库（GeoLite2-ASN.mmdb，用于解析访客运营商/ISP；缺失则运营商识别自动禁用）
DEFAULT_ASN_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'geoip', 'GeoLite2-ASN.mmdb')

# 性能指标归一化 / 异常值过滤阈值（防止 ms 误存或极端值拉偏均值）
_PERF_TIME_KEYS = {'fcp', 'lcp', 'ttfb', 'speed_index'}
_PERF_MAX_TIME = 60.0   # 时间类指标超过 60 秒视为异常，不计入聚合
_PERF_MAX_CLS = 2.0     # CLS 超过 2 视为异常

def _normalize_perf(k, v):
    """把 tracker 上报的性能指标归一化为秒并过滤极端异常值。返回归一化后的值或 None。"""
    if v is None:
        return None
    try:
        v = float(v)
    except (ValueError, TypeError):
        return None
    if v < 0:
        return None
    if k == 'cls':
        if v > _PERF_MAX_CLS:
            return None
        return round(v, 4)
    # 时间类指标：若大于 1000 大概率是按毫秒上报，转为秒
    if v > 1000:
        v = v / 1000.0
    if v > _PERF_MAX_TIME:
        return None
    return round(v, 4)


def _clean_path(p):
    """去掉 URL 查询串(?...) 与片段(#...)，仅保留用于统计 / 展示的路径。"""
    if not p:
        return '/'
    p = str(p).split('?', 1)[0].split('#', 1)[0]
    if not p:
        return '/'
    return p[:300]


# 统计时按路径聚合前，先剥离查询串 / 片段，使带 ?srsltid 等参数的同一页面归并
_CLEAN_PATH_SQL = (
    "CASE WHEN path LIKE '%?%' THEN SUBSTR(path,1,INSTR(path,'?')-1) "
    "WHEN path LIKE '%#%' THEN SUBSTR(path,1,INSTR(path,'#')-1) ELSE path END"
)

# 统计时区：统一按东八区（Asia/Shanghai，UTC+8，中国无夏令时）自然日聚合与展示
TZ_BEIJING = timezone(timedelta(hours=8))

# 已知爬虫 / 采集器 / 监控探针 UA（命中则丢弃上报，双保险）
_BOT_UA_RE = re.compile(
    r'(?:'
    r'bot\b|bot/|robot|spider|crawl|slurp|mediapartners|'
    r'googlebot|bingbot|bingpreview|baiduspider|yandexbot|'
    r'sogou|duckduckbot|duckduckgo|exabot|facebookexternalhit|'
    r'twitterbot|linkedinbot|semrushbot|ahrefsbot|mj12bot|dotbot|'
    r'petalbot|applebot|bytespider|ccbot|gigabot|teoma|'
    r'ia_archiver|archive\.org_bot|seekport|turnitin|'
    r'curl|wget|python-requests|python-urllib|libwww-perl|'
    r'go-http-client|java/|jakarta|okhttp|guzzle|httpx|aiohttp|'
    r'scrapy|httrack|node-fetch|axios|phantomjs|headless|'
    r'pingdom|uptimerobot|statuscake|newrelic|datadog|site24x7|'
    r'gtmetrix|loadimpact|blazemeter|monitor\.|'
    r'whatcms|wappalyzer|builtwith'
    r')',
    re.I
)

# ======================== 来源分类（依赖来路域名） ========================
# 仅当访客来自「带 Referrer」的站点才能识别；对方设 no-referrer 或浏览器未送来路则归为直接访问。
_SEARCH_DOMAINS = {
    'google.com', 'www.google.com', 'bing.com', 'www.bing.com', 'baidu.com', 'www.baidu.com',
    'sogou.com', 'www.sogou.com', 'yahoo.com', 'search.yahoo.com', 'yandex.com', 'yandex.ru',
    'duckduckgo.com', 'ecosia.org', 'ask.com', 'so.com', '360.cn', 'so.360.cn', 'sm.cn',
    'haosou.com', 'brave.com', 'search.brave.com', 'mojeek.com', 'startpage.com', 'searx.be',
    'presearch.com', 'aol.com', 'search.aol.com', 'nanjing.com', 'lycos.com', 'mail.ru',
}
_AI_DOMAINS = {
    'chat.openai.com', 'chatgpt.com', 'openai.com', 'perplexity.ai', 'www.perplexity.ai',
    'claude.ai', 'www.claude.ai', 'anthropic.com', 'copilot.microsoft.com', 'you.com',
    'phind.com', 'gemini.google.com', 'aistudio.google.com', 'poe.com', 'meta.ai',
    'character.ai', 'kimi.moonshot.cn', 'yuanbao.tencent.com', 'doubao.com', 'www.doubao.com',
    'tongyi.aliyun.com', 'qianwen.aliyun.com', 'chatglm.cn', 'zhipuai.cn', 'hunyuan.tencent.com',
    'deepseek.com', 'chat.deepseek.com', 'grok.com', 'metaso.cn', 'fenxiang.cn', 'devv.ai',
    'wisdome.ai', 'coze.cn', '扣子', 'yuanbao.tencent.com',
}
_SOCIAL_DOMAINS = {
    'facebook.com', 'm.facebook.com', 'fb.com', 'twitter.com', 'x.com', 't.co', 'reddit.com',
    'weibo.com', 'weibo.cn', 'zhihu.com', 'www.zhihu.com', 'qq.com', 'qzone.qq.com',
    'telegram.org', 't.me', 'linkedin.com', 'youtube.com', 'youtu.be', 'tiktok.com',
    'douyin.com', 'xiaohongshu.com', 'bilibili.com', 'pinterest.com', 'quora.com', 'vk.com',
    'ok.ru', 'line.me', 'whatsapp.com', 'medium.com', 'substack.com', 'tumblr.com',
    'instagram.com', 'threads.net', 'discord.com', 'douban.com', 'weixin.qq.com', 'mp.weixin.qq.com',
    'tieba.baidu.com', 'juejin.cn', 'csdn.net', 'oschina.net', 'cnblogs.com', 'v2ex.com',
}


class StatEngine(object):
    """事件存储与统计引擎。"""
    def __init__(self, data_dir=DEFAULT_DATA_DIR, geo_db=None, asn_db=None):
        self._data_dir = data_dir
        self._db = os.path.join(data_dir, 'events.db')
        self._log_file = os.path.join(data_dir, 'debug.log')
        self._geo_reader = None
        self._asn_reader = None
        # 本进程内已自动屏蔽（机房/数据中心）的访客缓存，避免重复写入 blocked_visitors
        self._dc_blocked_cache = set()
        os.makedirs(self._data_dir, exist_ok=True)
        self._load_geo(geo_db)
        self._load_asn(asn_db)
        self._init_db()
        # 加载运行时可配置项：潜在目标客户规则、统计时区
        self._inquiry_keywords = self.get_lead_patterns()
        self._build_inquiry_patterns()
        self.reload_timezone()

    # ---------------- 日志 ----------------
    def _log(self, msg):
        try:
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write("[%s] %s\n" % (datetime.now().strftime('%H:%M:%S'), msg))
        except Exception:
            pass

    # ---------------- GeoIP ----------------
    def _load_geo(self, geo_db):
        self._geo_reader = None
        if not _HAS_GEO:
            self._log('GeoIP: 未安装 maxminddb，地理定位已禁用（pip install maxminddb 可启用）')
            return
        if not geo_db or not os.path.isfile(geo_db):
            self._log('GeoIP: 数据库文件不存在（%s），地理定位已禁用' % geo_db)
            return
        try:
            self._geo_reader = maxminddb.open_database(geo_db)
            self._log('GeoIP: 已加载 %s' % geo_db)
        except Exception as e:
            self._log('GeoIP: 加载失败 %s' % e)

    def geo_enabled(self):
        return self._geo_reader is not None

    def resolve_geo(self, ip):
        """返回 {'code','country','city'} 或 None。私有/内网 IP 标记为本地的。
        兼容 MaxMind GeoLite2（country/city 含 names 字典）与 db-ip（含 name 字符串）两种结构。"""
        if not ip:
            return None
        try:
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                return {'code': '', 'country': '(内网/本地)', 'city': ''}
        except ValueError:
            return None
        if not self._geo_reader:
            return None
        try:
            r = self._geo_reader.get(ip)
        except Exception:
            return None
        if not r:
            return None
        country_obj = r.get('country') or {}
        city_obj = r.get('city') or {}
        cc = country_obj.get('iso_code') or ''
        country = self._geo_text(country_obj) or '未知'
        city = self._geo_text(city_obj)
        return {'code': cc, 'country': country, 'city': city}

    @staticmethod
    def _geo_text(obj):
        """从 GeoLite2(names 字典) 或 db-ip(name 字符串) 结构中取名称。"""
        if not obj:
            return ''
        names = obj.get('names')
        if isinstance(names, dict):
            return names.get('zh-CN') or names.get('en') or ''
        return obj.get('name') or ''

    # ---------------- ASN / 运营商（ISP） ----------------
    def _load_asn(self, asn_db):
        self._asn_reader = None
        if not _HAS_GEO:
            return
        if not asn_db or not os.path.isfile(asn_db):
            self._log('ASN: 数据库文件不存在（%s），运营商识别已禁用' % asn_db)
            return
        try:
            self._asn_reader = maxminddb.open_database(asn_db)
            self._log('ASN: 已加载 %s' % asn_db)
        except Exception as e:
            self._log('ASN: 加载失败 %s' % e)

    def asn_enabled(self):
        return self._asn_reader is not None

    def resolve_isp(self, ip):
        """返回 {'isp': 运营商/AS 组织名, 'asn': AS 号}；无法识别返回 {'isp':'', 'asn':0}。
        私有/内网 IP → {'isp':'(内网/本地)', 'asn':0}。兼容 MaxMind GeoLite2-ASN 与 db-ip 结构。"""
        if not ip:
            return {'isp': '', 'asn': 0}
        try:
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                return {'isp': '(内网/本地)', 'asn': 0}
        except ValueError:
            return {'isp': '', 'asn': 0}
        if not self._asn_reader:
            return {'isp': '', 'asn': 0}
        try:
            r = self._asn_reader.get(ip)
        except Exception:
            return {'isp': '', 'asn': 0}
        if not r:
            return {'isp': '', 'asn': 0}
        org = (r.get('autonomous_system_organization')
               or r.get('as_org') or r.get('isp') or r.get('organization') or '')
        isp = org.strip() if isinstance(org, str) else ''
        try:
            asn = int(r.get('autonomous_system_number') or 0)
        except Exception:
            asn = 0
        return {'isp': isp, 'asn': asn}

    # ---------------- 数据库 ----------------
    def _init_db(self):
        try:
            conn = sqlite3.connect(self._db)
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site TEXT, visitor TEXT, session TEXT,
                ts INTEGER, type TEXT, path TEXT, ref TEXT,
                lang TEXT, screen TEXT, duration INTEGER,
                device TEXT, browser TEXT, os TEXT, ua TEXT,
                country_code TEXT, country_name TEXT, city TEXT,
                meta TEXT, isp TEXT, asn INTEGER
            )""")
            # 兼容旧库：补齐地理字段
            for col in ('country_code', 'country_name', 'city'):
                try:
                    c.execute('ALTER TABLE events ADD COLUMN %s TEXT' % col)
                except Exception:
                    pass
            # 兼容旧库：补齐 meta 列（Core Web Vitals 等扩展指标）
            try:
                c.execute('ALTER TABLE events ADD COLUMN meta TEXT')
            except Exception:
                pass
            # 兼容旧库：补齐运营商（ISP）列与 AS 号列
            try:
                c.execute('ALTER TABLE events ADD COLUMN isp TEXT')
            except Exception:
                pass
            try:
                c.execute('ALTER TABLE events ADD COLUMN asn INTEGER')
            except Exception:
                pass
            c.execute("CREATE INDEX IF NOT EXISTS idx_events_site_ts ON events(site, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_events_site_type ON events(site, type)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_events_visitor_ts ON events(visitor, ts)")
            c.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS sites(site TEXT PRIMARY KEY, label TEXT, created INTEGER)")
            # 软屏蔽访客表：确认为异常爬虫后加入，读取统计时排除，但保留原始事件（可恢复）
            c.execute("""CREATE TABLE IF NOT EXISTS blocked_visitors(
                visitor TEXT PRIMARY KEY,
                site TEXT,
                reason TEXT,
                isp TEXT,
                asn INTEGER,
                created INTEGER
            )""")
            try:
                c.execute('ALTER TABLE blocked_visitors ADD COLUMN asn INTEGER')
            except Exception:
                pass
            # 可见事件视图：自动排除已软屏蔽访客的事件，所有站点维度统计读取均走此视图，
            # 原始 events 表保持完整（写入/清理/站点列表仍读写 events）。每次启动重建以匹配最新表结构。
            try:
                c.execute("DROP VIEW IF EXISTS visible_events")
                c.execute(
                    "CREATE VIEW visible_events AS SELECT * FROM events "
                    "WHERE visitor NOT IN (SELECT visitor FROM blocked_visitors)")
            except Exception as e:
                self._log('create visible_events view ERROR: %s' % e)
            conn.commit(); conn.close()
        except Exception as e:
            self._log('_init_db ERROR: %s' % e)

    def _conn(self):
        return sqlite3.connect(self._db)

    # ---------------- UA 解析 ----------------
    @staticmethod
    def parse_ua(ua):
        ua = ua or ''
        if re.search(r'iPad|Tablet|PlayBook|Kindle|Silk|Android(?!.*Mobile)', ua, re.I):
            device = '平板'
        elif re.search(r'Mobile|Android|iPhone|iPod|Windows Phone|BlackBerry', ua, re.I):
            device = '手机'
        else:
            device = '桌面'
        if 'Edg' in ua:
            browser = 'Edge'
        elif 'OPR' in ua or 'Opera' in ua:
            browser = 'Opera'
        elif 'Firefox' in ua:
            browser = 'Firefox'
        elif 'Chrome' in ua and 'Chromium' not in ua:
            browser = 'Chrome'
        elif 'Safari' in ua and 'Chrome' not in ua:
            browser = 'Safari'
        elif 'Trident' in ua or 'MSIE' in ua:
            browser = 'IE'
        else:
            browser = '其他'
        if 'Windows' in ua:
            os_name = 'Windows'
        elif 'Mac OS X' in ua or 'Macintosh' in ua:
            os_name = 'macOS'
        elif 'Android' in ua:
            os_name = 'Android'
        elif 'iPhone OS' in ua or 'CPU iPhone' in ua or 'iPad' in ua:
            os_name = 'iOS'
        elif 'Linux' in ua:
            os_name = 'Linux'
        else:
            os_name = '其他'
        return device, browser, os_name

    @staticmethod
    def is_bot(ua):
        return bool(ua and _BOT_UA_RE.search(ua))

    # 常见数据中心 / 云主机 / 爬虫托管 AS 号（持续补充）
    _DC_ASN = {
        15169,  # Google
        14061, 396982,  # DigitalOcean / Google Cloud
        14618, 16509,  # Amazon AWS
        8075,  # Microsoft
        13335, 199524,  # Cloudflare
        16276,  # OVH
        20473,  # Vultr (Choopa)
        63949,  # Linode
        51167,  # Contabo
        205814,  # Hetzner
        45102,  # Alibaba
        132203,  # Tencent
        38365,  # Baidu
        55990,  # Huawei
        31898,  # Oracle
        54113,  # Fastly (CDN / 边缘)
        9009,   # M247 Europe SRL (hosting / 数据中心，常见爬虫出口)
        203020, # Datacamp Limited (hosting)
        49574, 62240,  # Servers.com
        46475,  # Ace Data Centers
    }
    # 组织名关键词（不区分大小写）——命中即视为数据中心 / 云主机 / 托管网络
    _DC_KEYWORDS = [
        'amazon', 'aws', 'google cloud', 'microsoft', 'azure', 'alibaba',
        'tencent', 'baidu', 'huawei', 'oracle', 'digitalocean', 'linode',
        'vultr', 'ovh', 'hetzner', 'contabo', 'cloudflare', 'akamai',
        'fastly', 'datacamp', 'm247', 'oculus networks', 'servers.com',
        'leaseweb', 'choopa', 'gcore', 'cdn77', 'stackpath', 'limelight',
        'server', 'hosting', 'datacenter', 'data center', 'colocation',
        'cloud', 'cdn', 'vps', 'dedicated', 'static ip', 'edge',
    ]

    def is_data_center_isp(self, isp, asn):
        """判断 ISP / AS 是否属于数据中心、云主机或爬虫托管网络。返回 (是否可疑, 原因)。"""
        if asn and asn in self._DC_ASN:
            return True, 'AS%d 为已知数据中心/云主机网络（疑似数据采集/抓取）' % asn
        if isp:
            low = isp.lower()
            for kw in self._DC_KEYWORDS:
                if kw in low:
                    return True, '运营商「%s」为数据中心/云主机网络（疑似数据采集/抓取）' % isp
        return False, ''

    # ---------------- 东八区时间工具 ----------------
    @staticmethod
    def _bj_day_bounds(date_str):
        """返回东八区(UTC+8)自然日 date_str 的 [start_ms, end_ms) epoch 毫秒。"""
        y, m, d = [int(x) for x in date_str.split('-')]
        start = datetime(y, m, d, 0, 0, 0, tzinfo=TZ_BEIJING)
        end = start + timedelta(days=1)
        return int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    @staticmethod
    def _fmt_bj(ts_ms):
        """epoch 毫秒 -> 东八区 'YYYY-MM-DD HH:MM:SS'。"""
        try:
            return datetime.fromtimestamp(ts_ms / 1000, tz=TZ_BEIJING).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return ''

    @staticmethod
    def _parse_range(range_str, default_days=30):
        """解析前端 range 参数，返回 (start_ms, end_ms, label, granularity)。
        range 格式：
          today | yesterday | 2days | 7days | 14days | 28days | 60days | 90days
          month:YYYY-MM
          custom:YYYY-MM-DD:YYYY-MM-DD
        窗口为东八区自然日；end_ms 对 today 取当前时间，其它取区间结束日 00:00。
        """
        now_bj = datetime.now(TZ_BEIJING)
        today = now_bj.date()
        rs = (range_str or '').strip().lower()
        if rs == 'today':
            s = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_BEIJING).timestamp() * 1000)
            e = int(now_bj.timestamp() * 1000)
            return s, e, '今天', 'hour'
        if rs == 'yesterday':
            d = today - timedelta(days=1)
            s, e = StatEngine._bj_day_bounds(d.isoformat())
            return s, e, '昨天', 'hour'
        if rs == '2days':
            s = StatEngine._bj_day_bounds((today - timedelta(days=1)).isoformat())[0]
            e = int(now_bj.timestamp() * 1000)
            return s, e, '2天之前', 'hour'
        m = re.match(r'^month:(\d{4})-(\d{2})$', rs)
        if m:
            y, mon = int(m.group(1)), int(m.group(2))
            s = datetime(y, mon, 1, 0, 0, 0, tzinfo=TZ_BEIJING)
            if mon == 12:
                e = datetime(y + 1, 1, 1, 0, 0, 0, tzinfo=TZ_BEIJING)
            else:
                e = datetime(y, mon + 1, 1, 0, 0, 0, tzinfo=TZ_BEIJING)
            return int(s.timestamp() * 1000), int(e.timestamp() * 1000), '%d年%d月' % (y, mon), 'day'
        m = re.match(r'^custom:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})$', rs)
        if m:
            sd = datetime.strptime(m.group(1), '%Y-%m-%d').date()
            ed = datetime.strptime(m.group(2), '%Y-%m-%d').date()
            if ed < sd:
                sd, ed = ed, sd
            max_span = 365
            if (ed - sd).days > max_span:
                ed = sd + timedelta(days=max_span)
            s = StatEngine._bj_day_bounds(sd.isoformat())[0]
            if ed == today:
                e = int(now_bj.timestamp() * 1000)
            else:
                e = StatEngine._bj_day_bounds(ed.isoformat())[1]
            label = '%s 至 %s' % (sd.isoformat(), ed.isoformat())
            granularity = 'hour' if (ed - sd).days <= 2 else 'day'
            return s, e, label, granularity
        # 默认按 N days 处理（也兼容旧的 days 参数）
        days = 30
        try:
            days = int(re.sub(r'\D', '', rs) or default_days)
        except Exception:
            days = default_days
        days = max(1, min(days, 365))
        label = '过去%d天' % days
        if rs.startswith('7'):
            label = '过去7天'
        elif rs.startswith('14'):
            label = '过去14天'
        elif rs.startswith('28'):
            label = '过去28天'
        elif rs.startswith('60'):
            label = '过去60天'
        elif rs.startswith('90'):
            label = '过去90天'
        granularity = 'hour' if days <= 2 else 'day'
        dates = [(now_bj - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days - 1, -1, -1)]
        start_ms = StatEngine._bj_day_bounds(dates[0])[0]
        end_ms = int(now_bj.timestamp() * 1000) if days <= 2 else StatEngine._bj_day_bounds(dates[-1])[1]
        return start_ms, end_ms, label, granularity

    @staticmethod
    def _hour_bounds(hour_str):
        """东八区 'YYYY-MM-DD HH' -> [start_ms, end_ms)。"""
        y, m, d, h = [int(x) for x in hour_str.replace('-', ' ').replace(':', ' ').split()]
        start = datetime(y, m, d, h, 0, 0, tzinfo=TZ_BEIJING)
        end = start + timedelta(hours=1)
        return int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    # ---------------- 来源分类 ----------------
    def classify_source(self, ref, site=None):
        """返回 (category, host)。category ∈ search / ai / social / link / direct。
        若 referer 来自当前监控站点自身主域（含任何子域），则视为直接访问。"""
        if not ref:
            return 'direct', ''
        try:
            host = urlparse(ref).hostname or ''
        except Exception:
            host = ''
        host = (host or '').lower()
        if host.startswith('www.'):
            host = host[4:]
        if not host:
            return 'direct', ''
        # 站外来源？如果 referer 与当前站点同属一个主域，视为直接访问
        if site:
            site_root = self._domain_root(site)
            if site_root and self._domain_root(host) == site_root:
                return 'direct', ''
        if host in _AI_DOMAINS:
            return 'ai', host
        if host in _SEARCH_DOMAINS:
            return 'search', host
        if host in _SOCIAL_DOMAINS:
            return 'social', host
        return 'link', host

    # ---------------- 自然搜索词解析 ----------------
    _SEARCH_QUERY_PARAMS = {
        'google.com': 'q', 'www.google.com': 'q', 'bing.com': 'q', 'www.bing.com': 'q',
        'baidu.com': 'wd', 'www.baidu.com': 'wd', 'yahoo.com': 'p', 'search.yahoo.com': 'p',
        'yandex.com': 'text', 'yandex.ru': 'text', 'duckduckgo.com': 'q',
        'sogou.com': 'query', 'www.sogou.com': 'query', 'so.com': 'q', 'so.360.cn': 'q',
        '360.cn': 'q', 'ask.com': 'q', 'aol.com': 'query', 'search.aol.com': 'query',
        'naver.com': 'query', 'search.naver.com': 'query', 'ecosia.org': 'q',
        'brave.com': 'q', 'search.brave.com': 'q', 'presearch.com': 'q',
        'startpage.com': 'query', 'searx.be': 'q', 'mojeek.com': 'q', 'lycos.com': 'query',
        'mail.ru': 'q',
    }

    @staticmethod
    def _search_keyword(ref):
        """从搜索引擎 referer 中解析自然搜索词（依赖 query 参数）。无则返回 ''。"""
        if not ref:
            return ''
        try:
            u = urlparse(ref)
            host = (u.hostname or '').lower()
            if host.startswith('www.'):
                host = host[4:]
            if host not in StatEngine._SEARCH_QUERY_PARAMS:
                return ''
            qp = parse_qs(u.query)
            for cand in (StatEngine._SEARCH_QUERY_PARAMS[host], 'q', 'query', 'text', 'wd', 'p'):
                vals = qp.get(cand)
                if vals and vals[0].strip():
                    return vals[0].strip()[:120]
        except Exception:
            return ''
        return ''

    # ---------------- 潜在询盘访客识别 ----------------
    # 命中关键词：访问 URL 含产品页或联系页（及其多语种变体）任一即视为潜在询盘客户
    # 覆盖 英/法/德/意/荷/西 及 日/韩（罗马音常用形式）对应路径
    _INQUIRY_PATH_KEYWORDS = (
        # 英文
        '/product', 'contact',
        # 法文
        'produit', 'contactez',
        # 德文
        'produkt', 'kontakt',
        # 意大利文（prodott 前缀覆盖 prodotto/prodotti）
        'prodott', 'contatti',
        # 荷兰文
        'producten',
        # 西班牙文
        'producto', 'contacto',
        # 日文（罗马音 + 汉字/平假名原生形式）
        'seihin', 'otoiawase', 'toiawase', '製品', 'お問い合わせ',
        # 韩文（罗马音 + 谚文原生形式）
        'jepum', 'munui', '제품', '문의',
    )

    def _is_potential_inquiry(self, paths):
        """潜在询盘访客：访问 URL 含产品页或联系页（及其多语种变体）任一即命中。

        命中关键词见 self._inquiry_keywords（可在站点管理后台自定义，支持 * 通配符），
        覆盖 英/法/德/意/荷/西 及 日/韩 的 产品(product/produit/produkt/prodotto/
        producto/seihin/jepum 等) 与 联系(contact/kontakt/contatti/contacto/
        otoiawase/munui 等) 路径。子串匹配（不区分大小写，已做 URL 解码），因此
        /fr/products、/de/produkte 等带语言前缀的链接同样命中；同一访客命中任一即
        视为潜在询盘客户。
        """
        if not paths:
            return False
        for p in paths:
            if self._inquiry_path_match(unquote(p or '').lower()):
                return True
        return False

    def _inquiry_path_match(self, low_path):
        """low_path 已 lower() 且 URL 解码。命中 self._inquiry_patterns 中任一即 True。
        self._inquiry_patterns 元素为 (is_regex, pattern)：is_regex=True 时为已编译正则，
        否则为小写子串。"""
        for is_re, pat in getattr(self, '_inquiry_patterns', []):
            if is_re:
                if pat.search(low_path):
                    return True
            elif pat and pat in low_path:
                return True
        return False

    @staticmethod
    def _landing_refs_sql(ph):
        """返回「每位访客落地来源 ref」的查询 SQL（以窗口内首条 pageview 的 referrer 为归属）。
        不依赖 window 函数，兼容旧版 SQLite；同一访客多条首访并列时取 rowid 最小者，结果确定。"""
        return (
            "SELECT t.visitor,"
            " (SELECT ref FROM visible_events v2 WHERE v2.visitor=t.visitor AND v2.site IN (%s)"
            "   AND v2.type='pageview' AND v2.ts>=? AND v2.ts<? ORDER BY v2.ts ASC LIMIT 1) AS ref"
            " FROM (SELECT DISTINCT visitor FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?) t"
        ) % (ph, ph)

    # ---------------- 写入 ----------------
    def add_event(self, ev):
        """ev: dict，字段经校验后入库。返回 True/False。"""
        try:
            site = (ev.get('site') or '').strip().lower()
            if not site:
                return False
            ua = ev.get('ua') or ''
            if self.is_bot(ua):
                return False
            visitor = (ev.get('visitor') or '').strip()
            if not visitor:
                return False
            session = (ev.get('session') or visitor)
            etype = ev.get('type') or 'pageview'
            if etype not in ('pageview', 'pagehide', 'perf'):
                return False
            ts = int(ev.get('ts') or (datetime.now().timestamp() * 1000))
            path = _clean_path(ev.get('path'))
            ref = (ev.get('ref') or '')[:300]
            lang = (ev.get('lang') or '')[:40]
            screen = (ev.get('screen') or '')[:20]
            meta = None
            if etype == 'perf':
                # Core Web Vitals：meta 存 JSON 指标（秒 / 无量纲）
                raw = ev.get('meta') or {}
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except Exception:
                        raw = {}
                if isinstance(raw, dict):
                    clean = {}
                    for k in ('fcp', 'lcp', 'ttfb', 'cls', 'speed_index'):
                        v = _normalize_perf(k, raw.get(k))
                        if v is not None:
                            clean[k] = v
                    if clean:
                        meta = json.dumps(clean, ensure_ascii=False)
                duration = 0
            else:
                try:
                    # tracker 上报为毫秒，统一存储为秒
                    duration = int(round(float(ev.get('duration') or 0) / 1000))
                except (ValueError, TypeError):
                    duration = 0
                if duration < 0:
                    duration = 0
            device, browser, os_name = self.parse_ua(ua)
            ip = ev.get('ip') or ''
            geo = self.resolve_geo(ip)
            cc = (geo or {}).get('code') or ''
            cname = (geo or {}).get('country') or ''
            city = (geo or {}).get('city') or ''
            isp_info = self.resolve_isp(ip)
            isp = isp_info.get('isp') or ''
            asn = isp_info.get('asn') or 0
            # 机房 / 数据中心流量：一旦确认即直接排除（不计入任何统计），无需人工剔除
            if (isp or asn) and visitor not in self._dc_blocked_cache:
                dc, dc_reason = self.is_data_center_isp(isp, asn)
                if dc:
                    self.block_visitor(visitor, site, reason=dc_reason, isp=isp, asn=asn)
                    self._dc_blocked_cache.add(visitor)
            conn = self._conn()
            conn.execute(
                "INSERT INTO events(site,visitor,session,ts,type,path,ref,lang,screen,duration,device,browser,os,ua,country_code,country_name,city,meta,isp,asn) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (site, visitor, session, ts, etype, path, ref, lang, screen, duration, device, browser, os_name, ua[:500], cc, cname, city, meta, isp, asn))
            conn.commit(); conn.close()
            return True
        except Exception as e:
            self._log('add_event ERROR: %s' % e)
            return False

    # ---------------- 读取 ----------------
    def get_sites(self):
        """返回主域去重排序列表（同一主域下的所有子域归并为一个主域条目）。"""
        try:
            conn = self._conn()
            rows = conn.execute("SELECT DISTINCT site FROM events").fetchall()
            seen = set(r[0] for r in rows if r[0])
            mrows = conn.execute("SELECT site FROM sites").fetchall()
            for r in mrows:
                if r[0]:
                    seen.add(r[0])
            conn.close()
            roots = set(self._domain_root(s) for s in seen if s)
            return self._sort_by_order(list(roots))
        except Exception as e:
            self._log('get_sites ERROR: %s' % e)
            return []

    # ---------------- 站点自定义排序 ----------------
    def get_site_order(self):
        """返回用户自定义的主域顺序列表（存于 meta 表）。"""
        try:
            conn = self._conn()
            row = conn.execute("SELECT value FROM meta WHERE key='site_order'").fetchone()
            conn.close()
            if row and row[0]:
                return json.loads(row[0])
        except Exception as e:
            self._log('get_site_order ERROR: %s' % e)
        return []

    def set_site_order(self, order):
        """保存用户自定义的主域顺序（自动归并为主域并去重保序）。"""
        try:
            clean = []
            seen = set()
            for s in (order or []):
                root = self._domain_root(self._normalize_site(s) or '')
                if root and root not in seen:
                    seen.add(root)
                    clean.append(root)
            conn = self._conn()
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('site_order', ?)",
                         (json.dumps(clean),))
            conn.commit(); conn.close()
            return True
        except Exception as e:
            self._log('set_site_order ERROR: %s' % e)
            return False

    def _sort_by_order(self, roots):
        """按用户自定义顺序排序主域列表；未列入顺序的排在后面，按字母序。"""
        order = self.get_site_order()
        idx = {s: i for i, s in enumerate(order)}
        return sorted(roots, key=lambda s: (idx.get(s, len(order)), s))

    def get_months(self, site):
        """返回该站点（主域聚合其下所有子域）有 pageview 数据的月份列表（YYYY-MM，降序）。"""
        if not site:
            return []
        sites = self._sites_under_root(site)
        if not sites:
            return []
        try:
            conn = self._conn()
            ph = ','.join('?' * len(sites))
            secs = int(round((getattr(self, '_tz_offset', 8.0)) * 3600))
            rows = conn.execute(
                "SELECT strftime('%%Y-%%m', datetime(ts/1000, 'unixepoch', '%+d seconds')) AS ym "
                "FROM visible_events WHERE site IN (%s) AND type='pageview' GROUP BY ym ORDER BY ym DESC" % (secs, ph),
                tuple(sites)).fetchall()
            conn.close()
            return [r[0] for r in rows if r[0]]
        except Exception as e:
            self._log('get_months ERROR: %s' % e)
            return []

    # ---------------- 站点注册（手动管理） ----------------
    @staticmethod
    def _normalize_site(s):
        """宽松归一化：保留子域与 www. 前缀、允许单标签（如 test / localhost）。
        仅做「去协议 / 去路径 / 去端口 / 小写」这类无害清洗，不做 www 剥离，
        以免多语言站点（de.example.com 与 www.example.com）被误合并。"""
        s = (s or '').strip()
        if not s:
            return ''
        s = s.lower()
        if s.startswith('//'):
            s = s[2:]
        if '://' in s:
            s = s.split('://', 1)[1]
        for ch in ('/', '?', '#'):
            if ch in s:
                s = s.split(ch, 1)[0]
        if ':' in s:   # 去端口
            s = s.split(':', 1)[0]
        s = s.rstrip('.')
        if not s:
            return ''
        # 允许：单标签（test / localhost）或多级域名（含子域、www）
        if re.match(r'^[a-z0-9-]+(\.[a-z0-9-]+)*$', s) or s == 'localhost':
            return s
        return ''

    @staticmethod
    def _domain_root(s):
        """提取主域：de.example.com -> example.com；www.example.com -> example.com；
        example.com 保持不变；localhost / test 等单标签保持不变。"""
        s = (s or '').strip().lower()
        if not s or s == 'localhost':
            return s
        parts = s.split('.')
        if len(parts) <= 2:
            return s
        return '.'.join(parts[-2:])

    def _sites_under_root(self, root):
        """返回数据库中属于该主域的所有完整域名（含主域本身）。"""
        root = (root or '').strip().lower()
        if not root:
            return []
        try:
            conn = self._conn()
            rows = conn.execute("SELECT DISTINCT site FROM events WHERE site IS NOT NULL AND site<>''").fetchall()
            mrows = conn.execute("SELECT site FROM sites WHERE site IS NOT NULL AND site<>''").fetchall()
            conn.close()
            seen = set()
            for r in rows:
                if r[0]: seen.add(r[0])
            for r in mrows:
                if r[0]: seen.add(r[0])
            result = [s for s in seen if s == root or s.endswith('.' + root)]
            return sorted(result)
        except Exception as e:
            self._log('_sites_under_root ERROR: %s' % e)
            return []
    def add_site(self, site, label=''):
        site = self._normalize_site(site)
        if not site:
            return False, '站点名不合法（应为合法域名，如 example.com）'
        label = (label or '').strip()[:80]
        try:
            conn = self._conn()
            conn.execute(
                "INSERT OR IGNORE INTO sites(site, label, created) VALUES(?,?,?)",
                (site, label, int(datetime.now().timestamp() * 1000)))
            conn.commit(); conn.close()
            return True, site
        except Exception as e:
            return False, str(e)

    def remove_site(self, site):
        site = self._normalize_site(site)
        if not site:
            return False
        root = self._domain_root(site)
        # 删除主域及所有子域（如 example.com + *.example.com）
        try:
            conn = self._conn()
            conn.execute("DELETE FROM sites WHERE site=? OR site LIKE ?", (root, '%.' + root))
            conn.execute("DELETE FROM events WHERE site=? OR site LIKE ?", (root, '%.' + root))
            conn.commit(); conn.close()
            return True
        except Exception:
            return False

    def list_sites(self):
        """返回所有已知站点，按主域归并：子域统一归属到其主域下，只显示主域。"""
        try:
            conn = self._conn()
            label_map = {}
            for r in conn.execute("SELECT site, label FROM sites").fetchall():
                if r[0]:
                    label_map[r[0]] = r[1] or ''
            seen = set(label_map.keys())
            for r in conn.execute("SELECT DISTINCT site FROM events").fetchall():
                if r[0]:
                    seen.add(r[0])
            conn.close()
            # 按主域归并：子域只显示其主域
            roots = {}
            for s in seen:
                root = self._domain_root(s)
                if root not in roots:
                    roots[root] = {'root': root, 'label': label_map.get(root, ''), 'subs': []}
                roots[root]['subs'].append(s)
                # 若主域没有 label，取第一个子域的 label 兜底
                if s != root and not roots[root]['label']:
                    roots[root]['label'] = label_map.get(s, '')
            ordered = self._sort_by_order(list(roots.keys()))
            return [{'site': r, 'label': roots[r]['label']} for r in ordered]
        except Exception:
            return []

    # ---------------- 数据保留 / 清理 ----------------
    def get_retention_days(self, default=720):
        try:
            conn = self._conn()
            row = conn.execute("SELECT value FROM meta WHERE key='retention_days'").fetchone()
            conn.close()
            if row and row[0]:
                d = int(row[0])
                if d >= 1:
                    return d
        except Exception:
            pass
        return default

    def set_retention_days(self, days):
        try:
            days = max(1, int(days))
            conn = self._conn()
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('retention_days', ?)",
                         (str(days),))
            conn.commit(); conn.close()
            return days
        except Exception as e:
            self._log('set_retention_days ERROR: %s' % e)
            return None

    # ---------------- 潜在询盘（潜在目标客户）页面规则 ----------------
    def get_lead_patterns(self):
        """返回潜在目标客户判定用的路径模式列表（支持 * 通配符）。缺省回退到内置多语种关键词。"""
        try:
            conn = self._conn()
            row = conn.execute("SELECT value FROM meta WHERE key='lead_patterns'").fetchone()
            conn.close()
            if row and row[0]:
                lst = json.loads(row[0])
                if isinstance(lst, list) and lst:
                    return [str(x).strip() for x in lst if str(x).strip()]
        except Exception:
            pass
        return list(StatEngine._INQUIRY_PATH_KEYWORDS)

    def set_lead_patterns(self, patterns):
        """保存潜在目标客户路径模式（列表或换行分隔字符串，支持 * 通配符）。空列表则恢复默认。"""
        if patterns is None:
            patterns = []
        if isinstance(patterns, str):
            patterns = patterns.split('\n')
        lst = [str(x).strip() for x in patterns if str(x).strip()]
        try:
            conn = self._conn()
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lead_patterns', ?)",
                         (json.dumps(lst, ensure_ascii=False),))
            conn.commit(); conn.close()
        except Exception as e:
            self._log('set_lead_patterns ERROR: %s' % e)
            return None
        self._inquiry_keywords = lst if lst else list(StatEngine._INQUIRY_PATH_KEYWORDS)
        self._build_inquiry_patterns()
        return self._inquiry_keywords

    def _build_inquiry_patterns(self):
        """将 self._inquiry_keywords 编译为 (is_regex, pattern) 列表。
        含 * 视为通配符：转义其余字符后把 * 替换为 .* 并做正则子串匹配；否则按小写子串匹配。"""
        self._inquiry_patterns = []
        for kw in getattr(self, '_inquiry_keywords', []):
            if '*' in kw:
                try:
                    rx = re.compile(re.escape(kw).replace('\\*', '.*'), re.I)
                    self._inquiry_patterns.append((True, rx))
                except Exception:
                    self._inquiry_patterns.append((False, kw.lower()))
            else:
                self._inquiry_patterns.append((False, kw.lower()))

    # ---------------- 时区（自定义统计时区，默认东八区） ----------------
    def get_timezone_offset(self, default=8.0):
        """返回统计时区相对 UTC 的偏移小时数（浮点，默认 8 = 东八区）。"""
        try:
            conn = self._conn()
            row = conn.execute("SELECT value FROM meta WHERE key='timezone_offset'").fetchone()
            conn.close()
            if row and row[0]:
                v = float(row[0])
                if -12.0 <= v <= 14.0:
                    return v
        except Exception:
            pass
        return default

    def set_timezone_offset(self, off):
        """保存统计时区偏移（小时，浮点），并即时重载内存中的时区。"""
        try:
            off = float(off)
        except (ValueError, TypeError):
            return None
        if off < -12.0 or off > 14.0:
            return None
        conn = self._conn()
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('timezone_offset', ?)",
                     (str(off),))
        conn.commit(); conn.close()
        self.reload_timezone()
        return off

    def reload_timezone(self):
        """从 meta 重载统计时区，更新模块级 TZ_BEIJING 全局与 self._tz_offset。"""
        global TZ_BEIJING
        off = self.get_timezone_offset()
        try:
            TZ_BEIJING = timezone(timedelta(hours=off))
        except Exception:
            TZ_BEIJING = timezone(timedelta(hours=8))
        self._tz_offset = off

    def cleanup_old_events(self, days=None):
        """删除超过保留期的原始事件，返回删除条数。days=None 时取 meta 中的 retention_days。"""
        try:
            if days is None:
                days = self.get_retention_days()
            days = max(1, int(days))
            cutoff = int((datetime.now(TZ_BEIJING) - timedelta(days=days)).timestamp() * 1000)
            conn = self._conn()
            n = conn.execute("SELECT COUNT(*) FROM events WHERE ts < ?", (cutoff,)).fetchone()[0] or 0
            conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            conn.commit(); conn.close()
            self._log('cleanup_old_events: 删除 %d 条（保留 %d 天）' % (n, days))
            return n
        except Exception as e:
            self._log('cleanup_old_events ERROR: %s' % e)
            return 0

    # ---------------- 软屏蔽（异常爬虫访客剔除，可恢复） ----------------
    def block_visitor(self, visitor, site='', reason='', isp='', asn=0):
        """将访客软屏蔽：加入 blocked_visitors。原始事件保留，所有统计读取经视图自动排除。返回 True/False。"""
        visitor = (visitor or '').strip()
        if not visitor:
            return False
        try:
            # 未显式传入 isp/asn 时，尝试从该访客最近一条事件回填，便于屏蔽列表展示
            conn = self._conn()
            if not isp or not asn:
                try:
                    r = conn.execute(
                        "SELECT isp, asn FROM events WHERE visitor=? AND isp IS NOT NULL AND isp<>'' "
                        "ORDER BY ts DESC LIMIT 1", (visitor,)).fetchone()
                    if r and r[0] and not isp:
                        isp = r[0]
                    if r and r[1] and not asn:
                        try:
                            asn = int(r[1])
                        except Exception:
                            asn = 0
                except Exception:
                    pass
            ts = int(datetime.now(TZ_BEIJING).timestamp() * 1000)
            conn.execute(
                "INSERT OR REPLACE INTO blocked_visitors(visitor, site, reason, isp, asn, created) "
                "VALUES(?,?,?,?,?,?)",
                (visitor, (site or '').strip().lower(), (reason or '').strip(), (isp or '').strip(), asn or 0, ts))
            conn.commit(); conn.close()
            self._log('block_visitor: %s (site=%s reason=%s)' % (visitor, site, reason))
            return True
        except Exception as e:
            self._log('block_visitor ERROR: %s' % e)
            return False

    def unblock_visitor(self, visitor):
        """解除访客软屏蔽：从 blocked_visitors 移除，其历史数据重新计入统计。返回 True/False。"""
        visitor = (visitor or '').strip()
        if not visitor:
            return False
        try:
            conn = self._conn()
            conn.execute("DELETE FROM blocked_visitors WHERE visitor=?", (visitor,))
            conn.commit(); conn.close()
            self._log('unblock_visitor: %s' % visitor)
            return True
        except Exception as e:
            self._log('unblock_visitor ERROR: %s' % e)
            return False

    def auto_block_datacenter_visitors(self):
        """启动时回填：将历史事件中属于机房 / 数据中心网络的访客加入 blocked_visitors，
        使其不再计入任何统计（visible_events 视图自动排除）。幂等（INSERT OR REPLACE）。
        返回本次新屏蔽的访客数量。"""
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT DISTINCT visitor, site, isp, asn FROM events "
                "WHERE isp IS NOT NULL AND isp<>'' ").fetchall()
            conn.close()
            n = 0
            for r in rows:
                vid = r[0] or ''
                if not vid or vid in self._dc_blocked_cache:
                    continue
                site_v = r[1] or ''
                isp_v = r[2] or ''
                asn_v = r[3] or 0
                dc, dc_reason = self.is_data_center_isp(isp_v, asn_v)
                if dc:
                    self.block_visitor(vid, site_v, reason=dc_reason, isp=isp_v, asn=asn_v)
                    self._dc_blocked_cache.add(vid)
                    n += 1
            if n:
                self._log('auto_block_datacenter: 回填 %d 个机房/数据中心访客' % n)
            return n
        except Exception as e:
            self._log('auto_block_datacenter ERROR: %s' % e)
            return 0

    def clean_stored_paths(self):
        """启动一次性清洗：将历史事件中带查询串(?...)或片段(#...)的路径归一化为静态路径。
        仅处理部署「查询串剥离」前入库、尚未清洗的旧数据；已干净的数据不会被命中。幂等。
        返回被更新的行数。"""
        try:
            conn = self._conn()
            cur = conn.execute(
                "UPDATE events SET path = CASE "
                "WHEN path LIKE '%?%' THEN SUBSTR(path,1,INSTR(path,'?')-1) "
                "WHEN path LIKE '%#%' THEN SUBSTR(path,1,INSTR(path,'#')-1) "
                "ELSE path END "
                "WHERE path LIKE '%?%' OR path LIKE '%#%'"
            )
            n = cur.rowcount
            conn.commit()
            conn.close()
            if n:
                self._log('clean_stored_paths: 归一化 %d 条含查询串/片段的历史路径' % n)
            return n
        except Exception as e:
            self._log('clean_stored_paths ERROR: %s' % e)
            return 0

    def get_blocked_visitors(self, site=None):
        """返回已软屏蔽访客列表（按屏蔽时间倒序）。site 传入时仅返回该主域下屏蔽记录。"""
        try:
            conn = self._conn()
            if site:
                sites = self._sites_under_root(site)
                if sites:
                    ph = ','.join('?' * len(sites))
                    rows = conn.execute(
                        "SELECT visitor, site, reason, isp, asn, created FROM blocked_visitors "
                        "WHERE site IN (%s) OR site='' ORDER BY created DESC" % ph, tuple(sites)).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT visitor, site, reason, isp, asn, created FROM blocked_visitors "
                        "ORDER BY created DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT visitor, site, reason, isp, asn, created FROM blocked_visitors "
                    "ORDER BY created DESC").fetchall()
            conn.close()
            out = []
            for r in rows:
                out.append({'visitor': r[0], 'site': r[1] or '', 'reason': r[2] or '',
                            'isp': r[3] or '', 'asn': r[4] or 0, 'created': r[5] or 0})
            return out
        except Exception as e:
            self._log('get_blocked_visitors ERROR: %s' % e)
            return []

    def current_online(self, site, minutes=5):
        """返回近 N 分钟活跃的独立访客数（跨该主域下所有子域）。"""
        try:
            sites = self._sites_under_root(site)
            if not sites:
                return 0
            ph = ','.join('?' * len(sites))
            sp = tuple(sites)
            cutoff = int((datetime.now(TZ_BEIJING) - timedelta(minutes=minutes)).timestamp() * 1000)
            conn = self._conn()
            row = conn.execute(
                "SELECT COUNT(DISTINCT visitor) FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=?" % ph,
                sp + (cutoff,)).fetchone()
            conn.close()
            return row[0] or 0
        except Exception as e:
            self._log('current_online ERROR: %s' % e)
            return 0

    def get_stats(self, site, days=30, range_str=None):
        try:
            days = int(days)
        except (ValueError, TypeError):
            days = 30
        days = max(1, min(days, 365))
        if not site:
            return {'error': '缺少站点参数'}
        # 主域聚合其下所有子域（www / de / fr 等），看板按主域归并、统计时一并计入
        sites = self._sites_under_root(site)
        if not sites:
            return {'error': '该站点暂无数据'}
        ph = ','.join('?' * len(sites))
        sp = tuple(sites)
        # ===== 解析时间范围（东八区）=====
        start_ms, end_ms, range_label, granularity = self._parse_range(range_str, days)

        conn = self._conn()
        c = conn.cursor()

        # ===== 趋势数据：按小时或按天 =====
        if granularity == 'hour':
            # 生成从 start 到 end 每个整点
            trend = []
            cur = datetime.fromtimestamp(start_ms / 1000, tz=TZ_BEIJING)
            end_dt = datetime.fromtimestamp(end_ms / 1000, tz=TZ_BEIJING)
            while cur < end_dt:
                hs = cur.strftime('%Y-%m-%d %H')
                h_start, h_end = self._hour_bounds(hs)
                # clamp 到实际 end_ms
                h_end = min(h_end, end_ms)
                row = c.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT visitor) FROM visible_events "
                    "WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?" % ph,
                    sp + (h_start, h_end)).fetchone()
                # 标签：HH:MM 或 MM-DD HH
                label = cur.strftime('%m-%d %H:00') if (end_dt - cur).days > 0 else cur.strftime('%H:00')
                trend.append({'label': label, 'pv': row[0] or 0, 'uv': row[1] or 0})
                cur += timedelta(hours=1)
            daily = trend
        else:
            # 按天聚合（兼容旧字段名 daily）
            dates = []
            cur = datetime.fromtimestamp(start_ms / 1000, tz=TZ_BEIJING)
            end_dt = datetime.fromtimestamp(end_ms / 1000, tz=TZ_BEIJING)
            while cur < end_dt:
                dates.append(cur.strftime('%Y-%m-%d'))
                cur += timedelta(days=1)
            daily = []
            for d in dates:
                d_start, d_end = self._bj_day_bounds(d)
                d_end = min(d_end, end_ms)
                row = c.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT visitor) FROM visible_events "
                    "WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?" % ph,
                    sp + (d_start, d_end)).fetchone()
                daily.append({'date': d, 'pv': row[0] or 0, 'uv': row[1] or 0})

        # 总量
        tot = c.execute(
            "SELECT COUNT(*), COUNT(DISTINCT visitor) FROM visible_events "
            "WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?" % ph,
            sp + (start_ms, end_ms)).fetchone()
        total_pv = tot[0] or 0
        total_uv = tot[1] or 0

        # 会话与跳出率
        bounced = c.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT session FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<? "
            "GROUP BY session HAVING COUNT(*)=1)" % ph, sp + (start_ms, end_ms)).fetchone()[0] or 0
        sessions = c.execute(
            "SELECT COUNT(DISTINCT session) FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?" % ph,
            sp + (start_ms, end_ms)).fetchone()[0] or 0
        bounce = round(100.0 * bounced / sessions, 1) if sessions else 0

        # 平均停留时长（按会话汇总 pagehide.duration）
        avg_row = c.execute(
            "SELECT AVG(d) FROM ("
            "SELECT session, SUM(duration) d FROM visible_events WHERE site IN (%s) AND type='pagehide' AND ts>=? AND ts<? "
            "GROUP BY session)" % ph, sp + (start_ms, end_ms)).fetchone()
        avg_duration = int(round(avg_row[0] or 0))

        def top(tbl_col, lim=15, src_col='path'):
            c.execute(
                "SELECT %s, COUNT(*) c FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<? "
                "GROUP BY %s ORDER BY c DESC LIMIT %d" % (src_col, ph, src_col, lim),
                sp + (start_ms, end_ms))
            return [{'name': r[0] or '(未知)', 'value': r[1]} for r in c.fetchall()]

        # 热门页面：按 (子域, 路径) 分组，剥离查询串，保留各自子域，前端据此拼多语言/带 www 的完整链接
        c.execute(
            "SELECT site, %s, COUNT(*) c FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<? "
            "GROUP BY site, %s ORDER BY c DESC LIMIT 15" % (_CLEAN_PATH_SQL, ph, _CLEAN_PATH_SQL),
            sp + (start_ms, end_ms))
        pages = [{'name': r[1] or '(未知)', 'value': r[2], 'site': r[0] or ''} for r in c.fetchall()]

        def dist(col, lim=8):
            c.execute(
                "SELECT %s, COUNT(DISTINCT visitor) c FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<? "
                "GROUP BY %s ORDER BY c DESC LIMIT %d" % (col, ph, col, lim),
                sp + (start_ms, end_ms))
            return [{'name': r[0] or '其他', 'value': r[1]} for r in c.fetchall()]

        device = dist('device')
        browser = dist('browser')
        os_dist = dist('os')

        # ===== 来源分类：以每位访客「落地来源」（窗口内首条 pageview 的 referrer）为唯一归属，
        #      使各来源独立访客数之和 == 概览总独立访客数（不重复计数）=====
        cat_counter = {}
        dom_counter = {}
        try:
            for r in c.execute(self._landing_refs_sql(ph),
                               sp + (start_ms, end_ms) + sp + (start_ms, end_ms)).fetchall():
                ref = r[1] or ''
                category, host = self.classify_source(ref, site)
                cat_counter[category] = cat_counter.get(category, 0) + 1   # 每位访客计 1
                if host:
                    dom_counter[host] = dom_counter.get(host, 0) + 1
        except Exception as e:
            self._log('get_stats sources ERROR: %s' % e)
        SOURCE_LABELS = {'search': '搜索引擎', 'ai': 'AI 工具', 'social': '社交媒体',
                         'link': '外部链接', 'direct': '直接访问'}
        sources = sorted(
            [{'category': k, 'label': SOURCE_LABELS.get(k, k), 'value': v}
             for k, v in cat_counter.items()],
            key=lambda x: -x['value'])
        referrer = sorted(
            [{'name': k, 'value': v} for k, v in dom_counter.items()],
            key=lambda x: -x['value'])[:15]

        # ===== 子域/语言站点分布（同一主域下各子域名，按独立访客）=====
        subdomains = []
        try:
            c.execute(
                "SELECT site, COUNT(DISTINCT visitor) c FROM visible_events "
                "WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<? "
                "GROUP BY site ORDER BY c DESC" % ph, sp + (start_ms, end_ms))
            subdomains = [{'name': r[0], 'value': r[1]} for r in c.fetchall()]
        except Exception as e:
            self._log('get_stats subdomains ERROR: %s' % e)

        # ===== 地域：国家 -> 城市 从属树 =====
        geo_tree = []
        try:
            country_totals = {}
            c.execute(
                "SELECT country_name, COUNT(DISTINCT visitor) c FROM visible_events "
                "WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<? AND country_name<>'' "
                "GROUP BY country_name" % ph, sp + (start_ms, end_ms))
            for r in c.fetchall():
                country_totals[r[0]] = r[1] or 0
            c.execute(
                "SELECT country_code, country_name, city, COUNT(DISTINCT visitor) c FROM visible_events "
                "WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<? AND country_name<>'' "
                "GROUP BY country_name, city" % ph, sp + (start_ms, end_ms))
            tree = {}
            for r in c.fetchall():
                cc, cname, city, cval = r[0], r[1], r[2], r[3] or 0
                node = tree.setdefault(cname, {'code': cc or '', 'name': cname,
                                               'value': country_totals.get(cname, 0), 'cities': {}})
                if cc and not node['code']:
                    node['code'] = cc
                if city:
                    node['cities'][city] = node['cities'].get(city, 0) + cval
            for cname, node in tree.items():
                cities_sorted = sorted(
                    [{'name': k, 'value': v} for k, v in node['cities'].items() if k],
                    key=lambda x: -x['value'])[:12]
                geo_tree.append({
                    'code': node['code'], 'name': node['name'],
                    'value': node['value'], 'cities': cities_sorted,
                })
            geo_tree.sort(key=lambda x: -x['value'])
        except Exception as e:
            self._log('get_stats geo_tree ERROR: %s' % e)

        # ===== 新访客 vs 回访客（按首次到访时间，相对区间起点）=====
        nr = {'new': 0, 'returning': 0, 'new_pct': 0, 'returning_pct': 0}
        try:
            c.execute(
                "SELECT visitor, MIN(ts) FROM visible_events WHERE site IN (%s) AND visitor IN "
                "(SELECT DISTINCT visitor FROM visible_events WHERE site IN (%s) AND ts>=? AND ts<?) "
                "GROUP BY visitor" % (ph, ph),
                sp + sp + (start_ms, end_ms))
            for r in c.fetchall():
                if (r[1] or 0) < start_ms:
                    nr['returning'] += 1
                else:
                    nr['new'] += 1
            tot_nr = nr['new'] + nr['returning']
            if tot_nr:
                nr['new_pct'] = round(100.0 * nr['new'] / tot_nr, 1)
                nr['returning_pct'] = round(100.0 * nr['returning'] / tot_nr, 1)
        except Exception as e:
            self._log('get_stats new_returning ERROR: %s' % e)

        # ===== 落地页 / 退出页（按会话首/末页面，访客数排名；按 子域+路径 分组，剥离查询串）=====
        landing_pages = []
        exit_pages = []
        try:
            c.execute(
                "SELECT site, cp, COUNT(*) c FROM ("
                "SELECT site, visitor, %s AS cp, ROW_NUMBER() OVER (PARTITION BY visitor ORDER BY ts ASC) rn "
                "FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?"
                ") WHERE rn=1 GROUP BY site, cp ORDER BY c DESC LIMIT 10" % (_CLEAN_PATH_SQL, ph),
                sp + (start_ms, end_ms))
            landing_pages = [{'site': r[0] or '', 'path': r[1] or '/', 'value': r[2]} for r in c.fetchall()]
            c.execute(
                "SELECT site, cp, COUNT(*) c FROM ("
                "SELECT site, visitor, %s AS cp, ROW_NUMBER() OVER (PARTITION BY visitor ORDER BY ts DESC) rn "
                "FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?"
                ") WHERE rn=1 GROUP BY site, cp ORDER BY c DESC LIMIT 10" % (_CLEAN_PATH_SQL, ph),
                sp + (start_ms, end_ms))
            exit_pages = [{'site': r[0] or '', 'path': r[1] or '/', 'value': r[2]} for r in c.fetchall()]
        except Exception as e:
            self._log('get_stats landing/exit ERROR: %s' % e)

        # ===== 访问深度分布（按访客访问的不同页面数分桶）=====
        depth_distribution = []
        try:
            c.execute(
                "SELECT (CASE WHEN np=1 THEN '1' WHEN np BETWEEN 2 AND 3 THEN '2-3' WHEN np BETWEEN 4 AND 6 THEN '4-6' ELSE '7+' END) AS bucket, COUNT(*) c FROM ("
                "SELECT visitor, COUNT(DISTINCT path) np FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<? "
                "GROUP BY visitor) GROUP BY bucket" % ph, sp + (start_ms, end_ms))
            raw_depth = {r[0]: r[1] for r in c.fetchall()}
            depth_distribution = [
                {'bucket': '1', 'value': raw_depth.get('1', 0)},
                {'bucket': '2-3', 'value': raw_depth.get('2-3', 0)},
                {'bucket': '4-6', 'value': raw_depth.get('4-6', 0)},
                {'bucket': '7+', 'value': raw_depth.get('7+', 0)},
            ]
        except Exception as e:
            self._log('get_stats depth ERROR: %s' % e)

        # ===== 页面平均停留时长（pagehide 时长，按 子域+路径 聚合，剥离查询串）=====
        page_dwell = []
        try:
            c.execute(
                "SELECT site, %s, AVG(duration), COUNT(*) FROM visible_events WHERE site IN (%s) AND type='pagehide' AND ts>=? AND ts<? "
                "GROUP BY site, %s HAVING COUNT(*)>=1 ORDER BY COUNT(*) DESC LIMIT 15" % (_CLEAN_PATH_SQL, ph, _CLEAN_PATH_SQL),
                sp + (start_ms, end_ms))
            page_dwell = [{'site': r[0] or '', 'path': r[1] or '/', 'avg': int(round(r[2] or 0)), 'views': r[3]} for r in c.fetchall()]
        except Exception as e:
            self._log('get_stats page_dwell ERROR: %s' % e)

        # ===== 当前在线（近 5 分钟活跃独立访客）=====
        online = self.current_online(site, 5)

        # ===== Core Web Vitals（页面性能，perf 事件聚合，按设备分组）=====
        _PERF_KEYS = ('fcp', 'lcp', 'ttfb', 'cls', 'speed_index')
        perf_overall = {k: 0 for k in _PERF_KEYS}
        perf_pages = []
        perf_by_device = {}

        def _p75(vals):
            if not vals:
                return 0
            s = sorted(vals)
            n = len(s)
            idx = int(0.75 * (n - 1))
            return round(s[idx], 3)

        try:
            c.execute(
                "SELECT site, path, meta, device FROM visible_events WHERE site IN (%s) AND type='perf' AND ts>=? AND ts<?"
                % ph, sp + (start_ms, end_ms))
            all_values = {k: [] for k in _PERF_KEYS}  # 用于计算整体 p75
            perf_event_count = 0
            pacc = {}  # key: (site, path)
            for r in c.fetchall():
                perf_event_count += 1
                site_k = (r[0] or '').strip().lower()
                path = r[1] or '/'
                dev = (r[3] or '未知')
                try:
                    m = json.loads(r[2]) if r[2] else {}
                except Exception:
                    m = {}
                if not isinstance(m, dict):
                    continue
                # 先统一归一化（处理 ms 误存、过滤极端异常值），后续聚合均用归一化后的值
                norm = {k: _normalize_perf(k, m.get(k)) for k in _PERF_KEYS}
                for k in _PERF_KEYS:
                    v = norm[k]
                    if v is not None:
                        all_values[k].append(v)
                sp_key = (site_k, path)
                pa = pacc.setdefault(sp_key, {k: [0, 0] for k in _PERF_KEYS})
                pa['views'] = pa.get('views', 0) + 1
                for k in _PERF_KEYS:
                    v = norm[k]
                    if v is not None:
                        pa[k][0] += v
                        pa[k][1] += 1
                # 按设备分组聚合
                if dev not in perf_by_device:
                    perf_by_device[dev] = {'values': {k: [] for k in _PERF_KEYS}, 'pacc': {}, 'count': 0}
                d = perf_by_device[dev]
                d['count'] += 1
                for k in _PERF_KEYS:
                    v = norm[k]
                    if v is not None:
                        d['values'][k].append(v)
                dpa = d['pacc'].setdefault(sp_key, {k: [0, 0] for k in _PERF_KEYS})
                dpa['views'] = dpa.get('views', 0) + 1
                for k in _PERF_KEYS:
                    v = norm[k]
                    if v is not None:
                        dpa[k][0] += v
                        dpa[k][1] += 1
            # 整体与设备汇总使用 p75（与 PageSpeed Insights 字段数据对齐，比均值更抗极端值）
            perf_overall = {k: _p75(all_values[k]) for k in _PERF_KEYS}
            ptmp = []
            for (sk, path), pa in pacc.items():
                if pa['views'] < 1:
                    continue
                ptmp.append({
                    'site': sk, 'path': path, 'views': pa['views'],
                    'fcp': round(pa['fcp'][0] / pa['fcp'][1], 3) if pa['fcp'][1] else 0,
                    'lcp': round(pa['lcp'][0] / pa['lcp'][1], 3) if pa['lcp'][1] else 0,
                    'ttfb': round(pa['ttfb'][0] / pa['ttfb'][1], 3) if pa['ttfb'][1] else 0,
                    'cls': round(pa['cls'][0] / pa['cls'][1], 3) if pa['cls'][1] else 0,
                    'speed_index': round(pa['speed_index'][0] / pa['speed_index'][1], 3) if pa['speed_index'][1] else 0,
                })
            ptmp.sort(key=lambda x: -x['views'])
            perf_pages = ptmp[:15]
            # 逐设备汇总
            for dev, d in perf_by_device.items():
                dev_pages = []
                for (sk, path), pa in d['pacc'].items():
                    if pa['views'] < 1:
                        continue
                    dev_pages.append({
                        'site': sk, 'path': path, 'views': pa['views'],
                        'fcp': round(pa['fcp'][0] / pa['fcp'][1], 3) if pa['fcp'][1] else 0,
                        'lcp': round(pa['lcp'][0] / pa['lcp'][1], 3) if pa['lcp'][1] else 0,
                        'ttfb': round(pa['ttfb'][0] / pa['ttfb'][1], 3) if pa['ttfb'][1] else 0,
                        'cls': round(pa['cls'][0] / pa['cls'][1], 3) if pa['cls'][1] else 0,
                        'speed_index': round(pa['speed_index'][0] / pa['speed_index'][1], 3) if pa['speed_index'][1] else 0,
                    })
                dev_pages.sort(key=lambda x: -x['views'])
                perf_by_device[dev] = {
                    'summary': {k: _p75(d['values'][k]) for k in _PERF_KEYS},
                    'pages': dev_pages[:15],
                    'count': d['count'],
                }
        except Exception as e:
            self._log('get_stats perf ERROR: %s' % e)

        # ===== 流量异常告警（当前区间 vs 上一等长区间）=====
        anomaly = {'level': 'ok', 'type': '', 'cur_pv': total_pv, 'prev_pv': 0, 'ratio': 0}
        try:
            span = end_ms - start_ms
            if span > 0:
                p_start = start_ms - span
                p_end = start_ms
                prow = c.execute(
                    "SELECT COUNT(*) FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?"
                    % ph, sp + (p_start, p_end)).fetchone()
                prev_pv = prow[0] or 0
                anomaly['prev_pv'] = prev_pv
                if prev_pv > 0 and total_pv > 0:
                    ratio = total_pv / float(prev_pv)
                    anomaly['ratio'] = round(ratio, 2)
                    if ratio >= 1.8:
                        anomaly['level'] = 'warn'
                        anomaly['type'] = 'spike'
                    elif ratio <= 0.55:
                        anomaly['level'] = 'warn'
                        anomaly['type'] = 'drop'
        except Exception as e:
            self._log('get_stats anomaly ERROR: %s' % e)

        # ===== 上一周期对比（环比）：本期 vs 上一个等长周期 =====
        prev = {'pv': 0, 'uv': 0, 'sessions': 0, 'bounce': 0.0,
                'avg_duration': 0, 'ppv': 0.0, 'daily_prev': []}
        try:
            span = end_ms - start_ms
            p_start = start_ms - span
            p_end = start_ms

            def _bounds_list(gran, s_ms, e_ms):
                out = []
                if gran == 'hour':
                    cur = datetime.fromtimestamp(s_ms / 1000, tz=TZ_BEIJING)
                    endd = datetime.fromtimestamp(e_ms / 1000, tz=TZ_BEIJING)
                    while cur < endd:
                        out.append(self._hour_bounds(cur.strftime('%Y-%m-%d %H')))
                        cur += timedelta(hours=1)
                else:
                    cur = datetime.fromtimestamp(s_ms / 1000, tz=TZ_BEIJING)
                    endd = datetime.fromtimestamp(e_ms / 1000, tz=TZ_BEIJING)
                    while cur < endd:
                        out.append(self._bj_day_bounds(cur.strftime('%Y-%m-%d')))
                        cur += timedelta(days=1)
                return out

            daily_prev = []
            for (b0, b1) in _bounds_list(granularity, p_start, p_end):
                row = c.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT visitor) FROM visible_events "
                    "WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?" % ph,
                    sp + (b0, b1)).fetchone()
                daily_prev.append({'pv': row[0] or 0, 'uv': row[1] or 0})
            p_tot = c.execute(
                "SELECT COUNT(*), COUNT(DISTINCT visitor) FROM visible_events "
                "WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?" % ph,
                sp + (p_start, p_end)).fetchone()
            prev_pv = p_tot[0] or 0
            prev_uv = p_tot[1] or 0
            p_bounced = c.execute(
                "SELECT COUNT(*) FROM (SELECT session FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<? "
                "GROUP BY session HAVING COUNT(*)=1)" % ph, sp + (p_start, p_end)).fetchone()[0] or 0
            p_sessions = c.execute(
                "SELECT COUNT(DISTINCT session) FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?" % ph,
                sp + (p_start, p_end)).fetchone()[0] or 0
            prev_bounce = round(100.0 * p_bounced / p_sessions, 1) if p_sessions else 0
            p_avg = c.execute(
                "SELECT AVG(d) FROM (SELECT session, SUM(duration) d FROM visible_events WHERE site IN (%s) AND type='pagehide' AND ts>=? AND ts<? "
                "GROUP BY session)" % ph, sp + (p_start, p_end)).fetchone()
            prev_avg = int(round(p_avg[0] or 0))
            prev['pv'] = prev_pv
            prev['uv'] = prev_uv
            prev['sessions'] = p_sessions
            prev['bounce'] = prev_bounce
            prev['avg_duration'] = prev_avg
            prev['ppv'] = round(prev_pv / prev_uv, 2) if prev_uv else 0
            prev['daily_prev'] = daily_prev
        except Exception as e:
            self._log('get_stats prev ERROR: %s' % e)

        conn.close()
        return {
            'site': site, 'root': self._domain_root(site), 'sites': sites,
            'days': days, 'range_label': range_label, 'granularity': granularity,
            'daily': daily,
            'total_pv': total_pv, 'total_uv': total_uv, 'total_sessions': sessions,
            'bounce': bounce, 'avg_duration': avg_duration,
            'pages': pages, 'referrer': referrer, 'sources': sources,
            'subdomains': subdomains,
            'device': device, 'browser': browser, 'os': os_dist,
            'geo_tree': geo_tree, 'countries': geo_tree,
            'geo_enabled': self.geo_enabled(),
            # 新增指标
            'online': online,
            'new_returning': nr,
            'landing_pages': landing_pages,
            'exit_pages': exit_pages,
            'depth_distribution': depth_distribution,
            'page_dwell': page_dwell,
            'perf_overall': perf_overall,
            'perf_count': perf_event_count,
            'perf_pages': perf_pages,
            'perf_by_device': perf_by_device,
            'anomaly': anomaly,
            'prev': prev,
        }

    def get_visitors(self, site, days=30, range_str=None, visitor_limit=200, event_limit=3000,
                     source=None, refdomain=None, inquiry=None):
        """按访客聚合其动作序列（Clicky 风格访客会话）。source=来源类型(search/ai/social/link/direct)，refdomain=来源域名（host）。"""
        try:
            days = int(days)
        except (ValueError, TypeError):
            days = 30
        days = max(1, min(days, 365))
        visitor_limit = max(1, min(int(visitor_limit or 200), 500))
        event_limit = max(1, min(int(event_limit or 3000), 10000))
        if not site:
            return {'visitors': [], 'total_visitors': 0, 'inquiry_count': 0, 'suspect_count': 0}
        sites = self._sites_under_root(site)
        if not sites:
            return {'visitors': [], 'total_visitors': 0, 'inquiry_count': 0, 'suspect_count': 0}
        ph = ','.join('?' * len(sites))
        sp = tuple(sites)
        start_ms, end_ms, _, _ = self._parse_range(range_str, days)
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT ts, visitor, session, type, path, ref, device, browser, os, "
                "country_code, country_name, city, duration, site, isp, asn "
                "FROM visible_events WHERE site IN (%s) AND type IN ('pageview','pagehide','perf') AND ts>=? AND ts<? ORDER BY ts DESC LIMIT ?" % ph,
                sp + (start_ms, end_ms, event_limit)).fetchall()
            # ===== 真实独立访客总数 / 询盘访客总数：全周期 SQL 统计，覆盖 3000 事件截断与 200 分页限制 =====
            total_visitors = 0
            inquiry_count_full = 0
            try:
                # 询盘访客集合：与 _is_potential_inquiry 口径一致（URL 解码后子串/通配符匹配，含 CJK），全周期
                dist_paths = conn.execute(
                    "SELECT DISTINCT visitor, %s FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?" % (_CLEAN_PATH_SQL, ph),
                    sp + (start_ms, end_ms)).fetchall()
                inquiry_vis = set()
                _seen = set()
                for vid, p in dist_paths:
                    k = (vid, p)
                    if k in _seen:
                        continue
                    _seen.add(k)
                    if self._inquiry_path_match(unquote(p or '').lower()):
                        inquiry_vis.add(vid)
                inquiry_count_full = len(inquiry_vis)

                if source or refdomain or inquiry:
                    # 仅统计满足筛选条件的独立访客（落地来源归属 + 询盘命中）
                    matched = 0
                    for r in conn.execute(self._landing_refs_sql(ph),
                                       sp + (start_ms, end_ms) + sp + (start_ms, end_ms)).fetchall():
                        vid = r[0]
                        if inquiry and vid not in inquiry_vis:
                            continue
                        cat, host = self.classify_source(r[1] or '', site)
                        if source and cat != source:
                            continue
                        if refdomain and host != (refdomain or '').lower():
                            continue
                        matched += 1
                    total_visitors = matched
                else:
                    total_visitors = conn.execute(
                        "SELECT COUNT(DISTINCT visitor) FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=? AND ts<?" % ph,
                        sp + (start_ms, end_ms)).fetchone()[0] or 0
            except Exception as e:
                self._log('get_visitors total_visitors ERROR: %s' % e)
                total_visitors = len(buckets)
                inquiry_count_full = sum(1 for b in buckets.values() if b.get('is_inquiry'))
            inquiry_count = inquiry_count_full
            conn.close()
            buckets = {}
            for r in rows:
                vid = r[1] or '(未知)'
                b = buckets.get(vid)
                if b is None:
                    b = {
                        'visitor': vid,
                        'first_time': r[0],
                        'last_time': r[0],
                        'country': r[10] or '',
                        'cc': r[9] or '',
                        'city': r[11] or '',
                        'device': r[6] or '桌面',
                        'browser': r[7] or '其他',
                        'os': r[8] or '',
                        'site': r[13] or '',
                        'isp': r[14] or '',
                        'asn': r[15] or 0,
                        'referer': r[5] or '',
                        'pv': 0,
                        'duration_total': 0,
                        'event_count': 0,
                        'pages': {},
                        'hide_pages': {},
                    }
                    buckets[vid] = b
                ts = r[0]
                if ts < b['first_time']:
                    b['first_time'] = ts
                if ts > b['last_time']:
                    b['last_time'] = ts
                    # 以最新一条的地理/设备信息为准
                    if r[10]:
                        b['country'] = r[10]
                    if r[9]:
                        b['cc'] = r[9]
                    if r[11]:
                        b['city'] = r[11]
                    if r[6]:
                        b['device'] = r[6]
                    if r[7]:
                        b['browser'] = r[7]
                    if r[8]:
                        b['os'] = r[8]
                    if r[13]:
                        b['site'] = r[13]
                    if r[14]:
                        b['isp'] = r[14]
                    if r[15]:
                        b['asn'] = r[15]
                if r[3] == 'pageview':
                    b['pv'] += 1
                    path = _clean_path(r[4])
                    p = b['pages'].get(path)
                    if p is None:
                        p = {'count': 0, 'first_ms': ts, 'last_ms': ts}
                        b['pages'][path] = p
                    p['count'] += 1
                    if ts > p['last_ms']:
                        p['last_ms'] = ts
                    if ts < p['first_ms']:
                        p['first_ms'] = ts
                    if path in b['hide_pages']:
                        del b['hide_pages'][path]
                elif r[3] == 'pagehide':
                    path = _clean_path(r[4])
                    if path not in b['pages']:
                        p = b['hide_pages'].get(path)
                        if p is None:
                            p = {'count': 0, 'first_ms': ts, 'last_ms': ts}
                            b['hide_pages'][path] = p
                        p['count'] += 1
                        if ts > p['last_ms']:
                            p['last_ms'] = ts
                        if ts < p['first_ms']:
                            p['first_ms'] = ts
                b['duration_total'] += int(r[12] or 0)
                b['event_count'] += 1
                if r[5] and not b['referer']:
                    b['referer'] = r[5]
            # ===== 按来源类型 / 来源域名筛选（点击来源明细时触发）=====
            # 自身域名引荐归并为直接访问
            for b in buckets.values():
                if b.get('referer'):
                    cat, _ = self.classify_source(b['referer'], site)
                    if cat == 'direct':
                        b['referer'] = ''
            if source or refdomain:
                def _match(b):
                    cat, host = self.classify_source(b.get('referer') or '', site)
                    if source and cat != source:
                        return False
                    if refdomain and host != (refdomain or '').lower():
                        return False
                    return True
                buckets = {k: b for k, b in buckets.items() if _match(b)}
            # 构建「不同页面」去重列表（按最后访问时间倒序），单日内同一访客不重复建、只累加不同页面的访问动作
            for b in buckets.values():
                plist = []
                all_paths = dict(b['pages'])
                for path, p in b['hide_pages'].items():
                    if path not in all_paths:
                        all_paths[path] = p
                for path, p in all_paths.items():
                    plist.append({'path': path, 'count': p['count'],
                                  'site': b['site'], 'first_ms': p['first_ms'], 'last_ms': p['last_ms']})
                plist.sort(key=lambda x: x['last_ms'], reverse=True)
                for p in plist:
                    p['first_time'] = self._fmt_bj(p['first_ms'])
                    p['last_time'] = self._fmt_bj(p['last_ms'])
                    del p['first_ms']
                    del p['last_ms']
                b['pages_list'] = plist
                b['pages_count'] = len(plist)
                # 潜在询盘访客标识：访问过产品页且访问过联系页
                b['is_inquiry'] = self._is_potential_inquiry(list(all_paths.keys()))
            # ===== 异常访客标注：多条件组合（支持多选）=====
            # 1) 单访客浏览量畸高：以全体访客 PV 中位数为基准，PV ≥ 中位数×倍数 且 ≥ 绝对下限。
            # 2) 数据中心/云主机/爬虫托管 ISP：命中已知 AS 号或组织名关键词。
            # 仅在样本量足够时启用 PV 规则，避免早期小数据误报。中位数对少数畸高值稳健。
            SUSPECT_FACTOR = 8       # 高于中位数的倍数阈值
            SUSPECT_MIN_PV = 30      # 绝对 PV 下限（低于此不标注，避免误伤正常深度浏览）
            pv_values = sorted(b['pv'] for b in buckets.values())
            suspect_count = 0
            suspect_dc_count = 0
            suspect_highpv_count = 0
            if len(pv_values) >= 5:
                n = len(pv_values)
                median_pv = (pv_values[n // 2] if n % 2 else (pv_values[n // 2 - 1] + pv_values[n // 2]) / 2.0)
                threshold = max(SUSPECT_MIN_PV, median_pv * SUSPECT_FACTOR)
            else:
                threshold = None
            for b in buckets.values():
                reasons = []
                is_highpv = (threshold is not None and b['pv'] >= threshold)
                if is_highpv:
                    reasons.append('单访客浏览量畸高：%d 次，约为全站中位数(%.0f)的 %.1f 倍'
                                   % (b['pv'], median_pv, (b['pv'] / median_pv) if median_pv else 0))
                dc, dc_reason = self.is_data_center_isp(b.get('isp') or '', b.get('asn') or 0)
                if dc:
                    reasons.append(dc_reason)
                if reasons:
                    b['suspicious'] = True
                    if is_highpv and dc:
                        b['suspect_type'] = 'both'
                    elif dc:
                        b['suspect_type'] = 'datacenter'
                    else:
                        b['suspect_type'] = 'high_pv'
                    b['suspect_reason'] = '；'.join(reasons)
                    suspect_count += 1
                    if b['suspect_type'] in ('datacenter', 'both'):
                        suspect_dc_count += 1
                    if b['suspect_type'] in ('high_pv', 'both'):
                        suspect_highpv_count += 1
                else:
                    b['suspicious'] = False
                    b['suspect_type'] = ''
                    b['suspect_reason'] = ''
            # 仅看潜在询盘访客
            if inquiry:
                buckets = {k: b for k, b in buckets.items() if b.get('is_inquiry')}
            # 按最后活跃时间倒序，取前 N 个访客
            result = sorted(buckets.values(), key=lambda x: x['last_time'], reverse=True)[:visitor_limit]
            for b in result:
                b['first_time'] = self._fmt_bj(b['first_time'])
                b['last_time'] = self._fmt_bj(b['last_time'])
                b['duration_text'] = self._fmt_duration(b['duration_total'])
                b['duration_total'] = int(b.get('duration_total') or 0)
                b['actions_count'] = b['event_count']
                b['pv'] = b['pv'] + len(b.get('hide_pages', {}))
                b['pages_count'] = b.get('pages_count', len(b.get('pages_list', [])))
                b.pop('pages', None)
                b.pop('event_count', None)
                b.pop('hide_pages', None)
            return {'visitors': result, 'total_visitors': total_visitors, 'inquiry_count': inquiry_count,
                    'suspect_count': suspect_count,
                    'suspect_dc_count': suspect_dc_count,
                    'suspect_highpv_count': suspect_highpv_count}
        except Exception as e:
            self._log('get_visitors ERROR: %s' % e)
            return {'visitors': [], 'total_visitors': 0, 'inquiry_count': 0, 'suspect_count': 0}

    @staticmethod
    def _fmt_duration(sec):
        sec = int(sec or 0)
        if sec < 60:
            return '%d 秒' % sec
        if sec < 3600:
            return '%d 分 %d 秒' % (sec // 60, sec % 60) if sec % 60 else '%d 分' % (sec // 60)
        return '%d 时 %d 分' % (sec // 3600, (sec % 3600) // 60) if (sec % 3600) // 60 else '%d 时' % (sec // 3600)

    def get_recent(self, site, window_minutes=10, limit=500, source=None, refdomain=None):
        """返回指定时间窗口（默认近10分钟）内的最近事件，按时间倒序。source/refdomain 可筛选来源。"""
        try:
            window_minutes = int(window_minutes)
        except (ValueError, TypeError):
            window_minutes = 10
        window_minutes = max(1, min(window_minutes, 1440))
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            limit = 500
        limit = max(1, min(limit, 1000))
        if not site:
            return []
        sites = self._sites_under_root(site)
        if not sites:
            return []
        ph = ','.join('?' * len(sites))
        sp = tuple(sites)
        try:
            now_bj = datetime.now(TZ_BEIJING)
            end_ms = int(now_bj.timestamp() * 1000)
            start_ms = int((now_bj - timedelta(minutes=window_minutes)).timestamp() * 1000)
            conn = self._conn()
            rows = conn.execute(
                "SELECT ts, visitor, path, ref, device, duration, type, country_code, country_name, site, isp, asn FROM visible_events "
                "WHERE site IN (%s) AND type IN ('pageview','pagehide') AND ts>=? AND ts<=? ORDER BY ts DESC LIMIT ?" % ph,
                sp + (start_ms, end_ms, max(limit * 5, 1000))).fetchall()
            online = 0
            try:
                cutoff5 = int((now_bj - timedelta(minutes=5)).timestamp() * 1000)
                orow = conn.execute(
                    "SELECT COUNT(DISTINCT visitor) FROM visible_events WHERE site IN (%s) AND type='pageview' AND ts>=?" % ph,
                    sp + (cutoff5,)).fetchone()
                online = orow[0] or 0
            except Exception:
                pass
            conn.close()
            # 按访客聚合：单日内同一访客只出现一次，只在访客内累加其访问过的不同页面
            buckets = {}
            for r in rows:
                vid = r[1] or '(未知)'
                b = buckets.get(vid)
                if b is None:
                    b = {
                        'visitor': vid, 'site': r[9] or '', 'referer': r[3] or '',
                        'device': r[4] or '桌面', 'cc': r[7] or '', 'country': r[8] or '',
                        'isp': r[10] or '', 'asn': r[11] or 0,
                        'first_ms': r[0], 'last_ms': r[0], 'pv': 0, 'duration_total': 0,
                        'pages': {}, 'hide_pages': {},
                    }
                    buckets[vid] = b
                ts = r[0]
                if ts < b['first_ms']:
                    b['first_ms'] = ts
                if ts > b['last_ms']:
                    b['last_ms'] = ts
                    if r[9]:
                        b['site'] = r[9]
                    if r[4]:
                        b['device'] = r[4]
                    if r[7]:
                        b['cc'] = r[7]
                    if r[8]:
                        b['country'] = r[8]
                    if r[10]:
                        b['isp'] = r[10]
                    if r[11]:
                        b['asn'] = r[11]
                if r[6] == 'pageview':
                    b['pv'] += 1
                    path = _clean_path(r[2])
                    b['pages'][path] = b['pages'].get(path, 0) + 1
                    if path in b['hide_pages']:
                        del b['hide_pages'][path]
                elif r[6] == 'pagehide':
                    b['duration_total'] += int(r[5] or 0)
                    path = _clean_path(r[2])
                    if path not in b['pages']:
                        b['hide_pages'][path] = b['hide_pages'].get(path, 0) + 1
            # ===== 按来源类型 / 来源域名筛选 =====
            # 自身域名引荐归并为直接访问
            for b in buckets.values():
                if b.get('referer'):
                    cat, _ = self.classify_source(b['referer'], site)
                    if cat == 'direct':
                        b['referer'] = ''
            if source or refdomain:
                def _match(b):
                    cat, host = self.classify_source(b.get('referer') or '', site)
                    if source and cat != source:
                        return False
                    if refdomain and host != (refdomain or '').lower():
                        return False
                    return True
                buckets = {k: b for k, b in buckets.items() if _match(b)}
            # 实时访客也标注数据中心 ISP / 疑似数据采集
            for b in buckets.values():
                dc, dc_reason = self.is_data_center_isp(b.get('isp') or '', b.get('asn') or 0)
                if dc:
                    b['suspicious'] = True
                    b['suspect_type'] = 'datacenter'
                    b['suspect_reason'] = dc_reason
                else:
                    b['suspicious'] = False
                    b['suspect_type'] = ''
                    b['suspect_reason'] = ''
            out = []
            for b in buckets.values():
                all_pages = dict(b['pages'])
                for path, cnt in b['hide_pages'].items():
                    if path not in all_pages:
                        all_pages[path] = cnt
                plist = sorted(all_pages.items(), key=lambda x: -x[1])
                current_path = _clean_path(plist[0][0]) if plist else '/'
                out.append({
                    'visitor': b['visitor'],
                    'site': b['site'],
                    'referer': b['referer'] or None,
                    'device': b['device'],
                    'cc': b['cc'],
                    'country': b['country'],
                    'isp': b.get('isp') or '',
                    'suspicious': b.get('suspicious') or False,
                    'suspect_reason': b.get('suspect_reason') or '',
                    'first_time': self._fmt_bj(b['first_ms']),
                    'last_time': self._fmt_bj(b['last_ms']),
                    'pv': b['pv'] + len(b['hide_pages']),
                    'pages_count': len(all_pages),
                    'current_path': current_path,
                    'duration_text': self._fmt_duration(b['duration_total']),
                    'duration_total': int(b.get('duration_total') or 0),
                })
            out.sort(key=lambda x: x['last_time'], reverse=True)
            return {'rows': out[:limit], 'online': online}
        except Exception as e:
            self._log('get_recent ERROR: %s' % e)
            return {'rows': [], 'online': 0}
class Handler(BaseHTTPRequestHandler):
    engine = None
    token = DEFAULT_TOKEN
    www_root = None

    def _send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        if not getattr(self, '_head_mode', False):
            self.wfile.write(data)

    def _send_file(self, path, content_type):
        try:
            with open(path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            if not getattr(self, '_head_mode', False):
                self.wfile.write(data)
        except Exception:
            self.send_error(404)

    def _check_token(self, query):
        if not self.token:
            return True
        return query.get('token', [''])[0] == self.token

    def client_ip(self):
        """优先取反向代理透传的真实访客 IP（X-Forwarded-For / X-Real-IP）。"""
        xff = self.headers.get('X-Forwarded-For', '')
        if xff:
            return xff.split(',')[0].strip()
        xri = self.headers.get('X-Real-IP', '')
        if xri:
            return xri.strip()
        return self.client_address[0]

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, DELETE')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path in ('/api/site', '/api/site/'):
            if not self._check_token(query):
                self._send_json({'error': 'token 错误'}, 401); return
            site = query.get('site', [''])[0]
            ok = self.engine.remove_site(site)
            self._send_json({'status': ok})
            return
        self.send_error(405)

    def do_HEAD(self):
        """复用 GET 路由，仅返回响应头（HEAD 用于健康检查 / 监控）。"""
        self._head_mode = True
        try:
            self.do_GET()
        finally:
            self._head_mode = False

    def send_error(self, code, message=None, explain=None):
        # HEAD 模式下不返回消息体，只发状态行与头
        if getattr(self, '_head_mode', False):
            try:
                self.send_response(code, message)
                self.send_header('Content-Length', '0')
                self.end_headers()
            except Exception:
                pass
            return
        return super().send_error(code, message, explain)

    def do_GET(self):
        self._head_mode = False
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == '/tracker.js':
            f = os.path.join(self.www_root, 'tracker.js')
            self._send_file(f, 'application/javascript; charset=utf-8')
            return

        if path == '/api/event':
            # GET 兜底（Image beacon）：参数在 query 中
            ev = {
                'site': query.get('site', [''])[0],
                'visitor': query.get('visitor', [''])[0],
                'session': query.get('session', [''])[0],
                'type': query.get('type', ['pageview'])[0],
                'path': query.get('path', ['/'])[0],
                'ref': query.get('ref', [''])[0],
                'lang': query.get('lang', [''])[0],
                'screen': query.get('screen', [''])[0],
                'duration': query.get('duration', ['0'])[0],
                'ua': self.headers.get('User-Agent', ''),
                'ip': self.client_ip(),
            }
            ok = self.engine.add_event(ev)
            self._send_json({'status': ok}, 200 if ok else 400)
            return

        if path in ('/api/sites', '/api/sites/'):
            if not self._check_token(query):
                self._send_json({'error': 'token 错误'}, 401); return
            try:
                sites = self.engine.get_sites()
                self._send_json({'status': True, 'sites': sites})
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return

        if path in ('/api/site', '/api/site/'):
            if not self._check_token(query):
                self._send_json({'error': 'token 错误'}, 401); return
            try:
                sites = self.engine.list_sites()
                self._send_json({'status': True, 'sites': sites})
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return

        if path in ('/api/months', '/api/months/'):
            if not self._check_token(query):
                self._send_json({'error': 'token 错误'}, 401); return
            site = query.get('site', [''])[0]
            try:
                months = self.engine.get_months(site)
                self._send_json({'status': True, 'data': months})
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return

        if path in ('/api/stats', '/api/stats/'):
            if not self._check_token(query):
                self._send_json({'error': 'token 错误'}, 401); return
            site = query.get('site', [''])[0]
            days = query.get('days', ['30'])[0]
            range_str = query.get('range', [''])[0]
            try:
                result = self.engine.get_stats(site, days, range_str=range_str or None)
                if isinstance(result, dict) and 'error' in result:
                    self._send_json({'status': False, 'msg': result['error']}, 400)
                else:
                    self._send_json({'status': True, 'data': result})
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return

        if path in ('/api/recent', '/api/recent/'):
            if not self._check_token(query):
                self._send_json({'error': 'token 错误'}, 401); return
            site = query.get('site', [''])[0]
            window = query.get('window', ['10'])[0]
            limit = query.get('limit', ['500'])[0]
            source = query.get('source', [''])[0]
            refdomain = query.get('refdomain', [''])[0]
            try:
                recs = self.engine.get_recent(site, window_minutes=window, limit=limit,
                                              source=source or None, refdomain=refdomain or None)
                recs = recs if isinstance(recs, dict) else {'rows': recs, 'online': 0}
                self._send_json({'status': True, 'data': recs.get('rows', []), 'online': recs.get('online', 0)})
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return

        if path in ('/api/admin/settings', '/api/admin/settings/'):
            if not self._check_token(query):
                self._send_json({'error': 'token 错误'}, 401); return
            try:
                days = self.engine.get_retention_days()
                tz = self.engine.get_timezone_offset()
                lp = self.engine.get_lead_patterns()
                self._send_json({'status': True, 'retention_days': days,
                                 'timezone_offset': tz, 'lead_patterns': lp})
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return

        if path in ('/api/visitors', '/api/visitors/'):
            if not self._check_token(query):
                self._send_json({'error': 'token 错误'}, 401); return
            site = query.get('site', [''])[0]
            days = query.get('days', ['30'])[0]
            range_str = query.get('range', [''])[0]
            source = query.get('source', [''])[0]
            refdomain = query.get('refdomain', [''])[0]
            inquiry = query.get('inquiry', [''])[0]
            try:
                recs = self.engine.get_visitors(site, days, range_str=range_str or None,
                                                source=source or None, refdomain=refdomain or None,
                                                inquiry=(inquiry in ('1', 'true', 'True')))
                self._send_json({'status': True, 'data': recs.get('visitors', []),
                                 'total_visitors': recs.get('total_visitors', 0),
                                 'inquiry_count': recs.get('inquiry_count', 0),
                                 'suspect_count': recs.get('suspect_count', 0),
                                 'suspect_dc_count': recs.get('suspect_dc_count', 0),
                                 'suspect_highpv_count': recs.get('suspect_highpv_count', 0)})
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return

        if path in ('/api/admin/blocked', '/api/admin/blocked/'):
            if not self._check_token(query):
                self._send_json({'error': 'token 错误'}, 401); return
            site = query.get('site', [''])[0]
            try:
                blocked = self.engine.get_blocked_visitors(site or None)
                self._send_json({'status': True, 'data': blocked})
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return

        if path in ('/', '/index.html'):
            idx = os.path.join(self.www_root, 'index.html')
            self._send_file(idx, 'text/html; charset=utf-8')
            return

        if path.startswith('/static/'):
            # 静态资源：echarts、世界地图 GeoJSON 等
            rel = path[len('/static/'):]
            # 防止路径穿越
            safe = os.path.normpath(rel).replace('\\', '/')
            if safe.startswith('..') or safe.startswith('/'):
                self.send_error(403); return
            static_root = os.path.join(self.www_root, 'static')
            fpath = os.path.join(static_root, safe)
            if not os.path.isfile(fpath):
                self.send_error(404); return
            ctype = 'application/octet-stream'
            if fpath.endswith('.js'):
                ctype = 'application/javascript; charset=utf-8'
            elif fpath.endswith('.json'):
                ctype = 'application/json; charset=utf-8'
            elif fpath.endswith('.html'):
                ctype = 'text/html; charset=utf-8'
            self._send_file(fpath, ctype)
            return

        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ('/api/admin/block', '/api/admin/block/'):
            # 确认为异常爬虫后软屏蔽该访客：保留原始事件，统计读取时排除（可恢复）
            if not self._check_token(parse_qs(parsed.query)):
                self._send_json({'error': 'token 错误'}, 401); return
            try:
                length = int(self.headers.get('Content-Length', 0) or 0)
                raw = self.rfile.read(length) if length else b''
                body = {}
                if raw:
                    try:
                        body = json.loads(raw.decode('utf-8'))
                    except Exception:
                        body = {}
                visitor = (body.get('visitor') or '').strip()
                if not visitor:
                    self._send_json({'status': False, 'error': '缺少 visitor'}, 400); return
                try:
                    asn = int(body.get('asn') or 0)
                except Exception:
                    asn = 0
                ok = self.engine.block_visitor(
                    visitor, site=body.get('site') or '',
                    reason=body.get('reason') or '', isp=body.get('isp') or '', asn=asn)
                self._send_json({'status': ok} if ok else {'status': False, 'error': '屏蔽失败'},
                                200 if ok else 500)
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return
        if path in ('/api/admin/unblock', '/api/admin/unblock/'):
            # 解除软屏蔽：其历史数据重新计入统计
            if not self._check_token(parse_qs(parsed.query)):
                self._send_json({'error': 'token 错误'}, 401); return
            try:
                length = int(self.headers.get('Content-Length', 0) or 0)
                raw = self.rfile.read(length) if length else b''
                body = {}
                if raw:
                    try:
                        body = json.loads(raw.decode('utf-8'))
                    except Exception:
                        body = {}
                visitor = (body.get('visitor') or '').strip()
                if not visitor:
                    self._send_json({'status': False, 'error': '缺少 visitor'}, 400); return
                ok = self.engine.unblock_visitor(visitor)
                self._send_json({'status': ok} if ok else {'status': False, 'error': '解除失败'},
                                200 if ok else 500)
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return
        if path in ('/api/admin/settings', '/api/admin/settings/'):
            if not self._check_token(parse_qs(parsed.query)):
                self._send_json({'error': 'token 错误'}, 401); return
            try:
                length = int(self.headers.get('Content-Length', 0) or 0)
                raw = self.rfile.read(length) if length else b''
                body = {}
                if raw:
                    try:
                        body = json.loads(raw.decode('utf-8'))
                    except Exception:
                        body = {}
                resp = {}
                if 'retention_days' in body and body['retention_days'] is not None:
                    d = self.engine.set_retention_days(body['retention_days'])
                    if d:
                        resp['retention_days'] = d
                if 'timezone_offset' in body and body['timezone_offset'] is not None:
                    try:
                        off = self.engine.set_timezone_offset(body['timezone_offset'])
                        if off is not None:
                            resp['timezone_offset'] = off
                    except Exception as e:
                        resp['timezone_error'] = str(e)
                if 'lead_patterns' in body:
                    lp = self.engine.set_lead_patterns(body['lead_patterns'])
                    if lp is not None:
                        resp['lead_patterns'] = lp
                if body.get('cleanup_now'):
                    resp['deleted'] = self.engine.cleanup_old_events(body.get('days'))
                if 'retention_days' not in resp and 'deleted' not in resp:
                    resp['retention_days'] = self.engine.get_retention_days()
                if 'timezone_offset' not in resp:
                    resp['timezone_offset'] = self.engine.get_timezone_offset()
                if 'lead_patterns' not in resp:
                    resp['lead_patterns'] = self.engine.get_lead_patterns()
                self._send_json({'status': True, 'data': resp})
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return
        if path in ('/api/site/reorder', '/api/site/reorder/'):
            if not self._check_token(parse_qs(parsed.query)):
                self._send_json({'error': 'token 错误'}, 401); return
            try:
                length = int(self.headers.get('Content-Length', 0) or 0)
                raw = self.rfile.read(length) if length else b''
                body = {}
                if raw:
                    try:
                        body = json.loads(raw.decode('utf-8'))
                    except Exception:
                        body = {}
                order = body.get('order', [])
                ok = self.engine.set_site_order(order)
                self._send_json({'status': ok} if ok else {'status': False, 'error': '保存排序失败'},
                                200 if ok else 500)
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return
        if path in ('/api/site', '/api/site/'):
            if not self._check_token(parse_qs(parsed.query)):
                self._send_json({'error': 'token 错误'}, 401); return
            try:
                length = int(self.headers.get('Content-Length', 0) or 0)
                raw = self.rfile.read(length) if length else b''
                body = {}
                if raw:
                    try:
                        body = json.loads(raw.decode('utf-8'))
                    except Exception:
                        body = {}
                ok, info = self.engine.add_site(body.get('site', ''), body.get('label', ''))
                self._send_json({'status': ok, 'site': info} if ok else {'status': False, 'error': info},
                                200 if ok else 400)
            except Exception as e:
                self._send_json({'status': False, 'error': str(e)}, 500)
            return
        if path not in ('/api/event', '/api/event/'):
            self.send_error(404); return
        try:
            length = int(self.headers.get('Content-Length', 0) or 0)
            raw = self.rfile.read(length) if length else b''
            # 支持 JSON 与 form-urlencoded
            ctype = self.headers.get('Content-Type', '')
            ev = {}
            if 'application/json' in ctype:
                try:
                    ev = json.loads(raw.decode('utf-8')) if raw else {}
                except Exception:
                    ev = {}
            elif 'application/x-www-form-urlencoded' in ctype:
                ev = {k: v[0] for k, v in parse_qs(raw.decode('utf-8')).items()}
            else:
                # sendBeacon 默认 text/plain，尝试 JSON
                try:
                    ev = json.loads(raw.decode('utf-8')) if raw else {}
                except Exception:
                    ev = {}
            ev.setdefault('ua', self.headers.get('User-Agent', ''))
            ev.setdefault('ip', self.client_ip())
            ok = self.engine.add_event(ev)
            self._send_json({'status': ok}, 200 if ok else 400)
        except Exception as e:
            self._send_json({'status': False, 'error': str(e)}, 500)

    def log_message(self, fmt, *args):
        pass


def main():
    import argparse
    import errno
    ap = argparse.ArgumentParser(description='站点流量统计（埋点版）')
    ap.add_argument('--host', default=DEFAULT_HOST, help='监听地址 (默认 127.0.0.1)')
    ap.add_argument('--port', type=int, default=DEFAULT_PORT, help='监听端口 (默认 8899)')
    ap.add_argument('--token', default=DEFAULT_TOKEN, help='面板访问令牌 (留空则不鉴权)')
    ap.add_argument('--data-dir', default=DEFAULT_DATA_DIR, help='数据目录')
    ap.add_argument('--geoip-db', default=DEFAULT_GEO_DB, help='GeoLite2 数据库路径（缺省 geoip/GeoLite2-City.mmdb）')
    ap.add_argument('--asn-db', default=DEFAULT_ASN_DB, help='GeoLite2-ASN 数据库路径（缺省 geoip/GeoLite2-ASN.mmdb，用于识别访客运营商）')
    args = ap.parse_args()

    os.makedirs(args.data_dir, exist_ok=True)
    engine = StatEngine(data_dir=args.data_dir, geo_db=args.geoip_db, asn_db=args.asn_db)
    # 启动即按保留期清理过期原始事件（默认 720 天）；缺失或异常不影响启动
    try:
        deleted = engine.cleanup_old_events()
        if deleted:
            sys.stderr.write('[info] 启动清理：已删除 %d 条超过保留期的旧事件\n' % deleted)
    except Exception as e:
        sys.stderr.write('[warn] 启动清理失败：%s\n' % e)
    # 启动即回填：将历史事件中确认的机房 / 数据中心流量访客自动排除（不计入统计）
    try:
        n_dc = engine.auto_block_datacenter_visitors()
        if n_dc:
            sys.stderr.write('[info] 机房/数据中心流量回填：已自动排除 %d 个访客\n' % n_dc)
    except Exception as e:
        sys.stderr.write('[warn] 机房流量回填失败：%s\n' % e)
    # 启动即清洗：将部署「查询串剥离」前入库、含 ? 查询串或 # 片段的历史路径归一化为静态路径
    try:
        n_path = engine.clean_stored_paths()
        if n_path:
            sys.stderr.write('[info] 历史路径清洗：已归一化 %d 条含查询串/片段的路径\n' % n_path)
    except Exception as e:
        sys.stderr.write('[warn] 历史路径清洗失败：%s\n' % e)
    Handler.engine = engine
    Handler.token = args.token
    Handler.www_root = os.path.dirname(os.path.abspath(__file__))

    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        if e.errno in (errno.EADDRINUSE,):
            sys.stderr.write(
                "\n[错误] 端口 %d 已被占用 (Address already in use)。\n"
                "通常是旧的统计服务（site_stats_web 或另一个 site_analytics 实例）仍在运行。\n"
                "请先在服务器上定位并停止占用进程，再重新启动：\n"
                "  # 1. 查看是谁占用：\n"
                "  ss -ltnp | grep :%d\n"
                "  # 或：lsof -i :%d\n"
                "  # 2. 确认进程命令行（看清是不是旧版 app.py）：\n"
                "  ps -p <PID> -o pid,cmd\n"
                "  # 3. 确认是旧统计服务后停止：\n"
                "  kill <PID>            # 普通进程\n"
                "  systemctl stop site_analytics   # 若是 systemd 服务\n"
                "  # 4. 重新启动新版本：\n"
                "  cd /opt/site_analytics && bash start.sh --port %d\n" % (args.port, args.port, args.port)
            )
            sys.exit(1)
        raise
    url = 'http://%s:%d/' % (args.host if args.host != '0.0.0.0' else '<服务器IP>', args.port)
    if args.token:
        url += '?token=' + args.token
    print('=' * 60)
    print('站点流量统计（埋点版）已启动')
    print('监听: %s:%d' % (args.host, args.port))
    print('数据目录: %s' % args.data_dir)
    if engine.geo_enabled():
        print('GeoIP: 已启用 (%s)' % args.geoip_db)
    else:
        print('GeoIP: 未启用（安装 maxminddb 并放置 GeoLite2 数据库可显示访客地域）')
    if engine.asn_enabled():
        print('ASN(运营商): 已启用 (%s)' % args.asn_db)
    else:
        print('ASN(运营商): 未启用（放置 geoip/GeoLite2-ASN.mmdb 可识别访客运营商）')
    if args.token:
        print('面板令牌: %s' % args.token)
    else:
        print('面板鉴权: 未启用 (建议配合反向代理 + 访问控制)')
    print('面板地址: %s' % url)
    print('嵌入代码: <script src="http://%s:%d/tracker.js" data-site="你的域名" defer></script>'
          % (args.host if args.host != '0.0.0.0' else '<服务器IP>', args.port))
    print('=' * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')
        httpd.server_close()


if __name__ == '__main__':
    main()
