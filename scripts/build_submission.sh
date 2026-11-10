#!/usr/bin/env bash
# scripts/build_submission.sh: Builds the verified SETU SWFW_5S_02 submission package.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PKG_NAME="SETU_SWFW_5S_02_Submission"
PKG_DIR="$REPO_ROOT/$PKG_NAME"
ZIP_FILE="$REPO_ROOT/${PKG_NAME}.zip"
PDF_SRC="$REPO_ROOT/report/SETU_SWFW_5S_02_Project_Report.pdf"
HTML_SRC="$REPO_ROOT/report/report.html"

echo "=========================================================="
echo "   Building Submission Package: $PKG_NAME"
echo "=========================================================="

# 1. Ensure fresh clean build directory
rm -rf "$PKG_DIR" "$ZIP_FILE"
mkdir -p "$PKG_DIR"

# 2. Verify or Generate Project Report PDF
if [[ ! -f "$PDF_SRC" ]]; then
    echo "Report PDF not found at $PDF_SRC."
    if [[ -f "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" && -f "$HTML_SRC" ]]; then
        echo "Compiling PDF from $HTML_SRC using Microsoft Edge headless..."
        "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
            --headless=new --disable-gpu --no-pdf-header-footer \
            --print-to-pdf="$(wslpath -w "$PDF_SRC")" \
            "$(wslpath -w "$HTML_SRC")" || true
    fi
fi

if [[ ! -f "$PDF_SRC" ]]; then
    echo "ERROR: Missing required project report PDF at $PDF_SRC" >&2
    exit 1
fi

echo "[1/5] Adding PDF report to package root..."
cp "$PDF_SRC" "$PKG_DIR/SETU_SWFW_5S_02_Project_Report.pdf"

# 3. Create README.txt
echo "[2/5] Creating README.txt manifest and operator quick-start..."
cat << 'EOF' > "$PKG_DIR/README.txt"
================================================================================
SETU SWFW_5S_02: FINAL SUBMISSION PACKAGE
Local Multi-Region Highly Available Data Platform with Automated Disaster Recovery,
Chaos Engineering, and GitOps
================================================================================
Student Name:       Abhishek Kothe (GitHub: @Abhishek7439)
College:            Yeshwantrao Chavan College of Engineering (YCCE), Nagpur
Department:         Department of Computer Technology
Course / Project:   SETU 2026-27 | Project SWFW_5S_02
Academic Term:      5th Semester
Tested Environment: Ubuntu 26.04.1 LTS on WSL2 (Windows 11 host, 16 GB RAM)
External Testing:   Clean-machine test on a separate machine: not yet tested on a separate machine
================================================================================

PACKAGE CONTENTS
----------------
1. SETU_SWFW_5S_02_Project_Report.pdf
   Comprehensive 16-page technical report covering architecture, DR state machine,
   GitOps workflows, runbook, empirical results (AT1-AT7, E1-E5), limitations, and
   troubleshooting. All metrics are cited from immutable evidence files.

2. README.txt
   This manifest and operator quick-start guide.

3. source/
   Full project source tree exported directly from git HEAD (zero git history,
   zero secrets, zero .env files, zero temporary worktrees or caches).
   Includes:
   - docker-compose.yml: Multi-region container definitions (HAProxy, MinIO A/B, Toxiproxy, monitor)
   - gateway/: Ingress configurations (HAProxy 3.4.7 with runtime admin socket)
   - controller/: Autonomous 5-state DR finite state machine and proof engine
   - gitops/: Autonomous continuous deployment reconciler with health gate and auto-rollback
   - chaos/: 5-scenario chaos engineering resilience framework (E1-E5)
   - scripts/: Doctor pre-flight script, MinIO client wrapper, and end-to-end demo
   - docs/: Architecture documentation, ADRs (D1-D12), runbook, reviewer Q&A, and test evidence

4. demo/
   Demonstration assets and execution evidence:
   - DEMO_SCRIPT.md: Complete narration guide, terminal actions, and recording checklist
   - demo-run.log: Real execution log of make demo concluding with exit code 0
   - README.md: Demonstration overview and review evaluation protocol
   (Demonstration Note: Live demonstration will be conducted in person during project evaluation)

5-LINE OPERATOR QUICK-START
---------------------------
1. cd source
2. make doctor        # Verifies Docker, Python 3, memory allocation (>4 GiB free), and tc CLI
3. make up            # Starts multi-region platform containers (minio-a, minio-b, gateway, toxiproxy)
4. make demo          # Executes 10-step automated self-healing & GitOps demo (~1m50s, exit code 0)
5. make audit         # Executes cryptographic SHA-256 deep audit across all 149 stored objects

