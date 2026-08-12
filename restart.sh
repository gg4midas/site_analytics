#!/usr/bin/env bash
# 站点流量统计（埋点版）重启脚本
# 用法：bash restart.sh  （可接与 start.sh 相同的 PORT / TOKEN 参数）
# 说明：先释放端口占用，再以 start.sh 重新拉起；保留原 run.log（不删除）。
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8899}"
# 透传命令行参数
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --port)  PORT="$2"; ARGS+=("--port" "$2"); shift 2 ;;
    --token) ARGS+=("--token" "$2"); shift 2 ;;
    *) shift ;;
  esac
done

echo "停止占用端口 $PORT 的进程..."
if command -v fuser >/dev/null 2>&1; then
  fuser -k ${PORT}/tcp 2>/dev/null || true
elif command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -t -i :$PORT 2>/dev/null || true)
  if [ -n "$PIDS" ]; then kill $PIDS 2>/dev/null || true; fi
fi

# 等待端口真正释放
for i in $(seq 1 10); do
  if command -v ss >/dev/null 2>&1; then
    if ! ss -ltn 2>/dev/null | grep -q "[:.]$PORT\b"; then break; fi
  fi
  sleep 1
done
echo "端口 $PORT 已释放，开始重新启动..."
bash "$(dirname "$0")/start.sh" "${ARGS[@]}"
