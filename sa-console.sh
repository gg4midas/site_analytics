#!/usr/bin/env bash
# ============================================================================
#  site_analytics 服务管理控制台（精简版）
#  用法（在服务器上）：
#     bash sa-console.sh            # 交互式菜单
#     sa-console                    # 若已软链到 /usr/local/bin（见文末说明）
#     sa-console start|stop|restart|status|update   # 单命令（便于脚本调用）
#  说明：自动定位安装目录（优先脚本同级目录，其次 /opt/site_analytics），
#        兼容「nohup + start.sh」与「systemd 服务」两种运行方式。
#  可选环境变量：SA_HOME  可强制指定安装目录（需含 app.py）。
# ============================================================================
set -u

# 控制台自身版本（与 app.py 的 VERSION 相互独立；发布新版时同步更新）
CONSOLE_VER="1.2.0"

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
    # 从监听端口所在行提取 pid=（仅 root 能看到其它用户的 pid；本服务同用户运行无碍）
    pids=$(ss -ltnp 2>/dev/null | awk -v port="$p" '
      $0 ~ "(^|[:.])" port "[[:>:]]" {
        for (i=1;i<=NF;i++) if ($i ~ /pid=[0-9]+/) { sub("pid=","",$i); print $i }
      }')
  elif command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti :"${p}" 2>/dev/null)
  fi
  if [ -z "$pids" ]; then
    pids=$(pgrep -f "[a]pp.py" 2>/dev/null)
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
    ss -ltn 2>/dev/null | grep -qE "[:.]${p}\b"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -i ":${p}" >/dev/null 2>&1
  else
    return 2
  fi
}

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
  sleep 1; do_status
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
  if port_listening "$p"; then echo "端口监听 : ${host}:${p} 已监听"; else echo "端口监听 : ${host}:${p} 未监听"; fi
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

# ---- 版本 ----
app_version() {
  local v=""
  if [ -f app.py ]; then
    v=$(grep -oE "VERSION\s*=\s*['\"][^'\"]+['\"]" app.py | head -1 | sed -E "s/^[^'\"]*['\"]//; s/['\"]$//")
  fi
  echo "${v:-未知}"
}

do_update_check() {
  local cur; cur="$(app_version)"
  echo "控制台版本 : $CONSOLE_VER"
  echo "应用版本 : $cur"
  echo "安装目录 : $INSTALL_DIR"
  if ! command -v curl >/dev/null 2>&1; then
    echo "未找到 curl，无法联网检查更新。"
    return
  fi
  local latest
  latest=$(curl -s --max-time 8 "https://api.github.com/repos/gg4midas/site_analytics/releases/latest" 2>/dev/null \
            | grep -oE '"tag_name"\s*:\s*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
  if [ -z "$latest" ]; then
    echo "无法获取最新版本（无网络或 GitHub 不可达）。"
    return
  fi
  local cur_n latest_n
  cur_n=$(echo "$cur" | sed -E 's/^v//')
  latest_n=$(echo "$latest" | sed -E 's/^v//')
  echo "最新版本 : $latest"
  if [ "$cur_n" = "$latest_n" ]; then
    echo "已是最新版本。"
    return
  fi
  echo "发现新版本 $latest（当前 $cur）。"
  read -r -p "是否更新？(y/N): " ans
  case "$ans" in
    y|Y) do_upgrade;;
    *) echo "已取消。";;
  esac
}

do_upgrade() {
  if [ -d "$INSTALL_DIR/.git" ]; then
    echo "正在 git pull ..."
    if ( cd "$INSTALL_DIR" && git pull --ff-only 2>&1 ); then
      echo "代码已更新，正在重启服务。"
      do_restart
    else
      echo "git pull 失败，请手动更新后重启。"
    fi
  else
    echo "当前不是 git 仓库，无法自动更新。"
    echo "请手动下载最新 zip 覆盖 $INSTALL_DIR 后重启服务。"
  fi
}

# ============================================================================
#  菜单
# ============================================================================
show_menu() {
  echo
  echo "=========== site_analytics 服务管理控制台 ==========="
  echo " 1: 检查版本更新"
  echo " 2: 启动服务"
  echo " 3: 关闭服务"
  echo " 4: 重启服务"
  echo " 0: 退出"
  echo "======================================================"
}

run_loop() {
  local choice
  while true; do
    show_menu
    read -r -p "请输入操作编号 (0-4): " choice
    case "$choice" in
      1) do_update_check;;
      2) do_start;;
      3) do_stop;;
      4) do_restart;;
      0|q|Q) echo "再见。"; exit 0;;
      *) echo "无效选项：$choice";;
    esac
  done
}

# 支持「无参数」交互，或「单参数直接执行」便于脚本调用：
#   sa-console status | start | stop | restart | update
case "${1:-}" in
  ""|menu) run_loop;;
  start)  do_start;;
  stop)   do_stop;;
  restart) do_restart;;
  status) do_status;;
  update) do_update_check;;
  *) echo "未知命令: $1（支持: start|stop|restart|status|update）"; exit 1;;
esac
