#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .env
./scripts/mc.sh alias set site-a http://minio-a:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
./scripts/mc.sh alias set site-b http://minio-b:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
./scripts/mc.sh alias set gw http://gateway:80 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
./scripts/mc.sh admin replicate add site-a site-b
./scripts/mc.sh admin replicate info site-a
