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

## 提交前自查

- [ ] `python3 app.py` 能启动，面板能打开且无 JS 报错。
- [ ] 改动未引入新的必需第三方依赖。
- [ ] 若改了面板文案，中英文均可正常显示。
- [ ] 不提交任何密钥、真实域名、访客数据或 `.mmdb` 数据库。

## 许可证

本项目以 [MIT License](LICENSE) 开源。提交贡献即表示你同意以相同许可方式授权你的修改。
