#!/usr/bin/env bash
# ============================================================================
#  site_analytics 服务管理控制台（精简版）
#  用法（在服务器上）：
#     bash sa-console.sh                              # 交互式菜单
#     sa-console                                      # 若已软链到 /usr/local/bin
#     sa-console start|stop|restart|status|health|logs|update   # 单命令（便于脚本调用）
#     sa-console rollback <tag>                        # 单命令回滚（如 v1.2.0）
#  说明：自动定位安装目录（优先脚本同级目录，其次 /opt/site_analytics），
#        兼容「nohup + start.sh」与「systemd 服务」两种运行方式。
#  版本管理：检查 / 升级 / 回滚均基于 GitHub Release（tarball）。
#        升级与回滚都会保留 data/ 数据库与本地配置，仅覆盖代码文件。
#  可选环境变量：SA_HOME  可强制指定安装目录（需含 app.py）。
#  可选环境变量：SA_UPDATE_MIRROR  国内镜像源（解决 codeload.github.com 被墙问题）。
#        取值可为「基址」如 https://mirror.example.com/sa  （控制台拼成 <基址>/<tag>.tar.gz，并读 <基址>/versions.json 取列表），
#        也可含 {tag} 占位符，如 https://gitee.com/u/r/repository/archive/{tag}.tar.gz（Gitee 模式，列表改查 Gitee tags API）。
#        设置后：下载优先走镜像、失败再回退 github/codeload；Gitee 模式要求仓库为「公开」。
#        也可把镜像地址写入安装目录下的 .update_mirror（一行一个 URL），持久生效。
# ============================================================================
set -u

# 控制台自身版本（与 app.py 的 VERSION 相互独立；发布新版时同步更新）
CONSOLE_VER="1.4.10"

# GitHub 仓库（用于版本检查 / 升级 / 回滚）
GITHUB_REPO="gg4midas/site_analytics"
GH_API="https://api.github.com/repos/${GITHUB_REPO}"

# ---- 定位安装目录 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
if [ -n "${SA_HOME:-}" ] && [ -f "$SA_HOME/app.py" ]; then
  INSTALL_DIR="$SA_HOME"
elif [ -f "$SCRIPT_DIR/app.py" ]; then
  INSTALL_DIR="$SCRIPT_DIR"
elif [ -f /opt/site_analytics/app.py ]; then
  INSTALL_DIR=/opt/site_analytics
else
  echo "无法定位 site_analytics 安装目录（未找到 app.py）。请 cd 到安装目录后运行，或设置 SA_HOME=安装目录。" >&2
  exit 1
fi
cd "$INSTALL_DIR" || exit 1

# 可选：国内镜像源（.update_mirror 文件持久化，覆盖 SA_UPDATE_MIRROR 环境变量）
if [ -z "${SA_UPDATE_MIRROR:-}" ] && [ -f "$INSTALL_DIR/.update_mirror" ]; then
  SA_UPDATE_MIRROR="$(head -1 "$INSTALL_DIR/.update_mirror" 2>/dev/null | tr -d '[:space:]')"
fi

# 脚本自身绝对路径（升级/回滚后用于重新执行磁盘上的新版本）
SELF="$INSTALL_DIR/sa-console.sh"
# 是否处于交互菜单模式（单命令模式下升级/回滚后不应重新进入菜单）
INTERACTIVE=0

SERVICE_NAME="site_analytics"
SVC_FILE_SYS="/etc/systemd/system/${SERVICE_NAME}.service"
SVC_FILE_LOCAL="${INSTALL_DIR}/${SERVICE_NAME}.service"
DATA_DIR="${DATA_DIR:-${INSTALL_DIR}/data}"
LOG_FILE="${INSTALL_DIR}/run.log"
PY="$(command -v python3 || command -v python)"

