# 贡献指南（Contributing）

感谢你关注 **Site Analytics**！这是一个零必需依赖、自托管的网站访问分析工具。以下说明如何参与贡献。

## 行为准则

请保持友善、就事论事。提交内容应与项目目标一致：轻量、隐私友好、自托管、零外部依赖优先。

## 提 Issue

在提 Issue 前请先搜索是否已有相同或类似问题。Issue 建议包含：

- **环境**：操作系统、Python 版本、是否启用 GeoIP / 反向代理。
- **现象**：期望行为 vs 实际行为，附关键日志（`data/run.log` 或 `data/debug.log`）。
- **复现步骤**：尽量可一步步复现。

## 提 Pull Request

1. **Fork** 本仓库到你的账号。
2. 从 `main` 切出特性分支：`git checkout -b feat/你的改动`。
3. 提交改动，信息用中文或英文均可，尽量一句话说明意图（如 `fix: 修复地域图空数据时白屏`）。
4. 推送到你的 Fork：`git push origin feat/你的改动`。
5. 在 GitHub 发起 Pull Request 到 `gg4midas/site_analytics:main`，描述改动动机与验证方式。

## 本地开发环境

- **Python 3.7+**（推荐 3.10+）。核心功能仅用标准库，无需 `pip install`。
- 启用地域功能时才需：`pip install maxminddb`，并自行下载 GeoLite2 数据库放入 `geoip/`。
- 前端图表库 `static/echarts.min.js` 已随仓库，无需联网。

启动验证：

```bash
python3 app.py --host 127.0.0.1 --port 8899
# 浏览器打开 http://localhost:8899/ 确认面板可加载、无控制台报错
```

## 代码规范

- **零外部依赖优先**：后端只用 Python 标准库；新增第三方库需先讨论。
- **单文件结构**：后端集中在 `app.py`，面板集中在 `index.html`，尽量不动既有拆分。
- **界面文案**：面板支持中 / 英双语（顶栏切换）。新增用户可见文案请在 `index.html` 的 `I18N_EN` 字典中补充英文，并对 HTML 用 `data-i18n`、对 JS 动态文本用 `t('中文')` 包裹。
- **GeoIP 等为可选增强**：缺失时必须优雅降级，不影响其它功能。

## 回归测试

仓库自带一组纯 Python 标准库 / bash 的回归脚本，位于 `tests/`。从**仓库根**运行，脚本会自动定位 `app.py`（同时兼容「放在 `tests/` 下」与「仍在工作区根」两种位置，也可用环境变量 `SA_APP_PATH` / `SA_CONSOLE_PATH` 覆盖）：

```bash
python tests/test_client_ip.py
python tests/test_v160_shell.py
python tests/test_register_gate.py
```

所有脚本使用独立的临时 `--data-dir` 与随机端口，不碰生产数据；运行期临时产物（数据目录、截图、`__pycache__`）统一写入系统临时目录，不落在仓库工作树里。

已知前置条件：

1. **注册门控**：靠 `/api/register` 做引导登录的老测试（如 `test_v151_login_contract.py`、`test_v160_shell.py`、`test_logout_login_repro.py`）会因 v1.8.6 起自助注册默认关闭而失败，必须设 `SA_ALLOW_REGISTER=1`（多数脚本内已自带该开关）。
2. **Playwright UI 验收**：`.cjs` 脚本需要 `NODE_PATH` 指向本地 `node_modules`，并指定 `channel: 'chrome'` 走系统 Chrome；无头环境不要依赖默认 bundled Chromium。
3. **区间选择**：无头 UI 验收要把日期区间切到「过去 28 天」，默认 today 无数据会把「面板空白」误判成功能故障。
4. **控制台错误断言**：要按 URL 过滤。登录页必然出现 `/api/me` 的 401 与 `/favicon.ico` 的 404，属预期噪声，不应计入失败。

### 发版顺序铁律

`sha256sums.txt` 必须在**所有代码定稿之后、`git tag` 之前**由 `sync_final_v180.py` 生成，并 commit 进 tag 树（详见「发布与维护」）。否则 tag 对应的 raw 清单地址返回 404，线上升级校验会永久降级为告警。

`sha256sums.txt` 只列 18 个运行时文件，`tests/` 不在其中；但升级 / 回滚下载的是 tag tarball（`archive/refs/tags/$tag.tar.gz`，含该 tag 树的全部 tracked 文件）会带上 `tests/`，因此 `sa-console.sh` 的清单外文件白名单必须放行它们，否则整个安装会被「归档含清单外文件」直接拒绝。白名单**只放行 `tests/` 顶层的 `.py` 回归脚本**（正则 `tests/[A-Za-z0-9_.-]+\.py`）；非 `.py`、子目录路径与 `..` 穿越一律拒绝，不依赖 tar 条目检查兜底。

## 提交前自查

- [ ] `python3 app.py` 能启动，面板能打开且无 JS 报错。
- [ ] 改动未引入新的必需第三方依赖。
- [ ] 若改了面板文案，中英文均可正常显示。
- [ ] 不提交任何密钥、真实域名、访客数据或 `.mmdb` 数据库。

## 发布与维护

本节约束发版顺序与 Gitee 镜像分支同步，供维护者执行发布时遵循。

### 发版顺序：`sha256sums.txt` 必须进 tag 树

- `sha256sums.txt` 必须在**所有代码定稿之后、`git tag` 之前**生成并 commit 进 tag 树。清单若只存在于工作树、不在 tag 提交里，tag 对应的 raw 地址会返回 404，线上升级校验将**永久降级为告警**（默认不设 `SA_REQUIRE_CHECKSUM` 时只告警继续，等于失去强制校验）。
- 验证清单确实在 tag 树里：`git cat-file -e <tag>:sha256sums.txt` 必须成功；且清单每一行的 hex 必须与 `git show <tag>:<rel>` 的 sha256 一致。
- 判断「发布是否漏文件」时，必须用 `git show <tag>:<file>` 取 tag 树里的文件算 sha256 再跟生产环境比对，**不能拿工作树的文件比**——工作树可能已包含尚未发版的改动。

### Gitee 分支同步铁律

- **禁止**把 `main` 直接推到 Gitee 的 `main`（包括 `git push gitee main`、`git push gitee main --tags`、`git push gitee main:main` 这类写法）：这会把 `README_EN.md` 推到 Gitee 的 `main`。以上仅为警示，切勿作为可执行命令复制运行。
- 正确做法：先把 `main` 合并到 `gitee` 分支，再用 `git push gitee gitee:main` 推送；tag 单独推送，不要随分支一起推 `--tags`。
- `gitee` 分支必须删除 `README_EN.md`，并去掉中文 `README.md` 顶部的英文链接行，否则页面会出现断链。

> 背景：`sha256sums.txt` 只列运行时文件、排除文档，正是因为 Gitee 分支与 main 的 `README.md` 字节不同且缺少 `README_EN.md`；按分支打包的镜像若用全量清单会误报。详见两份 README 的「升级完整性校验」。

## 许可证

本项目以 [MIT License](LICENSE) 开源。提交贡献即表示你同意以相同许可方式授权你的修改。
