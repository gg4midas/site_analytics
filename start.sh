#!/usr/bin/env bash
# 站点流量统计（埋点版）启动脚本
# 用法：
#   bash start.sh                       # 默认端口 8899，无令牌
#   PORT=8899 TOKEN=你的令牌 bash start.sh
#   bash start.sh --port 8899 --token 你的令牌
# 说明：脚本会自动 cd 到自身所在目录，确保 app.py 及相对路径的
#       geoip/、data/ 能正确解析；以 nohup 后台方式运行，日志写入 run.log。
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8899}"
TOKEN="${TOKEN:-}"
GEOIP_DB="${GEOIP_DB:-geoip/GeoLite2-City.mmdb}"
ASN_DB="${ASN_DB:-geoip/GeoLite2-ASN.mmdb}"

# 透传命令行参数（--port / --token）
while [ $# -gt 0 ]; do
  case "$1" in
    --port)  PORT="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    *) echo "[忽略未知参数] $1" >&2; shift ;;
  esac
done

ARGS=(--host 127.0.0.1 --port "$PORT" --geoip-db "$GEOIP_DB" --asn-db "$ASN_DB")
if [ -n "$TOKEN" ]; then ARGS+=(--token "$TOKEN"); fi

# 端口占用预检（仅警告，不阻断；真正拦截由 app.py 完成）
if command -v ss >/dev/null 2>&1; then
  if ss -ltnp 2>/dev/null | grep -q "[:.]$PORT\b"; then
    echo "[警告] 端口 $PORT 已被占用，启动可能失败。当前占用情况：" >&2
    ss -ltnp 2>/dev/null | grep "[:.]$PORT\b" >&2
    echo "请先停止占用进程（kill <PID> 或 bash restart.sh）再启动。" >&2
  fi
elif command -v lsof >/dev/null 2>&1; then
  if lsof -i :$PORT >/dev/null 2>&1; then
    echo "[警告] 端口 $PORT 已被占用，启动可能失败。当前占用情况：" >&2
    lsof -i :$PORT >&2
    echo "请先停止占用进程再启动。" >&2
  fi
fi

echo "启动站点流量统计（埋点版）监听 127.0.0.1:$PORT（后台运行，日志 run.log）"
nohup python3 app.py "${ARGS[@]}" > run.log 2>&1 &
PID=$!
echo "已启动，PID=$PID"
