#!/usr/bin/env bash
# 本地真题备考工作台 —— 启动入口（Git Bash / WSL）
#   ./start.sh            # 默认 8787，起来后开浏览器
#   ./start.sh 9000       # 指定端口
#   ./start.sh --no-open  # 不开浏览器
set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1

PORT=8787
OPEN=1
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      echo "用法: ./start.sh [端口] [--no-open]"; exit 0;;
    --no-open) OPEN=0; shift;;
    -p) PORT="${2:-8787}"; shift 2;;
    *) PORT="$1"; shift;;
  esac
done

NODE="$(command -v node || true)"
[ -z "$NODE" ] && [ -x "/c/Users/Aron/.workbuddy/binaries/node/versions/24.22.0/node.exe" ] \
  && NODE="/c/Users/Aron/.workbuddy/binaries/node/versions/24.22.0/node.exe"
if [ -z "$NODE" ]; then
  echo "[错误] 找不到 node。先装 Node 18+，或改 start.sh 里的兜底路径。" >&2
  exit 1
fi

# 端口被占就往后找，8787-8799
port_free() {
  "$NODE" -e "const s=require('net').createServer();s.once('error',()=>process.exit(1));s.listen(Number(process.argv[1]),'127.0.0.1',()=>s.close(()=>process.exit(0)));" "$1" >/dev/null 2>&1
}
while ! port_free "$PORT"; do
  echo "端口 $PORT 已被占用，试下一个..."
  PORT=$((PORT + 1))
  if [ "$PORT" -gt 8799 ]; then echo "8787-8799 都被占用了，先关掉一个再启动。" >&2; exit 1; fi
done

echo
echo "  本地真题备考工作台"
echo "  地址  http://127.0.0.1:$PORT/"
echo "  node  $NODE"
echo "  停止  在这个窗口按 Ctrl+C"
echo

if [ "$OPEN" = "1" ]; then
  ( sleep 2; explorer.exe "http://127.0.0.1:$PORT/index.html" ) >/dev/null 2>&1 &
fi

exec "$NODE" server.mjs --port "$PORT"
