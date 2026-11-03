#!/usr/bin/env bash
# Core demo: write via gateway -> appears in Region B -> kill Region A -> still readable.
set -euo pipefail
cd "$(dirname "$0")/.."
MC=./scripts/mc.sh

echo "== 1. write through the gateway"
$MC mb --ignore-existing gw/demo
echo "hello from region A at $(date -u +%FT%TZ)" | $MC pipe gw/demo/hello.txt

echo "== 2. wait for replication, check Region B has it"
sleep 5
$MC ls site-b/demo

echo "== 3. DISASTER: stopping Region A"
docker compose stop minio-a
sleep 6

echo "== 4. read through the gateway (should be served by Region B)"
$MC cat gw/demo/hello.txt

echo "== 5. recover Region A"
docker compose start minio-a
echo "Done. Record the timings of steps 3-4 as your measured RTO."