# ============================================================================
#  配置读取（仅读，用于展示）
# ============================================================================
read_cfg() {
  # $1 = port|token|host
  local key="$1" val=""
  if [ -f "$SVC_FILE_LOCAL" ]; then
    case "$key" in
      port)  val=$(grep -oE '\--port [0-9]+' "$SVC_FILE_LOCAL" | awk '{print $2}');;
      token) val=$(grep -oE '\--token [^ ]+' "$SVC_FILE_LOCAL" | sed 's/--token //');;
      host)  val=$(grep -oE '\--host [0-9A-Za-z.:]+' "$SVC_FILE_LOCAL" | awk '{print $2}');;
    esac
  fi
  if [ -z "$val" ] && [ -f start.sh ]; then
    case "$key" in
      port)  val=$(grep -oE 'PORT="\$\{PORT:-[0-9]+\}"' start.sh | grep -oE '[0-9]+');;
      token) val=$(grep -oE 'TOKEN="\$\{TOKEN:-[^"]*\}"' start.sh | sed -E 's/TOKEN="\$\{TOKEN:-//; s/\}"$//');;
    esac
  fi
  case "$key" in
    port)  echo "${val:-8899}";;
    host)  echo "${val:-127.0.0.1}";;
    token) echo "${val:-}";;
  esac
}

# ============================================================================
#  运行态检测
# ============================================================================
# 关键点：start.sh 以「相对路径 python3 app.py」启动，进程 cmdline 里没有绝对
# 安装目录，因此不能用「cmdline 是否含 $INSTALL_DIR/app.py」来判定。
# 改为以「监听端口反查 PID」为主（最可靠），pgrep app.py 兜底。
find_pids() {
  local p="$(read_cfg port)" pids=""
  if command -v ss >/dev/null 2>&1; then
    # 找到监听该端口的行（端口后必须非数字，避免 8899 误匹配 88999），再提取其中的 pid=
    pids=$(ss -ltnp 2>/dev/null | grep -E "[:.]${p}([^0-9]|$)" | grep -oE 'pid=[0-9]+' | sed 's/pid=//' | sort -u)
  elif command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti :"${p}" 2>/dev/null | sort -u)
  fi
  if [ -z "$pids" ]; then
    pids=$(pgrep -f "[a]pp.py" 2>/dev/null | sort -u)
  fi
  # 只保留纯数字 PID，过滤空行/多余空白
  echo "$pids" | grep -oE '[0-9]+' | sort -u
}

is_systemd() { [ -f "$SVC_FILE_SYS" ] && command -v systemctl >/dev/null 2>&1; }

svc_active() {
  is_systemd || return 1
  [ "$(systemctl is-active "$SERVICE_NAME" 2>/dev/null)" = "active" ]
}

port_listening() {
  local p="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -qE "[:.]${p}([^0-9]|$)"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -i ":${p}" >/dev/null 2>&1
  else
    return 2
  fi
}

# 等待应用真正就绪：优先 HTTP 探针（直连本机，不受反向代理影响），其次端口监听；
# 最多轮询约 30 秒，覆盖升级后冷启动较慢的场景，避免误报「未监听」。
wait_ready() {
  local p="$1" host="$2" waited=0 code
  while [ "$waited" -lt 30 ]; do
    if port_listening "$p"; then return 0; fi
    if command -v curl >/dev/null 2>&1; then
      code=$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${p}/" 2>/dev/null)
      if [ "${code:0:1}" = "2" ] && [ -n "$code" ]; then return 0; fi
    fi
    sleep 1; waited=$((waited+1))
  done
  return 1
}

# 升级/回滚后，当前进程仍是旧脚本的内存副本，需重新执行磁盘上的新脚本以加载新菜单。
reload_self() { exec bash "$SELF"; }

# ============================================================================
#  动作
# ============================================================================
do_start() {
  if svc_active; then echo "服务已在运行（systemd active）。"; return; fi
  if port_listening "$(read_cfg port)"; then
    echo "端口 $(read_cfg port) 已被占用，启动中止。先选「关闭服务」或释放端口。"
    return
  fi
  if is_systemd; then
    systemctl start "$SERVICE_NAME" && echo "已通过 systemd 启动。"
  else
    bash start.sh && echo "已通过 start.sh 后台启动。"
  fi
  # 等待端口真正就绪（app 启动需加载 GeoIP 库 / 初始化数据库，可能耗时数秒；
  # 升级后首次冷启动更慢）。用 HTTP 探针最多轮询约 30 秒，避免误报「未监听」。
  wait_ready "$(read_cfg port)" "$(read_cfg host)"
  do_status
}

do_stop() {
  if svc_active; then systemctl stop "$SERVICE_NAME" && echo "已停止 systemd 服务。"; fi
  local pids; pids="$(find_pids | tr '\n' ' ')"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null && echo "已停止进程: $pids" || echo "停止进程失败: $pids"
    sleep 1
  fi
  [ -z "$pids" ] && ! svc_active && echo "未发现运行中的进程。"
}

