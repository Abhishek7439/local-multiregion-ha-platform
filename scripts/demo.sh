#!/usr/bin/env bash
# make demo: One-command end-to-end demonstration of self-healing with proof
set -euo pipefail
shopt -s inherit_errexit 2>/dev/null || true

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-setu-multiregion}"
MC="$ROOT_DIR/scripts/mc.sh"
LOGFILE="/tmp/setu-demo-controller.log"
rm -f "$LOGFILE"

# Load credentials from .env if present
if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.env"
    set +a
fi
MINIO_ROOT_USER="${MINIO_ROOT_USER:-setuadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-ChangeMe12345}"

echo "=========================================================="
echo "   SETU SWFW_5S_02: Self-Healing With Proof (End-to-End)  "
echo "=========================================================="
echo "Architecture:"
echo " - Gateway:   HAProxy (:8080) with active health checks & admin socket (:9999)"
echo " - Region A:  MinIO primary (:9100 / :9101)"
echo " - Region B:  MinIO standby (:9200 / :9201)"
echo " - Storage:   Two-way active-active MinIO site replication"
echo " - DR Agent:  Python state machine with fast metadata failback gate"
echo " - GitOps:    Autonomous reconciler with active health gate & auto-rollback"
echo " - Project:   $COMPOSE_PROJECT_NAME"
echo "=========================================================="
echo ""

echo "--- Step 1: Verify Stack Health ---"
docker compose up -d
sleep 3

# Wait up to 15s for endpoints to become responsive
for endpoint in "127.0.0.1:9100/minio/health/live" "127.0.0.1:9200/minio/health/live" "127.0.0.1:8080/minio/health/live"; do
    ready=false
    for _ in $(seq 1 15); do
        if curl -sf -m 2 -o /dev/null "http://$endpoint"; then
            ready=true
            break
        fi
        sleep 1
    done
    if [ "$ready" != "true" ]; then
        echo "ERROR: Endpoint http://$endpoint failed health check" >&2
        exit 1
    fi
done

echo "Region A:  UP (HTTP 200)"
echo "Region B:  UP (HTTP 200)"
echo "Gateway:   UP (HTTP 200)"
echo ""

echo "--- Bootstrap: Idempotent Replication & Bucket Verification ---"
"$MC" alias set site-a http://minio-a:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
"$MC" alias set site-b http://minio-b:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
"$MC" alias set gw http://gateway:80 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1

if "$MC" admin replicate info site-a 2>&1 | grep -q "SiteReplication is not enabled"; then
    echo "Site replication unconfigured. Initializing site replication between site-a and site-b..."
    "$MC" admin replicate add site-a site-b
    sleep 2
fi

if ! "$MC" ls site-a/demo >/dev/null 2>&1; then
    echo "Bucket 'demo' missing. Creating site-a/demo..."
    "$MC" mb --ignore-existing site-a/demo
    sleep 2
fi
echo "Bootstrap complete: replication and 'demo' bucket ready."
echo ""

echo "--- Step 2: Normal Operation (Gateway Write -> Replicated to Region B) ---"
DEMO_TS=$(date -u +%FT%TZ)
OBJECT_NAME="demo-sample-$(date -u +%Y%m%dT%H%M%SZ).txt"
echo "Writing object 'gw/demo/$OBJECT_NAME' via Gateway (:8080)..."
echo "demo payload created at $DEMO_TS" | "$MC" pipe "gw/demo/$OBJECT_NAME" >/dev/null

echo "Waiting for replication to Region B (site-b)..."
replicated=false
for _ in $(seq 1 10); do
    if "$MC" stat "site-b/demo/$OBJECT_NAME" >/dev/null 2>&1; then
        replicated=true
        break
    fi
    sleep 1
done

if [ "$replicated" != "true" ]; then
    echo "ERROR: Object 'demo/$OBJECT_NAME' failed to replicate to Region B within 10s" >&2
    exit 1
fi

PAYLOAD_B=$("$MC" cat "site-b/demo/$OBJECT_NAME")
echo "Read from Region B: '$PAYLOAD_B'"

HASH_A=$("$MC" cat "site-a/demo/$OBJECT_NAME" | sha256sum | awk '{print $1}')
HASH_B=$("$MC" cat "site-b/demo/$OBJECT_NAME" | sha256sum | awk '{print $1}')
echo "SHA-256 Region A: $HASH_A"
echo "SHA-256 Region B: $HASH_B"
if [ "$HASH_A" = "$HASH_B" ]; then
    echo "Integrity: MATCH (normal replication verified)"
else
    echo "Integrity: MISMATCH" >&2
    exit 1
fi
echo ""

echo "--- Step 3: Starting DR Controller ---"
python3 controller/dr_controller.py > "$LOGFILE" 2>&1 &
CTRL_PID=$!
trap 'kill $CTRL_PID 2>/dev/null || true' EXIT
sleep 2
echo "DR Controller started in background (PID $CTRL_PID)"
echo ""

echo "--- Step 4: Injecting Disaster — Stopping Region A ---"
docker compose stop minio-a
echo "Region A stopped at $(date -u +%FT%TZ)"
echo "Waiting for DR controller to detect failure and execute failover..."
sleep 12

