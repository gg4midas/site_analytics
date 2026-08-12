# Site Analytics · 站点流量统计

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.7%2B-blue.svg)](https://www.python.org)
[![Self-hosted](https://img.shields.io/badge/Self--hosted-%E2%9C%93-brightgreen.svg)]()
[![Privacy-friendly](https://img.shields.io/badge/Privacy--friendly-%E2%9C%93-brightgreen.svg)]()

轻量、自托管、隐私友好的网站访问分析工具。**基于前端埋点，不依赖任何访问日志。**

通过在被统计的网页中嵌入一段极轻量的 JS（`tracker.js`），由**真实访客的浏览器**主动上报访问事件。
相比解析 Nginx/Apache 访问日志，这种方式天然规避了爬虫、监控、CDN 回源、健康检查等机器流量噪音，
信噪比更高，且能拿到日志无法提供的指标（真实停留时长、跳出率、SPA 路由、设备/浏览器归一化维度等）。

- **零必需第三方依赖**：后端仅用 Python 标准库（`http.server`）即可运行，图表使用本地 ECharts，无需联网、无需数据库服务。
- **自托管**：数据存在你自己的服务器上的 SQLite 文件里，不经过任何第三方。
- **可选增强**：GeoIP 地域分布（`maxminddb` + GeoLite2，自由可选，缺失时自动禁用，不影响其它功能）。

---

## 特性

- **真实访客指标**：PV、独立访客（UV）、会话数、跳出率、平均停留时长、人均页面数。
- **维度分析**：热门页面、来路域名（referrer）、设备分布、浏览器分布、操作系统分布、屏幕分辨率。
- **实时监控**：最近访客流，面板每 5 秒轮询刷新。
- **访客地域（可选）**：国家 / 地区分布 + 城市 TOP，带国旗；另可识别运营商（ASN）。
- **时间范围**：近 1 天 / 近 7 天 / 近 30 天，按天聚合。
- **站点管理**：面板内手动添加站点，自动生成已填好 `data-site` 的埋点代码，一键复制；支持删除注册（保留已采集事件）。
- **SQLite 事件存储**，按天聚合查询，单文件易备份。
- **公开上报端点**（`/api/event`，CORS 开放），面板与查询接口**可选 token 鉴权（默认关闭，非必需）**。
- **反作弊**：自动剔除 `navigator.webdriver` 与已知爬虫 UA。
- **反向代理友好**：通过 `X-Forwarded-For` / `X-Real-IP` 还原真实访客 IP。

---

## 界面一览（功能模块）

分析面板（`index.html`）为单页仪表盘，顶栏可切换 **中 / EN** 语言、切换深色 / 浅色主题、手动刷新。包含以下模块：

| 模块 | 内容 |
|------|------|
| 概览 | PV / UV / 会话 / 跳出率 / 平均停留等核心 KPI，访问趋势、访问深度、新访客 vs 回访客、设备分布 |
| 访客 | 访客明细（来路、设备/浏览器、运营商、地区、停留、最近活跃），潜在目标客户与疑似爬虫/数据采集标记 |
| 内容 | 热门页面、落地页 TOP、退出页 TOP、页面平均停留 TOP |
| 性能 | 前端性能采样（FCP / LCP / TTFB / CLS / Speed Index） |
| 来源 | 来源类型分布、来源域名 TOP |
| 地域 | 世界地图 + 国家/地区排行 + 城市 TOP（需启用 GeoIP） |
| 实时监控 | 近 5 / 10 / 30 分钟访客流，每 5 秒轮询 |
| 站点管理 | 添加/删除站点、生成埋点代码、设置数据保留期、管理被屏蔽访客 |

> 截图待补充——欢迎按 [CONTRIBUTING](CONTRIBUTING.md) 认领，或本地运行后提交真实截图。

---

## 工作原理

```
 访客浏览器               你的服务器                       数据
┌──────────┐   加载/上报   ┌──────────────────┐        ┌──────────┐
│ 被统计网页 │ ───────────▶ │  tracker.js       │        │          │
│ (任意站点) │ ◀─────────── │  app.py (8899)    │ ─────▶ │ SQLite   │
└──────────┘   返回脚本     │  事件收集+聚合     │  写入   │ events.db│
                           │  + 面板 index.html │        │          │
                           └──────────────────┘        └──────────┘
                                  ▲
                          面板浏览器访问 (查看图表)
```

1. 你在目标网站的每个页面嵌入 `tracker.js`（一行 `<script>`）。
2. 访客打开页面时，浏览器加载 `tracker.js` 并向 `/api/event` 上报访问（页面隐藏时再上报停留时长）。
3. `app.py` 接收事件写入 `data/events.db`，并按站点（`data-site`）分组。
4. 你通过面板（`index.html`）查看聚合图表；面板与上报端点可置于反向代理之后。

> **为什么不用日志解析？** 日志里混杂大量非人类流量（爬虫、监控、CDN 回源、探活），且拿不到停留时长、跳出率等客户端行为；前端埋点只统计真实浏览器执行，更干净、更准确。

---

## 目录结构

```
site_analytics/
├── app.py                  # 后端服务：事件收集 + 聚合 + 面板 + tracker.js（单文件）
├── tracker.js              # 前端埋点脚本（嵌入被统计网页）
├── index.html              # 分析面板（本地 ECharts，深色风格）
├── tracker-loader.html     # 可选的「内联加载器」片段（用于缓存/优化插件较重的站点）
├── nginx_bypass_auth.conf  # 反向代理用的两段 location 配置示例（通用 Nginx）
├── static/
│   └── echarts.min.js      # 本地图表库（已随仓库，无需联网）
├── start.sh                # 启动脚本（后台运行，写 run.log）
├── restart.sh              # 重启脚本
├── sa-console.sh           # 服务器管理控制台：启停 / 重启 / 版本检查 / 一键升级
├── site_analytics.service  # systemd 服务单元示例
├── update_geoip.sh         # 下载 / 更新 GeoLite2 数据库（City + ASN）
├── geoip/                  # 运行时放置 GeoLite2-*.mmdb（需自行下载，未入库）
└── data/                   # 运行时生成：events.db + run.log / debug.log
```

> `geoip/` 下的 `.mmdb` 数据库约 130MB，已通过 `.gitignore` 排除，不进仓库；克隆后用 `update_geoip.sh` 拉取即可。

---

## 环境要求

| 组件 | 要求 | 说明 |
|------|------|------|
| Python | **3.7+**（推荐 3.10+） | 仅用标准库即可运行核心功能 |
| 第三方库 | **无（核心功能）** | 不需要 `pip install` 任何东西 |
| `maxminddb` | 可选 | 仅当启用 GeoIP 地域功能时需要：`pip install maxminddb` |
| Web 服务器 | 可选（生产推荐） | Nginx / Caddy / Apache 任一，用于反向代理 + HTTPS |
| 操作系统 | Linux / macOS / Windows | 自托管场景以 Linux 服务器为主 |

> 本项目**不依赖** Node.js、不依赖外部数据库（MySQL/PostgreSQL 等）、不依赖任何云服务。

---

## 快速开始

```bash
# 1. 获取代码
git clone https://github.com/gg4midas/site_analytics.git
cd site_analytics

# 2. 启动（默认监听 127.0.0.1:8899，无令牌，不依赖任何第三方库）
python3 app.py

# 3. 浏览器打开面板
#    http://localhost:8899/
```

面板启动后，在你要统计的网站里嵌入埋点脚本（见下文「嵌入埋点代码」），有人访问后数据会自动出现。

> 想自定义端口 / 监听地址 / 令牌 / 数据目录，见「配置项」。

---

## 配置项

所有参数通过命令行传入，无配置文件：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `127.0.0.1` | 监听地址。生产建议保持 `127.0.0.1`，由反向代理对外暴露；若直接暴露公网可设为 `0.0.0.0`（不推荐）。 |
| `--port` | `8899` | 监听端口。 |
| `--token` | 空（不鉴权） | 面板与查询接口的可选访问令牌。留空则完全开放；设置后访问面板需带 `?token=xxx`。 |
| `--data-dir` | `./data` | 数据存储目录（放 `events.db`、日志）。可指向其它磁盘/挂载点。 |
| `--geoip-db` | `./geoip/GeoLite2-City.mmdb` | GeoIP 城市库路径。文件不存在时地域功能自动禁用。 |
| `--asn-db` | `./geoip/GeoLite2-ASN.mmdb` | GeoIP ASN 库路径，用于识别访客运营商。 |

示例：

```bash
# 仅本机、自定义端口、不鉴权（配合反向代理 + 访问控制最常用）
python3 app.py --host 127.0.0.1 --port 8899

# 叠加一层独立令牌保护面板
python3 app.py --host 127.0.0.1 --port 8899 --token 你的令牌

# 数据存到独立挂载点，并启用地理库
python3 app.py --data-dir /var/lib/site_analytics --geoip-db /opt/geo/GeoLite2-City.mmdb
```

> **关于令牌（token）**：它不是必需的。省略 `--token` 时面板与所有查询接口完全开放，任何知道地址的人都能访问。
> 若你的分析域名本身已做访问控制（basic auth / 仅自己知晓 / 内网），完全可以不用令牌；
> 反之希望面板再叠一层独立口令，才传 `--token`。

---

## 部署到生产

### 1) 后台运行 / 启动脚本

仓库自带 `start.sh` / `restart.sh`，会自动 `cd` 到自身目录并以 `nohup` 后台启动，日志写入 `run.log`：

```bash
bash start.sh                       # 默认端口 8899，无令牌
PORT=8899 TOKEN=你的令牌 bash start.sh
bash start.sh --port 8899 --token 你的令牌

bash restart.sh                    # 先释放端口再重启
```

### 2) systemd 服务（Linux 服务器推荐）

将示例单元放到系统目录并启用开机自启：

```bash
sudo cp site_analytics.service /etc/systemd/system/
sudo nano /etc/systemd/system/site_analytics.service   # 修改 WorkingDirectory 与 ExecStart 里的路径/令牌
sudo systemctl daemon-reload
sudo systemctl enable --now site_analytics
```

单元文件关键项（默认示例）：

```
WorkingDirectory=/opt/site_analytics
ExecStart=/usr/bin/python3 /opt/site_analytics/app.py --host 127.0.0.1 --port 8899 --token 你的令牌
```

> 把代码放到 `/opt/site_analytics` 后，将上面的 `/opt/site_analytics` 改成你的实际路径；不用令牌则删掉 `--token` 段。

### 3) 反向代理（通用，不绑定任何面板）

生产环境**不要**把 `8899` 端口直接暴露公网。标准做法：后端监听 `127.0.0.1`，由 Web 服务器（Nginx / Caddy / Apache）反代到独立域名并配置 HTTPS。
宝塔、aaPanel、1Panel、cPanel 等面板本质上都是这些 Web 服务器的图形外壳——把对应的 `location` 段粘贴进站点配置即可，无需任何面板专属操作。

下面以 **Nginx** 为例（完整 `server` 块，含 TLS、公开上报路径、可选面板保护、真实 IP 透传）：

```nginx
server {
    listen 80;
    server_name analytics.example.com;   # 改成你的分析域名

    # ---- 必须公开：埋点脚本，所有访客浏览器都要加载 ----
    location = /tracker.js {
        proxy_pass http://127.0.0.1:8899;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ---- 必须公开：事件上报接口，POST/GET 都要放行，否则统计不到 ----
    location /api/event {
        proxy_pass http://127.0.0.1:8899;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 256k;       # 上报多为 sendBeacon/fetch，放宽体积限制
    }

    # ---- 面板其余路径：可选加 basic auth 保护（也可改用 --token）----
    location / {
        proxy_pass http://127.0.0.1:8899;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 如需基础认证保护面板，取消下面两行，并提前用 `htpasswd` 生成密码文件
        # auth_basic "Restricted";
        # auth_basic_user_file /etc/nginx/conf.d/analytics.htpasswd;
    }
}
```

> 上述三段 `location` 也已单独提供在 `nginx_bypass_auth.conf`，可直接复制使用。
> 在各类面板里：进入站点「设置 / 配置文件」，把这两段（tracker.js 与 /api/event）粘进 `server { … }` 内部即可，其余路径仍保持面板原有的访问控制。

**Caddy（自动 HTTPS，最简）：**

```caddyfile
analytics.example.com {
    encode gzip
    reverse_proxy 127.0.0.1:8899
}
```

**Apache（`<VirtualHost>` 内）：**

```apache
ProxyPass        /tracker.js http://127.0.0.1:8899/tracker.js
ProxyPass        /api/event  http://127.0.0.1:8899/api/event
ProxyPass        /           http://127.0.0.1:8899/
ProxyPreserveHost On
RemoteIPHeader   X-Forwarded-For
```

### 4) 真实 IP 透传（GeoIP / 准确统计的前提）

地域分布与准确来源统计依赖访客真实 IP。经反向代理后，后端默认看到的源 IP 是 `127.0.0.1`，
因此代理**必须**携带 `X-Forwarded-For` / `X-Real-IP`（上面各示例均已包含）。

```nginx
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Real-IP $remote_addr;
```

内网 / 本地 IP 在地域图会显示为「(内网/本地)」，属正常现象。

---

## 服务管理控制台（sa-console.sh，服务器运维）

部署到服务器后，可用自带的控制台统一管理启停与升级，无需记忆命令。

### 安装与软链

```bash
# 把 sa-console.sh 放到安装目录（如 /opt/site_analytics），赋予执行权限
chmod +x sa-console.sh
# 可选：软链到 PATH，之后任意目录输入 sa-console 即可
ln -s "$(pwd)/sa-console.sh" /usr/local/bin/sa-console
```

### 交互式菜单

```text
=========== site_analytics 服务管理控制台 ===========
 1: 检查版本更新
 2: 启动服务
 3: 关闭服务
 4: 重启服务
 0: 退出
======================================================
```

- **1 检查版本更新**：读取 `app.py` 里的 `VERSION`，联网比对 GitHub `main` 分支最新版本；若发现新版本，确认后自动下载覆盖并重启（保留数据库与本地配置）。
- **2 启动 / 3 关闭 / 4 重启**：兼容「`nohup` + `start.sh`」与「systemd 服务」两种运行方式；按监听端口反查进程，状态显示准确。

### 单命令（便于脚本 / 监控调用）

```bash
sa-console start | stop | restart | status | update
```

> 当前版本号记录在 `app.py` 的 `VERSION` 常量中（发版时改此处即可，控制台会自动比对并提示升级）。

---

## 嵌入埋点代码

把下面一行放在每个页面的 `</body>` 之前（或全站公共模板里）：

```html
<script src="https://你的分析域名/tracker.js" data-site="example.com" defer></script>
```

- **`data-site`**：站点标识（建议用域名），面板据此分组；省略时自动取当前 `location.hostname`。
- **跨域**：脚本托管在你的分析域名，向同域 `/api/event` 上报，已开放 CORS，无需额外配置。
- **`data-respect-dnt="true"`**（可选）：尊重浏览器「不跟踪（Do Not Track）」设置，开启后带 DNT 的访客不上报。
- **`data-endpoint="https://你的分析域名/api/event"`**（可选）：显式指定上报地址，防止脚本被意外改造时算错目标。
- **SPA / 前端路由**：`tracker.js` 监听 `pushState` / `popstate`，单页应用路由切换会自动按新路径上报，无需手动调用。

### 面板内自动生成代码（推荐）

不想手敲？在面板顶栏点 **「+ 添加站点」**，填写要监控的域名（如 `example.com`，可带备注名），
提交后自动列出该站点的埋点代码，点「复制」粘贴到目标网站 `</body>` 前即可。**无需重启后端**，新站点立即出现在顶部下拉框。
- **多语言 / 子域型站点（如 WPML）**：只需在「+ 添加站点」填写主域名（不含 `www`，如 `example.com`）。把同一段通用部署代码粘贴到 `www` / `de` / `fr` 等所有语言子域，tracker 自动按各子域的 `location.hostname` 上报，后端自动归并到主域统一监控并按语言区分；**不要**为每个子域分别添加站点，也**不要**加 `www.` 前缀。


### 缓存 / 优化插件较重的站点（可选）

若目标站用了激进的缓存或「Delay JS / 合并 JS」类优化插件，可能拦截外部 `tracker.js`。
此时用 `tracker-loader.html` 里的**内联加载器**替代上面的 `<script src>`：它是一段内联脚本，
运行时才动态注入 `tracker.js`，能在插件输出阶段「隐身」，从而避开本地化 / 合并。
该加载器对**任何 CMS（WordPress / 织梦 / 自建站点等）**都适用，不仅限于 WordPress。

---

## 启用访客地域（GeoIP，可选）

地域分布依赖 MaxMind GeoLite2 数据库，默认**不启用**（不影响其它功能）。

1. **安装解析库**（仅需一次，在服务端）：
   ```bash
   pip install maxminddb        # 纯 Python 解析，无需编译
   ```
2. **获取免费数据库**（任选其一）：
   - **MaxMind GeoLite2**（CC BY-SA 4.0，可免费非商用）：到 https://www.maxmind.com/ 注册 → My Account → Generate License Key。
   - **db-ip 免费库**（免 Key、免注册）：直接用 `--dbip` 参数即可，见下一步。
3. **下载并更新**（脚本解压到 `geoip/`）：
   ```bash
   GEOIP_LICENSE_KEY=你的Key ./update_geoip.sh
   # 或： ./update_geoip.sh 你的Key
   # 免 Key 的 db-ip 源：
   ./update_geoip.sh --dbip
   ```
4. **重启后端**，启动时出现 `GeoIP: 已启用 (...)` 即生效：
   ```bash
   python3 app.py --host 127.0.0.1 --port 8899 --geoip-db geoip/GeoLite2-City.mmdb --asn-db geoip/GeoLite2-ASN.mmdb
   ```
   若 `--geoip-db` 省略，默认读取 `geoip/GeoLite2-City.mmdb`。
5. 面板「地域」标签页即可看到国家 / 地区排行（带旗帜）与城市 TOP。

> 数据库约每 1–2 月更新一次，重跑 `update_geoip.sh` 后**重启后端**即可（GeoIP reader 在启动时加载）。

---

## API 参考

| 端点 | 鉴权 | 说明 |
|------|------|------|
| `GET  /tracker.js` | 无 | 返回埋点脚本 |
| `POST/GET /api/event` | 无 | 接收上报事件（JSON / form / 图片 beacon） |
| `GET  /api/sites` | token* | 站点列表（手动注册 ∪ 事件发现，去重） |
| `GET  /api/stats?site=&days=` | token* | 聚合统计 |
| `GET  /api/recent?site=&limit=` | token* | 最近事件（实时监控） |
| `GET  /api/site` | token* | 手动注册的站点及备注 |
| `POST /api/site` | token* | 添加站点 `{"site","label"}` |
| `DELETE /api/site?site=` | token* | 删除站点注册 |

> `token*`：仅当后端以 `--token` 启动时校验；未设置令牌则全部开放（同其他查询接口）。

---

## 指标口径说明

- **跳出率**：仅含 1 个 pageview 的会话 / 总会话。
- **平均停留**：按会话汇总 `pagehide` 上报的停留时长后取均值（关闭过快未触发上报的会话不计入）。
- **独立访客（UV）**：基于埋点分配的访客 ID（`localStorage`，约 1 年有效期），**非 IP**，因此不受 NAT / 共享出口 IP 影响，更接近真实人数。
- **会话**：基于访客 ID + 活跃窗口（默认 30 分钟无新事件则会话结束）划分。

---

## 隐私与合规

- 不采集表单内容、不采集精确 GPS 坐标。
- 启用 GeoIP 后，仅按访问者 IP 解析**国家 / 城市级别**的大致位置（来自本地 MaxMind 数据库，**不上传任何第三方**），用于地域分布统计；不存储原始 IP。
- 访客 ID 为随机生成，不与个人身份绑定。
- 如需满足 GDPR /《个人信息保护法》等告知义务，请在网站隐私政策中说明使用了本站统计。

---

## 常见问题 / 排错

- **面板无站点**：确认目标站已嵌入 `tracker.js` 且有真实访问；F12 看 Network 是否有 `/api/event` 请求（应为 204）。
- **事件未入库**：检查 `data/run.log` 或 `data/debug.log`；确认上报 UA 未被误判为爬虫（正常浏览器不会）。
- **图表不显示**：确认 `static/echarts.min.js` 存在且可访问。
- **地域为空**：GeoIP 未启用——确认已 `pip install maxminddb`、已下载 `.mmdb`、且重启了后端。
- **全部访客显示同一 IP / 内网**：反向代理未透传 `X-Forwarded-For`，参照「真实 IP 透传」配置。
- **端口占用**：`sa-console 重启` 会自动按端口定位进程并释放；或 `bash restart.sh`、`lsof -i :8899` / `fuser -k 8899/tcp` 手动释放后重启。

---

## 贡献

欢迎 Issue 与 Pull Request！开发指南见 [CONTRIBUTING.md](CONTRIBUTING.md)。

- 本地开发与运行**只需 Python 标准库**，无需额外环境；仅启用 GeoIP 时才需 `pip install maxminddb`。
- 提交前请确认 `python3 app.py` 可正常启动、面板可打开。
- 代码风格保持与现有单文件 `app.py` / `index.html` 一致（零外部依赖优先）。

---

## 许可证

本项目以 [MIT License](LICENSE) 开源——可自由使用、修改、分发，但**不提供担保**，作者不对使用后果负责。请在分发时保留版权与许可声明。