TECHNICAL DEFENSE HIGHLIGHTS
----------------------------
- Sub-5-second failover: HAProxy active Layer-7 health checking redispatches in ~3.4s without dropping client writes.
- Administrative fencing: Controller locks primary into MAINT mode on HAProxy socket to prevent split-brain.
- Fast failback gate: Inventory metadata parity check matches 140+ objects in 1.2s (123x faster than sequential downloads).
- Autonomous self-healing GitOps: Pre-flight syntax validation and post-apply health gate triggers auto-rollback in 19s.
- Zero external packages: Pure Python standard library (urllib, socket, hashlib, hmac) with custom AWS SigV4 client.
- 100% Cryptographic Parity: Byte-for-byte SHA-256 payload audit proves zero bit rot across 149 objects on both sites.
================================================================================
EOF

# Placeholder check on README.txt
if grep -iE '(TODO|placeholder|\[SETU_|\[YOUR_|FIXME)' "$PKG_DIR/README.txt" >/dev/null; then
    echo "ERROR: Placeholder text found in README.txt!" >&2
    exit 1
fi

# 4. Export source/ via git archive
echo "[3/5] Exporting clean source tree via git archive..."
mkdir -p "$PKG_DIR/source"
git archive HEAD | tar -x -C "$PKG_DIR/source"

# 5. Populate demo/
echo "[4/5] Adding demo assets and execution logs..."
mkdir -p "$PKG_DIR/demo"
cp "$REPO_ROOT/demo/DEMO_SCRIPT.md" "$PKG_DIR/demo/"
cp "$REPO_ROOT/demo/demo-run.log" "$PKG_DIR/demo/"
cp "$REPO_ROOT/demo/README.md" "$PKG_DIR/demo/"

# Check optional demo_video.mp4
if [[ -f "$REPO_ROOT/demo/demo_video.mp4" ]]; then
    VIDEO_SIZE=$(stat -c%s "$REPO_ROOT/demo/demo_video.mp4")
    # 10 MB limit for video to keep total zip well under 15 MB
    if (( VIDEO_SIZE < 10485760 )); then
        echo "Including demo/demo_video.mp4 ($(numfmt --to=iec-i --suffix=B "$VIDEO_SIZE"))..."
        cp "$REPO_ROOT/demo/demo_video.mp4" "$PKG_DIR/demo/"
    else
        echo "Notice: demo/demo_video.mp4 is large ($VIDEO_SIZE bytes); skipping to keep zip < 15 MB."
    fi
fi

# 6. Safety & Security Audit on Package Contents
echo "[5/5] Auditing package for secrets and forbidden files..."

# Ensure .env is never packaged
FORBIDDEN_ENV=$(find "$PKG_DIR" -name ".env" -o -name ".env.local" -o -name ".env.production" || true)
if [[ -n "$FORBIDDEN_ENV" ]]; then
    echo "SECURITY ERROR: Forbidden environment files found in package: $FORBIDDEN_ENV" >&2
    exit 1
fi

# Ensure no git internals are packaged
FORBIDDEN_GIT=$(find "$PKG_DIR" -name ".git" -o -name ".gitops_state.json" || true)
if [[ -n "$FORBIDDEN_GIT" ]]; then
    echo "SECURITY ERROR: Git internals or runtime state found in package: $FORBIDDEN_GIT" >&2
    exit 1
fi

# Ensure no Python bytecode caches
find "$PKG_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PKG_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

# 7. Create ZIP Archive
echo "Compressing $PKG_DIR into $ZIP_FILE..."
python3 - << EOF
import os
import zipfile

pkg_dir = "$PKG_DIR"
zip_path = "$ZIP_FILE"

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(pkg_dir):
        # Sort for deterministic archive ordering
        dirs.sort()
        files.sort()
        for f in files:
            full_path = os.path.join(root, f)
            arcname = os.path.relpath(full_path, "$REPO_ROOT")
            z.write(full_path, arcname)

print("ZIP compression complete.")
EOF

# 8. Validate Archive Size
ZIP_SIZE_BYTES=$(stat -c%s "$ZIP_FILE")
ZIP_SIZE_MB=$(echo "scale=2; $ZIP_SIZE_BYTES / 1048576" | bc)
echo "Archive size: ${ZIP_SIZE_MB} MB ($ZIP_SIZE_BYTES bytes)"

if (( ZIP_SIZE_BYTES > 20971520 )); then
    echo "ERROR: Package size (${ZIP_SIZE_MB} MB) exceeds maximum allowed 20 MB!" >&2
    exit 1
fi

echo "=========================================================="
echo "   PACKAGE BUILD SUCCESS: $ZIP_FILE (${ZIP_SIZE_MB} MB)"
echo "=========================================================="
