# Site Analytics · 站点流量统计

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.7%2B-blue.svg)](https://www.python.org)
[![Self-hosted](https://img.shields.io/badge/Self--hosted-%E2%9C%93-brightgreen.svg)]()
[![Privacy-friendly](https://img.shields.io/badge/Privacy--friendly-%E2%9C%93-brightgreen.svg)]()

> 英文文档：[README_EN.md](README_EN.md)

轻量、自托管、隐私友好的网站访问分析工具。**基于前端埋点，不依赖任何访问日志。**

通过在被统计的网页中嵌入一段极轻量的 JS（`tracker.js`），由**真实访客的浏览器**主动上报访问事件。
相比解析 Nginx/Apache 访问日志，这种方式天然规避了爬虫、监控、CDN 回源、健康检查等机器流量噪音，
信噪比更高，且能拿到日志无法提供的指标（真实停留时长、跳出率、SPA 路由、设备/浏览器归一化维度等）。

- **零必需第三方依赖**：后端仅用 Python 标准库（`http.server`）即可运行，图表使用本地 ECharts，无需联网、无需数据库服务。
- **自托管**：数据存在你自己的服务器上的 SQLite 文件里，不经过任何第三方。
- **可选增强**：GeoIP 地域分布（`maxminddb` + GeoLite2，自由可选，缺失时自动禁用，不影响其它功能）。

---

## 版本历史

### v1.4.3（2026-08-14）
- **后端可靠性加固（P0，生产必修，零依赖 / 数据库兼容）**：
  - **P0-1 SQLite 并发写入**：`_conn()` 默认开启 `WAL` 日志模式 + `busy_timeout=5000` + `synchronous=NORMAL`，消除高并发下 `database is locked` 导致 tracker 上报**静默丢事件**的问题；旧 `events.db` 直接复用，零迁移风险。
  - **P0-2 请求体上限**：所有 `POST` 接口统一经 `_read_body()` 安全读取，请求体上限 **64KB**，并对非整数 `Content-Length` 容错（不再返回 500），防慢速 / 超大体请求占满线程池（slowloris / DoS）。
  - **P0-3 超时与守护线程**：`Handler.timeout=15` 断掉慢客户端，`ThreadingHTTPServer(daemon_threads=True)` 避免关闭期挂起。
  - **P2-1 时序侧信道**：`_deploy_ok` 令牌比较由 `==` 改为 `hmac.compare_digest`，消除令牌校验的时序侧信道。

### v1.4.2（2026-08-14）
- **UI 设计评审系统性修复（14 项）**：
  - **P0 功能性 bug（3）**：修复 `--fg` 缺失导致深色模式 textarea 黑字黑底不可读；修复 `--track` 缺失导致进度条轨道在深色下为刺眼浅块；修复 `.code-box` 硬编码黑底导致浅色主题弹窗出现沉重黑块（均改为由设计 Token 控制）。
  - **P1 一致性（5）**：散落硬编码色（进度条渐变、站点标签紫、嫌疑徽标橙、性能条/分段计数白底）全部抽为 `--accent/--lead/--suspect/--track` 等 Token，深浅主题自动协调；顶栏之外的控件（刷新按钮、实时窗口下拉、自定义日期输入）统一为 36px 高度；主部署码框改为与每站点一致的两列三按钮；图表高度收口为 `--chart-sm/md/lg` 三档；新增间距/字号/圆角/控件高度/过渡标尺 Token。
  - **P2 体验与无障碍（6）**：新增全局 `:focus-visible` 焦点环；提亮 `--faint` 使小字达 WCAG AA 4.5:1；模态增加 `role="dialog"`/`aria-modal`/`aria-label`、ESC 关闭与 Tab 焦点陷阱；合并性能页重复说明为单处；导航在窄屏改为独立横向滚动且刷新按钮固定；新增顶部加载进度条与内容淡入加载态。

### v1.4.1（2026-08-13）
- **仪表盘 UI 优化**：「站点管理」弹窗中每个站点的埋点代码与三个操作按钮改为两列布局（代码在左、按钮在右列三行分布），更紧凑易读；顶栏的「站点选择 / 添加站点 / 日期下拉 / 语言切换 / 浅色深色切换」统一为相同高度与对齐，去除零散感。
- **文档核对**：同步核对中英文 README 与 v1.4.0 实现的一致性，修正功能描述、控制台菜单（补回 `6: 健康检查` / `7: 查看日志`）、API 参考（新增 `POST /api/site/key`、补充每站点令牌说明）及 v1.4.0 陌生域名拒绝说明。

### v1.4.0（2026-08-13）
- **每站点独立部署令牌（防盗用，取代 v1.3.9 的全局令牌，本次为大迭代）**：每个站点在「+ 添加站点」时由服务端自动生成**独立**令牌（与其他站点互不相同）；「站点管理」为每个站点生成已含令牌的埋点代码，复制即用，无需手动记令牌。服务端在落库前校验，未携带 / 携带错误令牌的站点上报直接 `403` 拒绝，不触发 GeoIP/落库开销。
  - 未登记站点（未在面板添加、也无历史数据的陌生域名）一律拒绝，从根源挡住脚本被盗用到陌生高流量站点产生的服务器压力。
  - 已接入站点（面板已添加、或已有历史数据的站点）在「宽松模式」下照常接收，现有监控零中断、平滑对接；重新嵌入带令牌的脚本后即受保护。
  - 老站点可在「站点管理」点「重新生成令牌」启用每站点令牌（生成后须用新代码重新嵌入）。
  - 仍保留 `--require-key` / `SA_REQUIRE_KEY=1` 严格模式（全站重新嵌入带令牌脚本后开启，连已知站点也须带正确令牌）与全局兜底令牌 `--deploy-key` / `SA_DEPLOY_KEY`。

### v1.3.9（2026-08-13）
- **部署令牌（防 tracker 盗用 / 抗压，全局令牌版）**：`/api/event` 端点新增可选的部署令牌校验（全局 `SA_DEPLOY_KEY` / `--deploy-key`），tracker 须随上报带回正确令牌，否则 `403` 拒绝。v1.4.0 起升级为每站点独立令牌。

### v1.3.8（2026-08-13）
- **控制台快捷指令**：面板菜单新增 `6: 健康检查`、`7: 查看日志` 两项。健康检查覆盖进程 / 端口监听 / HTTP 探针（直连本机 `127.0.0.1:$PORT`，不受反向代理影响）/ 数据目录可写性；查看日志输出 `run.log` 最近 40 行。本版本已提交发布，旧版升级后会自动保留这两项，不再被旧 tarball 覆盖丢失。

### v1.3.7（2026-08-13）
- **性能面板**：新增可折叠的「性能数据精度说明」提示（默认折叠，点击展开）。说明 FCP/LCP/TTFB/CLS 为真实访客测量（RUM）、整体取 P75 分位；**Speed Index 为合成估算值，非 Lighthouse 实测，偏差约 ±30%~50%，勿作绝对值解读**；TTFB 不含建连/TLS/重定向（系统性偏小）；LCP/CLS 在短停留会话时可能偏低；头部 P75 与各页面/各设备均值口径不同。
- **无用户管理系统说明**：补充「为什么没有内置用户管理系统」——本工具定位自托管自用，访问控制由部署层（反向代理 basic auth / 内网隔离）或网站层已有账户承担；多用户场景推荐在 Nginx/Caddy 叠认证，或自行在 `--token` 上扩展账号体系。
- **部署包**：同步重建 `site_analytics_final.zip`（v1.3.7，19 文件，已排除敏感/废弃文件）。

---

## 特性

- **真实访客指标**：PV、独立访客（UV）、会话数、跳出率、平均停留时长、人均页面数。
- **维度分析**：热门页面、来路域名（referrer）、设备分布、浏览器分布、操作系统分布、屏幕分辨率。
- **实时监控**：最近访客流，面板每 5 秒轮询刷新。
- **访客地域（可选）**：国家 / 地区分布 + 城市 TOP，带国旗；另可识别运营商（ASN）。
- **时间范围**：近 1 天 / 近 7 天 / 近 30 天，按天聚合。
- **站点管理**：面板内手动添加站点，自动生成已含部署令牌的埋点代码，一键复制；支持删除站点（含其全部数据）。
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


<img width="1920" height="919" alt="illustration_sa_dashboard" src="https://github.com/user-attachments/assets/4dc90907-2358-4edc-88d3-67ee247533c3" />


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
├── sa-console.sh           # 服务器管理控制台：启停 / 重启 / 版本检查升级 / 一键回滚
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

# 国内访问 GitHub 缓慢时，可用 Gitee 镜像（与 GitHub 同步）：
git clone https://gitee.com/operations-go_0/site_analytics.git

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

> **为什么没有内置用户管理系统**：本项目定位为自托管自用工具，访问控制交由部署层承担——例如反向代理的 basic auth、内网隔离，或直接复用网站层已有的账户登录体系。应用内未实现账号注册 / 登录 / 多租户隔离。
> 如需多用户场景，推荐在反向代理（Nginx / Caddy）叠加认证，或自行在 `--token` 之上扩展账号体系；完整的用户管理模块属于可选增强，不在当前版本范围内。

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
 1: 检查版本更新（升级）
 2: 回滚到旧版本
 3: 启动服务
 4: 关闭服务
 5: 重启服务
 6: 健康检查
 7: 查看日志
 0: 退出
======================================================
```

- **1 检查版本更新**：读取 `app.py` 里的 `VERSION`，联网比对**最新的 Release**（默认 GitHub；若配置了国内镜像源则改从镜像读取）；若发现新版本，确认后自动下载对应 tarball 覆盖并重启（保留 `data/` 数据库与本地配置）。
- **2 回滚到旧版本**：列出**所有已发布的 Release**（默认 GitHub；若配置了镜像源则从镜像列出），选择其一即可把代码回滚到该版本（同样保留 `data/` 数据库与本地配置，并重启服务）。当某次升级出现问题时，可用它快速回退到上一个稳定版。
- **3 启动 / 4 关闭 / 5 重启**：兼容「`nohup` + `start.sh`」与「systemd 服务」两种运行方式；按监听端口反查进程，状态显示准确。
- **6 健康检查**：覆盖进程 / 端口监听 / HTTP 探针（直连本机 `127.0.0.1:$PORT`，不受反向代理影响）/ 数据目录可写性。
- **7 查看日志**：输出 `run.log` 最近 40 行。

### 国内镜像（Gitee / 自托管，可选）

GitHub 的源码包实际存放在 `codeload.github.com`，该域名在国内经常被墙或超时，导致「升级 / 回滚」下载失败。控制台支持配置**镜像源**：下载与版本列表都优先走镜像。最省事的方案是用 **Gitee** 做镜像：

1. 在 Gitee 新建仓库时选择「导入已有仓库」并粘贴 GitHub 地址，仓库**设为公开**，再把 `main` 分支与所有 `vX.Y.Z` 标签推送上去（`git push --tags`）。
2. 国内服务器**一次性**引导新版控制台（Gitee 的 raw 文件国内通常可达）：
   ```bash
   cd /你的安装目录
   curl -fsSL https://gitee.com/operations-go_0/site_analytics/raw/main/sa-console.sh -o sa-console.sh
   chmod +x sa-console.sh
   ```
3. 把镜像地址写进安装目录的 `.update_mirror`（永久生效，一行一个 URL）：
   ```bash
   echo 'https://gitee.com/operations-go_0/site_analytics/repository/archive/{tag}.tar.gz' > /你的安装目录/.update_mirror
   ```

之后控制台的「升级 / 回滚」全自动走 Gitee，完全不依赖 GitHub。

> 也可不写文件、临时用环境变量：`SA_UPDATE_MIRROR='https://gitee.com/operations-go_0/site_analytics/repository/archive/{tag}.tar.gz' sa-console update`。
> 镜像地址支持 `{tag}` 占位符（自动替换为版本号）；目录型镜像则写成基址（控制台拼成 `<基址>/<tag>.tar.gz`，并额外读取 `<基址>/versions.json` 作为版本清单）。

### 自建镜像生成器（make_mirror.sh，可选）

若没有现成 Gitee 仓库、想完全自托管镜像，仓库内置 `make_mirror.sh`：在**能直连 GitHub** 的机器（通常是国外服务器）运行一次，即可把各 Release 的 tarball、`versions.json` 与最新 `sa-console.sh` 拉到本地目录，再将该目录通过 Web 服务 / 对象存储 + CDN 暴露为 https 地址，国内服务器把 `.update_mirror` 指向它即可。

```bash
SA_UPDATE_MIRROR_OUT=/var/www/site_analytics-mirror bash make_mirror.sh
# 不指定 OUT 时默认输出到 ./site_analytics-mirror
```

之后把输出目录暴露为 https（如 `https://<你的域名>/site_analytics-mirror/`），并在国内服务器执行 `echo 'https://<你的域名>/site_analytics-mirror' > /安装目录/.update_mirror`，升级 / 回滚即走你的自建镜像。

### 单命令（便于脚本 / 监控调用）

```bash
sa-console start | stop | restart | status | update
sa-console rollback <tag>          # 例如 sa-console rollback v1.2.0
```

> 版本管理基于 **GitHub Release（或等价的 Gitee 镜像）**：先在 GitHub 上发布一个带 `vX.Y.Z` 标签的 Release，控制台才能检查 / 升级 / 回滚；若配置了国内镜像源（`SA_UPDATE_MIRROR` 或安装目录下的 `.update_mirror`），则改从镜像读取版本列表与下载包。当前版本号记录在 `app.py` 的 `VERSION` 常量中（发版时改此处即可，控制台会自动比对并提示升级）。

---

## 站点部署令牌（防 tracker 盗用 / 抗压）

`/api/event` 是公开端点（埋点跑在访客浏览器里，无法强制登录）。但公开的 `tracker.js` 一旦被他人整段复制、嵌到自己的高流量站点，你的服务器就要为每个伪造访客做 GeoIP/ASN 解析 + 落库，产生不必要的压力。**站点部署令牌**让服务端只接受「携带正确令牌」的上报，把压力挡在落库之前。

### 工作原理

- 每个站点在面板「+ 添加站点」时，服务端自动为其生成**独立**的部署令牌（与其他站点互不相同）。
- 面板的「站点管理」会为**每个站点**生成已含该令牌的埋点代码，直接复制嵌入目标站即可——无需手动记令牌。
- 服务端在落库前校验令牌：非法/缺失令牌的**陌生站点**请求直接 `403` 拒绝，不产生任何 GeoIP/落库开销。
- 已接入的站点（面板里已添加、或已有历史数据的站点）即使暂时未带令牌也照常接收，保证现有监控数据平滑、零中断。

### 两种模式

| 模式 | 如何开启 | 已知站点（已有数据） | 陌生（新）站点 |
|---|---|---|---|
| **宽松模式（默认）** | 不额外配置 | 照常接收（无需令牌） | 无令牌则拒绝 |
| **严格模式** | 启动加 `--require-key` / `SA_REQUIRE_KEY=1` | 必须带正确令牌，否则拒绝 | 必须带正确令牌，否则拒绝 |

> 宽松模式的设计目的就是**平稳迁移**：你现有的站点（example.com 等）已在 `sites` 表 / 事件库里，属于「已知站点」，即使还没带令牌也照常上报、数据不断；只有**陌生域名**会被拦截。因此开启令牌后现有监控零中断。

### 启用步骤（推荐路径）

- **已有站点（升级前已在监控的站点）**：默认未启用每站点令牌、在「宽松模式」下照常接收，数据不断、零中断。要启用保护，在面板「站点管理」点该站点的「重新生成令牌」，用生成的新代码重新嵌入即可（旧嵌入在此之前仍正常记录）。
1. **添加站点**：在面板「+ 添加站点」填写要监控的域名，提交后「站点管理」里该站点即显示**已含部署令牌的埋点代码**，复制嵌入目标网站 `</body>` 前。
   - 想统一锁死所有站点：可设一个**全局兜底令牌**（`SA_DEPLOY_KEY` 环境变量或 `--deploy-key` 启动参数），任何站点可用；主要用于「严格模式」下一键管控。
2. **（可选）彻底锁死**：确认所有自有站点都用「站点管理」生成的代码正常上报后，启动加 `--require-key`（或环境变量 `SA_REQUIRE_KEY=1`）。此后连已知站点也必须带正确令牌，被盗用上报也会被拒。
3. **轮换 / 吊销**：在「站点管理」重新生成该站点的令牌（或改 `SA_DEPLOY_KEY` 全局令牌）并重新嵌入即可；旧令牌立即失效。

### 注意事项

- 令牌写在公开 JS 中，**不是密码学机密**——它挡的是「直接打 endpoint」「陌生域名盗用」这类最常见滥用，并支持随时轮换。对「完整盗走含令牌的 tracker.js 并原样复用」的针对性攻击无效（客户端代码无法保密）；那种情况应在反向代理层按来源 IP / 域名做白名单等额外限制。
- v1.4.0 起，未在面板添加、也无历史数据的陌生域名上报会被拒绝；如需接入新站点，请先在面板「+ 添加站点」获取带令牌的埋点代码。

---

## 嵌入埋点代码

**推荐**：在面板「站点管理」里为每个站点复制**自动生成的埋点代码**（已含上报地址与本站部署令牌，缓存插件友好），粘贴到目标网站 `</body>` 前即可。无需手敲、无需记令牌。

若手动嵌入，把下面这段放在每个页面的 `</body>` 之前（或全站公共模板里）：

```html
<script>
(function(){
  var s=document.createElement("script");
  s.src="https://你的分析域名/tracker.js";
  s.defer=true;
  s.setAttribute("data-endpoint","https://你的分析域名/api/event");
  document.head.appendChild(s);
})();
</script>
```

- 说明：脚本运行时动态加载 `tracker.js` 并向同域 `/api/event` 上报，已开放 CORS，无需额外配置；`data-endpoint` 显式指定上报地址，防止脚本被意外改造时算错目标。
- **`data-respect-dnt="true"`**（可选）：尊重浏览器「不跟踪（Do Not Track）」设置，开启后带 DNT 的访客不上报。
- **SPA / 前端路由**：`tracker.js` 监听 `pushState` / `popstate`，单页应用路由切换会自动按新路径上报，无需手动调用。
- **站点标识**：默认取当前 `location.hostname` 自动分组；多语言 / 子域站点见下方说明，无需手动指定。

### 面板内自动生成代码（推荐）

在面板顶栏点 **「+ 添加站点」**，填写要监控的域名（如 `example.com`，可带备注名），提交后「站点管理」里该站点即显示**已含部署令牌的埋点代码**，点「复制埋点代码」粘贴到目标网站 `</body>` 前即可。**无需重启后端**，新站点立即出现在顶部下拉框。
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
| `GET  /api/visitors?site=&days=&source=&refdomain=&inquiry=` | token* | 访客明细（含可疑 / 询盘计数，可按来源、引荐域、询盘筛选） |
| `GET  /api/months?site=` | token* | 该站点有数据的月份列表（面板按月切换） |
| `GET  /api/site` | token* | 手动注册的站点及备注（含每站点部署令牌） |
| `POST /api/site` | token* | 添加站点 `{"site","label"}`，自动生成独立部署令牌 |
| `POST /api/site/key` | token* | 重新生成某站点的部署令牌 `{"site"}` |
| `DELETE /api/site?site=` | token* | 删除站点（含其全部数据） |

> `token*`：仅当后端以 `--token` 启动时校验；未设置令牌则全部开放（同其他查询接口）。

---

## 指标口径说明

- **跳出率**：仅含 1 个 pageview 的会话 / 总会话。
- **平均停留**：按会话汇总 `pagehide` 上报的停留时长后取均值（关闭过快未触发上报的会话不计入）。
- **独立访客（UV）**：基于埋点分配的访客 ID（`localStorage`，约 1 年有效期），**非 IP**，因此不受 NAT / 共享出口 IP 影响，更接近真实人数。
- **会话**：基于访客 ID + 活跃窗口（默认 30 分钟无新事件则会话结束）划分。
- **页面性能（Core Web Vitals）精度说明**：
  - **FCP / LCP / TTFB / CLS 为真实用户测量（RUM）**：头部汇总取区间 **P75（第 75 分位）**，口径与 Google PageSpeed Insights 的 field data 一致；精度取决于采样量（面板右上角「采样」数 `perf_count`），样本越小、P75 置信区间越宽，建议以足够流量周期的数据为准。
  - **Speed Index 为合成估算值**：浏览器端无法获取逐帧截图，本项目以 FCP / LCP / TTFB 构造「视觉完成度曲线」积分得出，**并非 Lighthouse 实测 Speed Index**，仅作趋势参考，请勿当作绝对值解读（与真实值偏差可达 ±30%~50% 且不可校准）。UI 中该项已标注「(估算)」。
  - **口径偏差提示**：TTFB 仅含 `responseStart − requestStart`，**不含**连接 / TLS / 重定向耗时，故比标准 TTFB 偏小；LCP / CLS 在访客提前离开（未触发最终上报）时可能**偏低**；老版本浏览器 / 部分 Safari 不支持相关 Performance API，相关样本会被自动丢弃，整体样本偏向 Chromium 内核。
  - **头部 P75 与各页面 / 各设备均值口径不同**：头部汇总为 P75，而「各页面 / 各设备」明细表为**算术均值**，二者统计口径不同，数值不可直接横向比较。

---

## 异常流量标注与软屏蔽

为提升统计信噪比，面板对疑似非真实访客自动标注，且支持**无损软屏蔽**（原始事件保留、可恢复）。

### 运营商（ISP）识别
基于 GeoLite2-ASN 库（需安装 `maxminddb` 并放置 `geoip/GeoLite2-ASN.mmdb`），服务端按访客 IP 解析运营商。内网 / 本地 IP 显示「(内网/本地)」；未装 ASN 库或库缺失时该列留空、不报错。

### 疑似异常访客标注（满足任一即标记）
- **数据中心 / 云主机 / 爬虫托管 ISP**：运营商命中已知 AS 号或组织名关键词（AWS、Google Cloud、Azure、阿里云、腾讯云、华为云、Baidu、Cloudflare、OVH、Vultr、Hetzner、Datacamp、M247、Leaseweb 等；刻意排除 Starlink 等住宅卫星网络以免误伤真实用户）。显示为紫色「疑似数据采集」徽章。
- **单访客浏览量畸高**：该访客 PV ≥ 全部访客 PV 中位数 × 8，且 ≥ 30，且样本 ≥ 5 位访客时命中。显示为橙色「浏览量畸高」徽章。
- 两类条件为「或」关系，可并存；访客页顶部提示分别计数（`suspect_dc_count` / `suspect_highpv_count`）。

> 标注依赖 ISP 解析，须确保 ASN 库已部署并定期更新（`bash update_geoip.sh`），且反向代理已透传真实访客 IP（见「真实 IP 透传」）；若置于隐藏真实 IP 的代理之后，全部流量会被误判为机房网络。

### 软屏蔽（仅排除、可恢复）
在访客 / 实时监控表点该访客的「剔除」，即把其加入 `blocked_visitors`。所有统计经数据库视图 `visible_events` 自动排除其数据，但**原始事件完整保留**，可随时在「站点管理 → 已屏蔽访客」点「恢复」还原。读统计走视图、上报 / 删除等基表操作仍走 `events`，故屏蔽不丢原始数据、可无损还原。

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

### 数据停留在某天，之后没有新数据
看板数据停在某一日（如只有 7/9、7/10），说明之后 tracker 未成功上报。按序排查：

1. **确认部署代码是「通用部署代码」且已生效**：在 WP 后台确认 `</head>` 前存在那段**动态注入 loader**（以 `<script>(function(){...` 开头），而非旧的直接 `<script src=.../tracker.js>`。旧方式易被缓存插件本地化而失效。
2. **清缓存**：到 WP 缓存插件（WP Rocket / Autoptimize / W3TC 等）点「清空缓存」，避免浏览器 / 服务器返回旧页面与脚本。
3. **用调试模式验证上报**：在 loader 标签上加 `data-debug="true"`，打开浏览器控制台（F12 → Console），正常应看到：
   ```
   [tracker] site=de.example.com endpoint=https://你的分析域名/api/event
   [tracker] POST status 200
   ```
   若 `fetch failed` 或被 CSP / 网络拦截，检查分析域名是否可公网访问、有无跨域 / 防火墙限制。
4. **确认分析服务在跑**：`curl -I http://127.0.0.1:8899/` 应返回 200；`ps aux | grep app.py` 确认进程在运行（或用 `sa-console status`）。
5. 排除上述后仍有缺口，多为某段时间站点无真实访问或当时未部署 tracker，属正常；补部署并清缓存后新访问会实时进入看板。

> 多语言（WPML）子域：只需在「+ 添加站点」填**主域名**（不含 `www`，如 `example.com`），同一段代码粘贴到 `www` / `de` / `fr` 等子域，tracker 自动按 `location.hostname` 上报并归并，勿为每个子域分别添加。

---

## 贡献

欢迎 Issue 与 Pull Request！开发指南见 [CONTRIBUTING.md](CONTRIBUTING.md)。

- 本地开发与运行**只需 Python 标准库**，无需额外环境；仅启用 GeoIP 时才需 `pip install maxminddb`。
- 提交前请确认 `python3 app.py` 可正常启动、面板可打开。
- 代码风格保持与现有单文件 `app.py` / `index.html` 一致（零外部依赖优先）。

---

## 许可证

本项目以 [MIT License](LICENSE) 开源——可自由使用、修改、分发，但**不提供担保**，作者不对使用后果负责。请在分发时保留版权与许可声明。