do_restart() { do_stop; sleep 1; do_start; }

do_status() {
  local p="$(read_cfg port)" host="$(read_cfg host)" pids tok
  pids="$(find_pids | tr '\n' ' ')"
  echo "安装目录 : $INSTALL_DIR"
  echo "运行方式 : $(is_systemd && echo systemd || echo nohup/start.sh)"
  if svc_active || [ -n "$pids" ]; then
    echo "服务状态 : 运行中"
    [ -n "$pids" ] && echo "进程 PID : $pids"
  else
    echo "服务状态 : 未运行"
  fi
  if port_listening "$p"; then
    echo "端口监听 : ${host}:${p} 已监听"
  elif command -v curl >/dev/null 2>&1; then
    code=$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${p}/" 2>/dev/null)
    if [ "${code:0:1}" = "2" ] && [ -n "$code" ]; then
      echo "端口监听 : ${host}:${p} 已监听"
    else
      echo "端口监听 : ${host}:${p} 未监听"
    fi
  else
    echo "端口监听 : ${host}:${p} 未监听"
  fi
  tok="$(read_cfg token)"
  if [ -n "$tok" ]; then echo "访问令牌 : 已设置（面板需 ?token=...）"; else echo "访问令牌 : 未设置（建议配合反向代理 + 访问控制）"; fi
  echo "应用版本 : $(app_version)"
}

do_logs() {
  if [ -f "$LOG_FILE" ]; then
    echo "===== 最近 40 行 run.log ====="
    tail -n 40 "$LOG_FILE"
  else
    echo "未找到日志文件 $LOG_FILE"
  fi
}

do_health() {
  local p="$(read_cfg port)" host="$(read_cfg host)" pids code ok=1
  echo "===== 健康检查 ====="
  echo "安装目录 : $INSTALL_DIR"
  echo "运行方式 : $(is_systemd && echo systemd || echo nohup/start.sh)"
  pids="$(find_pids | tr '\n' ' ')"
  if [ -n "$pids" ]; then echo "进程     : 运行中 (PID: $pids)"; else echo "进程     : 未运行"; ok=0; fi
  if port_listening "$p"; then echo "端口监听 : ${host}:${p} 已监听"; else echo "端口监听 : ${host}:${p} 未监听（若已设反向代理，应用仍需在本机该端口监听，代理只是转发，不会替应用监听）"; ok=0; fi
  if command -v curl >/dev/null 2>&1; then
    code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${p}/" 2>/dev/null)
    if [ "${code:0:1}" = "2" ] && [ -n "$code" ]; then
      echo "HTTP 探针 : http://127.0.0.1:${p}/ 返回 $code（正常；直连本机应用，不受反向代理影响）"
    else
      echo "HTTP 探针 : http://127.0.0.1:${p}/ 返回『${code:-无响应}』（异常）"
      ok=0
    fi
  else
    echo "HTTP 探针 : 未找到 curl，跳过"
  fi
  if [ -d "$DATA_DIR" ] && [ -w "$DATA_DIR" ]; then echo "数据目录 : $DATA_DIR（存在且可写）"; else echo "数据目录 : $DATA_DIR（缺失或不可写）"; ok=0; fi
  if [ "$ok" = "1" ]; then echo "结论     : 健康 ✅"; else echo "结论     : 异常 ⚠️  请结合『7: 查看日志』排查"; fi
}

