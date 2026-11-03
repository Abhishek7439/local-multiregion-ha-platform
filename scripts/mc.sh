#!/usr/bin/env bash
# Runs the MinIO client inside the compose network (no install needed).
set -euo pipefail
mkdir -p "$HOME/.setu-mc"
exec docker run --rm -i --user "$(id -u):$(id -g)" --network setu_global \
  -v "$HOME/.setu-mc:/mc-config" \
  cgr.dev/chainguard/minio-client@sha256:1dccd2a6fd59914a98ac2d9dad95e552c91243cb0bd7242aaa224802df4b3432 --config-dir /mc-config "$@"
