#!/usr/bin/env bash
# ============================================================================
#  site_analytics 服务管理控制台
#  用法（在服务器上）：
#     bash sa-console.sh            # 交互式菜单
#     sa-console                    # 若已软链到 /usr/local/bin（见文末说明）
#  说明：本脚本自动定位安装目录（优先脚本同级目录，其次 /opt/site_analytics），
#        兼容「nohup + start.sh」与「systemd 服务」两种运行方式，统一托管。
#  可选环境变量：SA_HOME  可强制指定安装目录（需含 app.py）。
# ============================================================================
set -u

# 控制台自身版本（与 app.py 的 VERSION 相互独立；发布新版时同步更新）
CONSOLE_VER="1.1.0"

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

# ---- 颜色（非强制，失败则降级） ----
if [ -t 1 ]; then
  C_B="\033[1;36m"; C_G="\033[1;32m"; C_Y="\033[1;33m"; C_R="\033[1;31m"; C_0="\033[0m"
else
  C_B=""; C_G=""; C_Y=""; C_R=""; C_0=""
fi

# ============================================================================
#  配置读写
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

write_cfg() {
  # $1 = port|token|host   $2 = newvalue
  local key="$1" nv="$2"
  case "$key" in
    port)
      [ -f start.sh ] && sed -i "s/PORT=\"\${PORT:-[0-9]*}\"/PORT=\"\${PORT:-${nv}}\"/" start.sh
      [ -f "$SVC_FILE_LOCAL" ] && sed -i "s/--port [0-9]*/--port ${nv}/" "$SVC_FILE_LOCAL"
      [ -f "$SVC_FILE_SYS" ] && sed -i "s/--port [0-9]*/--port ${nv}/" "$SVC_FILE_SYS"
      ;;
    host)
      [ -f start.sh ] && sed -i "s/--host [0-9A-Za-z.:]*/--host ${nv}/" start.sh
      [ -f "$SVC_FILE_LOCAL" ] && sed -i "s/--host [0-9A-Za-z.:]*/--host ${nv}/" "$SVC_FILE_LOCAL"
      [ -f "$SVC_FILE_SYS" ] && sed -i "s/--host [0-9A-Za-z.:]*/--host ${nv}/" "$SVC_FILE_SYS"
      ;;
    token)
      [ -f "$SVC_FILE_LOCAL" ] && sed -i "s/--token [^ ]*/--token ${nv}/" "$SVC_FILE_LOCAL"
      [ -f "$SVC_FILE_SYS" ] && sed -i "s/--token [^ ]*/--token ${nv}/" "$SVC_FILE_SYS"
      [ -f start.sh ] && sed -i "s#TOKEN=\"\${TOKEN:-[^\"]*}\"#TOKEN=\"\${TOKEN:-${nv}}\"#" start.sh
      ;;
  esac
  echo -e "${C_G}已更新 ${key} = ${nv}（下次启动/重启后生效）${C_0}"
}

# ============================================================================
#  运行态检测
# ============================================================================
find_pids() {
  pgrep -f "app.py" 2>/dev/null | while read -r pid; do
    if [ -r "/proc/${pid}/cmdline" ] && tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null | grep -q "${INSTALL_DIR}/app.py"; then
      echo "$pid"
    fi
  done
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
  if svc_active; then echo -e "${C_Y}服务已在运行（systemd active）。${C_0}"; return; fi
  if port_listening "$(read_cfg port)"; then echo -e "${C_R}端口 $(read_cfg port) 已被占用，启动中止。先选「停止服务」或释放端口。${C_0}"; return; fi
  if is_systemd; then
    systemctl start "$SERVICE_NAME" && echo -e "${C_G}已通过 systemd 启动。${C_0}"
  else
    bash start.sh && echo -e "${C_G}已通过 start.sh 后台启动。${C_0}"
  fi
  sleep 1; do_status
}

do_stop() {
  if svc_active; then systemctl stop "$SERVICE_NAME" && echo -e "${C_G}已停止 systemd 服务。${C_0}"; fi
  local pids; pids="$(find_pids | tr '\n' ' ')"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null && echo -e "${C_G}已停止进程: $pids${C_0}" || echo -e "${C_R}停止进程失败: $pids${C_0}"
  fi
  [ -z "$pids" ] && ! svc_active && echo -e "${C_Y}未发现运行中的进程。${C_0}"
}