do_genkey() {
  # 生成可选「全局兜底部署令牌」（SA_DEPLOY_KEY）。每站点独立令牌由面板自动生成，本命令仅作统一管控用。
  local key
  if command -v python3 >/dev/null 2>&1; then
    key=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))" 2>/dev/null)
  fi
  if [ -z "$key" ]; then
    key=$(head -c 18 /dev/urandom 2>/dev/null | base64 2>/dev/null | tr '+/' '-_' | tr -d '=' | head -c 24)
  fi
  [ -z "$key" ] && key="$(date +%s%N)_deploykey"
  echo "===== 全局兜底部署令牌（SA_DEPLOY_KEY）====="
  echo "生成的令牌: $key"
  echo ""
  echo "启用方式（任选其一）："
  echo "  1) 启动参数（临时）： python3 app.py --deploy-key '$key' --port 8899"
  echo "  2) 环境变量（推荐，写入 systemd 单元 Environment=SA_DEPLOY_KEY=$key）："
  echo "       SA_DEPLOY_KEY=$key"
  echo ""
  echo "说明：每个站点的独立令牌由面板「站点管理」自动生成并显示在埋点代码里，复制即用。"
  echo "本命令生成的是可选的「全局兜底令牌」，任何站点都可使用。"
  echo ""
  echo "模式说明："
  echo "  - 默认「宽松模式」：已知站点（已有数据）照常接收，仅拦截陌生站点 —— 现有监控零中断。"
  echo "  - 严格模式：启动加 --require-key（或 SA_REQUIRE_KEY=1），所有站点都须带正确令牌（站点令牌或全局令牌）。"
  echo "    建议：先在面板「站点管理」为每个站点复制带令牌的代码嵌入，确认无误后再开启 --require-key 彻底锁死。"
}

# ============================================================================
#  版本管理（基于 GitHub Release）
# ============================================================================
app_version() {
  local v=""
  if [ -f app.py ]; then
    v=$(grep -oE "VERSION\s*=\s*['\"][^'\"]+['\"]" app.py | head -1 | sed -E "s/^[^'\"]*['\"]//; s/['\"]$//")
  fi
  echo "${v:-未知}"
}

# 取「版本号最高」的 Release tag（按 semver 排序，而非发布时间；无 Release 时返回空）。
# 注意：GitHub /releases/latest 按「发布时间」返回，并非最高版本，故这里用全量列表 + sort -V 取最大。
latest_release_tag() {
  command -v curl >/dev/null 2>&1 || { echo ""; return; }
  list_release_tags | sort -V | tail -1
}

# 列出所有 Release tag（按 GitHub 返回顺序，通常最新在前）
list_release_tags() {
  command -v curl >/dev/null 2>&1 || { echo ""; return; }
  # 国内镜像优先
  if [ -n "${SA_UPDATE_MIRROR:-}" ]; then
    case "$SA_UPDATE_MIRROR" in
      *gitee.com*)
        # Gitee 模板：从 archive 地址反推 owner/repo，查 Gitee tags API
        # （要求 Gitee 仓库为「公开」，否则匿名无法列标签/下包）
        local owner repo gt
        owner=$(echo "$SA_UPDATE_MIRROR" | sed -E 's#https://gitee\.com/([^/]+)/.*#\1#')
        repo=$(echo  "$SA_UPDATE_MIRROR" | sed -E 's#https://gitee\.com/[^/]+/([^/]+)/repository/archive.*#\1#')
        if [ -n "$owner" ] && [ -n "$repo" ]; then
          gt=$(curl -fsSL --max-time 20 "https://gitee.com/api/v5/repos/$owner/$repo/tags?per_page=30" 2>/dev/null \
               | grep -oE '"name"\s*:\s*"[^"]+"' | sed -E 's/.*"([^"]+)".*/\1/' \
               | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -30)
          if [ -n "$gt" ]; then echo "$gt"; return; fi
        fi
        ;;
      *'{tag}'*)
        # 自定义 {tag} 模板（非 gitee）：没有版本清单，回退 GitHub API
        ;;
      *)
        # 目录式镜像：<基址>/versions.json -> {"latest":"vX","tags":["vX",...]}
        local mj="${SA_UPDATE_MIRROR%/}/versions.json"
        local mt
        mt=$(curl -fsSL --max-time 20 "$mj" 2>/dev/null | grep -oE '"v[0-9][0-9.]*"' | tr -d '"' | sort -u)
        if [ -n "$mt" ]; then echo "$mt"; return; fi
        ;;
    esac
  fi
  # 回退 GitHub API
  curl -s --max-time 10 -H "Accept: application/vnd.github+json" "$GH_API/releases?per_page=30" 2>/dev/null \
    | grep -oE '"tag_name"\s*:\s*"[^"]+"' | sed -E 's/.*"([^"]+)".*/\1/'
}

# 某 tag 的源码 tarball 下载地址
release_tarball() { echo "https://github.com/${GITHUB_REPO}/archive/refs/tags/$1.tar.gz"; }

