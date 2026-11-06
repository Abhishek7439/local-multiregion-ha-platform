#!/usr/bin/env bash
set -u
echo "whoami=$(whoami) home=$HOME"
ls -l /var/run/docker.sock /usr/bin/docker 2>&1 | head
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
/usr/bin/docker compose up -d gateway
sleep 2
echo "=== ps ==="
/usr/bin/docker compose ps
echo "=== gateway logs ==="
/usr/bin/docker compose logs --tail 40 gateway
echo "=== health ==="
curl -sf -m 3 -o /dev/null -w "a:%{http_code}\n" http://127.0.0.1:9100/minio/health/live || echo a-fail
curl -sf -m 3 -o /dev/null -w "b:%{http_code}\n" http://127.0.0.1:9200/minio/health/live || echo b-fail
curl -sf -m 3 -o /dev/null -w "gw:%{http_code}\n" http://127.0.0.1:8080/minio/health/live || echo gw-fail
echo "=== admin socket ==="
python3 - <<'PY'
import socket
s = socket.create_connection(("127.0.0.1", 9999), 3)
s.sendall(b"show info\n")
s.shutdown(socket.SHUT_WR)
print(s.recv(2000).decode(errors="replace"))
PY