do_restart() { do_stop; sleep 1; do_start; }

do_status() {
  local p="$(read_cfg port)" host="$(read_cfg host)" pids tok
  pids="$(find_pids | tr '\n' ' ')"
  echo "安装目录 : $INSTALL_DIR"
  echo "运行方式 : $(is_systemd && echo systemd || echo nohup/start.sh)"
  if svc_active || [ -n "$pids" ]; then
    echo -e "服务状态 : ${C_G}运行中${C_0}"
    [ -n "$pids" ] && echo "进程 PID : $pids"
  else
    echo -e "服务状态 : ${C_R}未运行${C_0}"
  fi
  if port_listening "$p"; then echo -e "端口监听 : ${C_G}${host}:${p} 已监听${C_0}"; else echo -e "端口监听 : ${C_R}${host}:${p} 未监听${C_0}"; fi
  tok="$(read_cfg token)"
  [ -n "$tok" ] && echo "访问令牌 : 已设置（${C_Y}面板需 ?token=...${C_0}）" || echo "访问令牌 : 未设置（建议配合反向代理 + 访问控制）"
}

do_logs() {
  if [ -f "$LOG_FILE" ]; then
    echo -e "${C_Y}===== 最近 40 行 run.log（Ctrl+C 退出）=====${C_0}"
    tail -n 40 -f "$LOG_FILE"
  else
    echo -e "${C_R}未找到日志文件 $LOG_FILE${C_0}"
  fi
}

panel_url() {
  local p="$(read_cfg port)" host="$(read_cfg host)" tok ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  ip="${ip:-<服务器IP>}"
  echo "本地访问 : http://${host}:${p}/"
  if [ "$host" = "127.0.0.1" ] || [ "$host" = "0.0.0.0" ]; then
    echo "外部访问 : http://${ip}:${p}/  （监听 127.0.0.1 时需经反向代理/Nginx 暴露）"
  else
    echo "外部访问 : http://${host}:${p}/"
  fi
  local t="$(read_cfg token)"; [ -n "$t" ] && echo "带令牌  : http://${host}:${p}/?token=${t}"
  echo "嵌入代码 : <script src=\"http://${ip}:${p}/tracker.js\" data-site=\"你的域名\" defer></script>"
}

install_svc() {
  if [ "$(id -u)" -ne 0 ]; then echo -e "${C_R}安装系统服务需要 root 权限。${C_0}"; return; fi
  if [ ! -f "$SVC_FILE_LOCAL" ]; then echo -e "${C_R}未找到 $SVC_FILE_LOCAL，无法安装。${C_0}"; return; fi
  cp "$SVC_FILE_LOCAL" "$SVC_FILE_SYS"
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl start "$SERVICE_NAME"
  echo -e "${C_G}已安装并启动系统服务（开机自启）。${C_0}"
}

uninstall_svc() {
  if [ "$(id -u)" -ne 0 ]; then echo -e "${C_R}卸载系统服务需要 root 权限。${C_0}"; return; fi
  if ! is_systemd; then echo -e "${C_Y}未安装系统服务，无需卸载。${C_0}"; return; fi
  systemctl stop "$SERVICE_NAME" 2>/dev/null
  systemctl disable "$SERVICE_NAME" 2>/dev/null
  rm -f "$SVC_FILE_SYS"
  systemctl daemon-reload
  echo -e "${C_G}已卸载系统服务。${C_0}"
}

update_geoip() {
  if [ -f update_geoip.sh ]; then bash update_geoip.sh; else echo -e "${C_R}未找到 update_geoip.sh。${C_0}"; fi
}

backup_data() {
  local ts; ts="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "${INSTALL_DIR}/backups"
  local ok=0
  for f in events.db data/events.db events.sqlite; do
    if [ -f "$f" ]; then cp -p "$f" "${INSTALL_DIR}/backups/events-${ts}.db" && ok=1 && echo "已备份 $f -> backups/events-${ts}.db"; fi
  done
  [ "$ok" -eq 0 ] && echo -e "${C_Y}未找到事件数据库（可能尚未产生数据）。${C_0}"
}