# 把版本号归一化（去掉前导 v 与非数字字符）后比较：返回 0 表示 $1 >= $2
ver_ge() { [ "$(printf '%s\n%s\n' "${1#v}" "${2#v}" | sed 's/[^0-9.]//g' | sort -V | tail -1)" = "${1#v}" ]; }

# 下载 tarball（带重试与真实错误输出），供升级/回滚复用。
# 用法：download_tarball <url> <outfile> <errfile>  —— 返回 0 成功。
# 国内访问 GitHub/codeload 经常偶发超时，故单地址重试 2 次；多地址的兜底
# 由 do_install_release 的候选列表负责。curl 真实错误写到 errfile。
download_tarball() {
  local url="$1" out="$2" err="$3" i tries=2
  for i in 1 2; do
    if curl -fsSL --max-time 60 -o "$out" "$url" 2>"$err"; then
      return 0
    fi
    if [ "$i" -lt "$tries" ]; then
      echo "  第 $i 次下载未成功，2 秒后重试..."
      sleep 2
    fi
  done
  return 1
}

# 下载指定 tag 的 tarball，覆盖代码文件（保留 data/ 数据库与本地配置），重启服务。
# 同时被「升级」与「回滚」复用。
do_install_release() {
  local tag="$1" label="$2"
  if ! command -v curl >/dev/null 2>&1; then echo "未找到 curl，无法下载。"; return 1; fi
  local tmp; tmp=$(mktemp -d)
  # 候选下载地址（按顺序尝试）：国内镜像优先（若配置），其次 github，最后 codeload 直连兜底
  local cand="" u
  if [ -n "${SA_UPDATE_MIRROR:-}" ]; then
    case "$SA_UPDATE_MIRROR" in
      *'{tag}'*) cand="$cand ${SA_UPDATE_MIRROR/{tag\}/$tag}";;
      *) cand="$cand ${SA_UPDATE_MIRROR%/}/$tag.tar.gz";;
    esac
  fi
  cand="$cand https://github.com/${GITHUB_REPO}/archive/refs/tags/$tag.tar.gz"
  cand="$cand https://codeload.github.com/${GITHUB_REPO}/tar.gz/refs/tags/$tag"
  echo "正在下载 $tag ..."
  local ok=0 used=""
  for u in $cand; do
    if download_tarball "$u" "$tmp/arc.tar.gz" "$tmp/curl.err"; then ok=1; used="$u"; break; fi
  done
  if [ "$ok" -ne 1 ]; then
    echo "下载失败，请检查网络或手动更新。"
    if [ -s "$tmp/curl.err" ]; then echo "curl 详细错误："; sed 's/^/  /' "$tmp/curl.err"; fi
    echo "  已尝试地址：$cand"
    rm -rf "$tmp"; return 1
  fi
  echo "已从以下源下载成功：$(basename "$used")"
  if [ ! -s "$tmp/arc.tar.gz" ]; then echo "下载内容为空，已中止。"; rm -rf "$tmp"; return 1; fi
  mkdir -p "$tmp/x"
  if ! tar -xzf "$tmp/arc.tar.gz" -C "$tmp/x" 2>/dev/null; then echo "解压失败。"; rm -rf "$tmp"; return 1; fi
  local src; src=$(find "$tmp/x" -maxdepth 1 -mindepth 1 -type d | head -1)
  if [ -z "$src" ] || [ ! -f "$src/app.py" ]; then echo "解包结果异常（未找到 app.py），已中止。"; rm -rf "$tmp"; return 1; fi
  echo "已下载，正在覆盖文件（保留 data/ 数据库与本地配置）..."
  do_stop
  sleep 1
  # 用 tar 同步代码文件，排除版本库 / 数据库 / 日志 / data（保留已采集数据）
  ( cd "$src" && tar -cf - --exclude='.git' --exclude='*.db' --exclude='run.log' --exclude='data' --exclude='geoip/GeoLite2-City.mmdb' . ) \
    | ( tar -xf - -C "$INSTALL_DIR" )
  [ -f "$INSTALL_DIR/sa-console.sh" ] && chmod +x "$INSTALL_DIR/sa-console.sh"
  echo "已更新至 $(app_version)（$label）。"
  rm -rf "$tmp"
  do_start
}

do_update_check() {
  local cur; cur="$(app_version)"
  echo "控制台版本 : $CONSOLE_VER"
  echo "应用版本 : $cur"
  echo "安装目录 : $INSTALL_DIR"
  if ! command -v curl >/dev/null 2>&1; then
    echo "未找到 curl，无法联网检查更新。"; return
  fi
  local latest; latest="$(latest_release_tag)"
  if [ -z "$latest" ]; then
    echo "尚未发布 GitHub Release，无法比对版本。"
    echo "可到 https://github.com/${GITHUB_REPO}/releases 查看，或手动更新。"
    return
  fi
  echo "最新稳定版 : $latest"
  if ver_ge "$cur" "$latest"; then
    echo "已是最新稳定版。"
    return
  fi
  echo "发现新版本 $latest（当前 $cur）。"
  read -r -p "是否下载更新并重启？(y/N): " ans
  case "$ans" in
    y|Y)
      do_install_release "$latest" "升级到 $latest"
      [ "$INTERACTIVE" = "1" ] && reload_self;;
    *) echo "已取消.";;
  esac
}

