#!/usr/bin/env bash
# Standalone GitOps self-healing and auto-rollback demonstration
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT_DIR/scripts/demo_gitops.py"