cleanup_data() {
  echo -e "${C_Y}将按「数据保留期」删除过期原始事件（不可恢复）。${C_0}"
  read -r -p "确认执行？(y/N): " ans
  case "$ans" in
    y|Y)
      if [ -n "$PY" ]; then
        local deleted; deleted=$("$PY" - "$INSTALL_DIR" "$DATA_DIR" <<'PY'
import sys, importlib.util
base, data_dir = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("sa_app", base + "/app.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.StatEngine(data_dir=data_dir).cleanup_old_events() or 0)
PY
)
        echo -e "${C_G}已删除 ${deleted} 条过期事件。${C_0}"
      else
        echo -e "${C_R}未找到 python3，无法执行清理。${C_0}"
      fi
      ;;
    *) echo "已取消。";;
  esac
}

edit_cfg() {
  # $1 = port|host|token
  local key="$1" label cur nv
  case "$key" in
    port) label="端口";;
    host) label="监听地址(127.0.0.1 或 0.0.0.0 或具体IP)";;
    token) label="访问令牌(留空=不鉴权)";;
  esac
  cur="$(read_cfg "$key")"
  read -r -p "当前${label}: ${cur}  ->  输入新值: " nv
  [ -z "$nv" ] && { echo "未输入，取消。"; return; }
  if [ "$key" = "port" ] && ! echo "$nv" | grep -qE '^[0-9]+$'; then echo -e "${C_R}端口必须是数字。${C_0}"; return; fi
  write_cfg "$key" "$nv"
  echo -e "${C_Y}提示：修改后请选「重启服务」使其生效；若已安装 systemd，重启会从服务文件读取新参数。${C_0}"
}

do_about() {
  echo "site_analytics 服务管理控制台"
  echo "控制台版本 : $CONSOLE_VER"
  echo "安装目录 : $INSTALL_DIR"
  echo "默认端口 : $(read_cfg port)   监听 : $(read_cfg host)"
  # 应用版本：从 app.py 的 VERSION = "x.y.z" 读取
  local v=""
  if [ -f app.py ]; then
    v=$(grep -oE "VERSION\s*=\s*['\"][^'\"]+['\"]" app.py | head -1 | sed -E "s/^[^'\"]*['\"]//; s/['\"]$//")
  fi
  if [ -n "$v" ]; then
    echo "应用版本 : $v"
  else
    echo "应用版本 : 未设置（app.py 无 VERSION 常量）"
  fi
  echo "运行用户 : $(id -un 2>/dev/null || echo '?')   Python : ${PY:-未找到}"
}

# ============================================================================
#  菜单
# ============================================================================
show_menu() {
  echo
  echo -e "${C_B}=========== site_analytics 服务管理控制台 ===========${C_0}"
  echo " 1: 启动服务"
  echo " 2: 停止服务"
  echo " 3: 重启服务"
  echo " 4: 查看运行状态"
  echo " 5: 查看运行日志"
  echo " 6: 修改端口"
  echo " 7: 修改访问令牌"
  echo " 8: 修改监听地址"
  echo " 9: 获取面板地址"
  echo "10: 安装为系统服务 (systemd)"
  echo "11: 卸载系统服务"
  echo "12: 更新 GeoIP 数据库"
  echo "13: 备份数据"
  echo "14: 清理过期数据（按保留期）"
  echo "15: 关于 / 版本"
  echo " 0: 退出"
  echo -e "${C_B}======================================================${C_0}"
}

run_loop() {
  local choice
  while true; do
    show_menu
    read -r -p "请输入操作编号 (0-15): " choice
    case "$choice" in
      1) do_start;;
      2) do_stop;;
      3) do_restart;;
      4) do_status;;
      5) do_logs;;
      6) edit_cfg port;;
      7) edit_cfg token;;
      8) edit_cfg host;;
      9) panel_url;;
      10) install_svc;;
      11) uninstall_svc;;
      12) update_geoip;;
      13) backup_data;;
      14) cleanup_data;;
      15) do_about;;
      0|q|Q) echo "再见。"; exit 0;;
      *) echo -e "${C_R}无效选项：$choice${C_0}";;
    esac
  done
}

# 支持「无参数」交互，或「单参数直接执行」便于脚本调用：
#   bash sa-console.sh status | start | stop | restart | url
case "${1:-}" in
  ""|menu) run_loop;;
  start)  do_start;;
  stop)   do_stop;;
  restart) do_restart;;
  status) do_status;;
  url)    panel_url;;
  logs)   do_logs;;
  *) echo "未知命令: $1（支持: start|stop|restart|status|url|logs）"; exit 1;;
esac