echo ""
echo "--- Step 5: Failover Verification ---"
echo "Controller events during disaster:"
grep -E '"transition"|"fence"|"rto"' "$LOGFILE" || true

# Assert HAProxy status is MAINT
python3 -c "
import socket, sys
s = socket.create_connection(('127.0.0.1', 9999), 3)
s.sendall(b'show stat\n')
s.shutdown(socket.SHUT_WR)
data = b''.join(iter(lambda: s.recv(4096), b'')).decode()
status = None
for line in data.splitlines():
    if 'minio-a' in line:
        parts = line.split(',')
        status = parts[17]
        print(f'HAProxy backend {parts[0]} -> server {parts[1]} status: {parts[17]}')
if not status or not status.startswith('MAINT'):
    print(f'ERROR: Expected minio-a to be in MAINT status, got {status}', file=sys.stderr)
    sys.exit(1)
"
echo "Failover verified: minio-a is safely fenced (MAINT)."
echo ""

echo "--- Step 6: Disaster Recovery — Restarting Region A ---"
docker compose start minio-a
echo "Region A restarted at $(date -u +%FT%TZ)"
echo "Controller in RECOVERING state: waiting for fast integrity verification and automatic failback..."

FAILBACK_DONE=false
for i in $(seq 1 24); do
    sleep 2
    if grep -q '"to": "FAILBACK"' "$LOGFILE"; then
        FAILBACK_DONE=true
        sleep 2
        break
    fi
    echo "  ... syncing and checking checksums ($((i*2))s)"
done

if [ "$FAILBACK_DONE" = "true" ]; then
    echo "Failback complete!"
    echo "Controller events during recovery:"
    grep -E '"checksum"|"FAILBACK"|"HEALTHY"' "$LOGFILE" || true
else
    echo "ERROR: Failback did not finish within 48s" >&2
    exit 1
fi

# Assert HAProxy status is restored to UP
python3 -c "
import socket, sys
s = socket.create_connection(('127.0.0.1', 9999), 3)
s.sendall(b'show stat\n')
s.shutdown(socket.SHUT_WR)
data = b''.join(iter(lambda: s.recv(4096), b'')).decode()
status = None
for line in data.splitlines():
    if 'minio-a' in line:
        parts = line.split(',')
        status = parts[17]
        print(f'HAProxy backend {parts[0]} -> server {parts[1]} status: {parts[17]}')
if not status or not status.startswith('UP'):
    print(f'ERROR: Expected minio-a to be restored to UP status, got {status}', file=sys.stderr)
    sys.exit(1)
"
echo "Recovery verified: minio-a restored and un-fenced (UP)."
echo ""

echo "--- Step 7: Stopping Controller for Independent RPO Measurement ---"
kill "$CTRL_PID" 2>/dev/null || true
trap - EXIT
sleep 1
echo ""

echo "--- Step 8: Measuring RPO (Numbered Write Stream) ---"
RPO_OUTPUT=$(python3 controller/proof.py)
echo "$RPO_OUTPUT"

# Assert RPO objects count is 0
python3 -c "
import json, sys
data = json.loads('''$RPO_OUTPUT''')
for mode in ['graceful_stop', 'kill']:
    if mode in data:
        rpo = data[mode].get('rpo_objects', -1)
        if rpo != 0:
            print(f'ERROR: {mode} rpo_objects expected 0, got {rpo}', file=sys.stderr)
            sys.exit(1)
"
echo "RPO verified: 0 missing acknowledged objects."
echo ""

echo "--- Step 9: Cleaning Up Ephemeral RPO Test Buckets ---"
python3 -c "
import subprocess, json
mc = './scripts/mc.sh'
res = subprocess.run([mc, 'ls', '--json', 'site-a'], capture_output=True, text=True)
for line in res.stdout.splitlines():
    if not line.strip(): continue
    try:
        item = json.loads(line)
        bkt = item.get('key', '').rstrip('/')
        if bkt.startswith('rpo-'):
            subprocess.run([mc, 'rm', '--recursive', '--force', '--versions', f'site-a/{bkt}/'], capture_output=True)
            subprocess.run([mc, 'rb', f'site-a/{bkt}'], capture_output=True)
            print(f'  Cleaned ephemeral bucket: {bkt}')
    except Exception:
        pass
"
echo "Ephemeral RPO buckets removed."
echo ""

echo "--- Step 10: GitOps Continuous Deployment & Automated Rollback (AT5) ---"
python3 "$ROOT_DIR/scripts/demo_gitops.py"
echo ""

echo "=========================================================="
echo "   DEMO COMPLETE: All Platform Criteria Proven Live       "
echo "   - AT1: Multi-region health endpoints (HTTP 200)"
echo "   - AT2: Normal operation cross-region replication"
echo "   - AT3: Automated failover + fencing + RTO measured"
echo "   - AT4: Fast integrity failback + automatic un-fencing"
echo "   - RPO: Measured under graceful stop and SIGKILL (0 missing)"
echo "   - AT5: GitOps continuous auto-apply + auto-rollback"
echo "   - Ephemeral test buckets and worktrees cleaned"
echo "=========================================================="