do_rollback() {
  if ! command -v curl >/dev/null 2>&1; then
    echo "未找到 curl，无法联网获取版本列表。"; return
  fi
  local cur; cur="$(app_version)"
  echo "当前版本 : $cur"
  echo "可用版本（镜像源已发布，GitHub/Gitee）："
  local tags; tags="$(list_release_tags)"
  if [ -z "$tags" ]; then echo "暂无可回滚的 Release。"; return; fi
  local i=1 t
  while IFS= read -r t; do
    [ -z "$t" ] && continue
    local mark=""; [ "$t" = "$cur" ] && mark=" (当前)"
    printf "  %d: %s%s\n" "$i" "$t" "$mark"
    i=$((i+1))
  done <<< "$tags"
  echo "  0: 取消"
  local sel
  read -r -p "请选择要回滚到的版本编号: " sel
  if [ "$sel" = "0" ] || [ -z "$sel" ]; then echo "已取消。"; return; fi
  local chosen="" j=1
  while IFS= read -r t; do
    [ -z "$t" ] && continue
    if [ "$j" = "$sel" ]; then chosen="$t"; break; fi
    j=$((j+1))
  done <<< "$tags"
  if [ -z "$chosen" ]; then echo "无效选择。"; return; fi
  echo "即将回滚到 $chosen（会保留 data/ 数据库与本地配置，并重启服务）。"
  read -r -p "确认？(y/N): " ans
  case "$ans" in
    y|Y)
      do_install_release "$chosen" "回滚到 $chosen"
      [ "$INTERACTIVE" = "1" ] && reload_self;;
    *) echo "已取消.";;
  esac
}

# ============================================================================
#  菜单
# ============================================================================
show_menu() {
  echo
  echo "=========== site_analytics 服务管理控制台 ==========="
  echo " 1: 检查版本更新（升级）"
  echo " 2: 回滚到旧版本"
  echo " 3: 启动服务"
  echo " 4: 关闭服务"
  echo " 5: 重启服务"
  echo " 6: 健康检查"
  echo " 7: 查看日志"
  echo " 0: 退出"
  echo "======================================================"
}

run_loop() {
  INTERACTIVE=1
  local choice
  while true; do
    show_menu
    read -r -p "请输入操作编号 (0-7): " choice
    case "$choice" in
      1) do_update_check;;
      2) do_rollback;;
      3) do_start;;
      4) do_stop;;
      5) do_restart;;
      6) do_health;;
      7) do_logs;;
      0|q|Q) echo "再见。"; exit 0;;
      *) echo "无效选项：$choice";;
    esac
  done
}

# 支持「无参数」交互，或「单参数直接执行」便于脚本调用：
#   sa-console status | start | stop | restart | update | rollback <tag> | key
case "${1:-}" in
  ""|menu) run_loop;;
  start)  do_start;;
  stop)   do_stop;;
  restart) do_restart;;
  status) do_status;;
  health) do_health;;
  logs)   do_logs;;
  key)    do_genkey;;
  update) do_update_check;;
  rollback)
    if [ -z "${2:-}" ]; then
      echo "用法: sa-console rollback <tag>   （例如 sa-console rollback v1.2.0）"
      echo "可用 tag 见: https://github.com/${GITHUB_REPO}/releases"
      exit 1
    fi
    do_install_release "$2" "回滚到 $2";;
  *) echo "未知命令: $1（支持: start|stop|restart|status|update|rollback <tag>|key）"; exit 1;;
esac
