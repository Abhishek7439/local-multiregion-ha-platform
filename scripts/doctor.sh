#!/usr/bin/env bash
# make doctor: verify prerequisites for the multi-region data platform
set -u

echo "=========================================================="
echo "   SETU SWFW_5S_02 — System Environment Doctor"
echo "=========================================================="

FAILED=0
WARNED=0

check_cmd() {
    local name="$1"
    local cmd="$2"
    local required="$3"
    printf "Checking %-18s ... " "$name"
    if eval "$cmd" >/dev/null 2>&1; then
        echo "[ PASS ]"
    else
        if [ "$required" = "true" ]; then
            echo "[ FAIL ] (required)"
            FAILED=$((FAILED + 1))
        else
            echo "[ WARN ] (optional / fallback available)"
            WARNED=$((WARNED + 1))
        fi
    fi
}

# 1. Docker Engine
check_cmd "Docker CLI" "docker --version" "true"
check_cmd "Docker Daemon" "docker info" "true"
check_cmd "Compose v2" "docker compose version" "true"

# 2. Runtimes and utilities
check_cmd "Python 3" "python3 --version" "true"
check_cmd "Make" "make --version" "true"
check_cmd "Git" "git --version" "true"
check_cmd "Curl" "curl --version" "true"

# 3. Optional utilities
check_cmd "Socat (admin CLI)" "socat -V" "false"
check_cmd "Traffic Control (tc)" "tc -V" "false"

# 4. Memory check
printf "Checking %-18s ... " "System Memory"
if [ -f /proc/meminfo ]; then
    TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    TOTAL_MEM_MB=$((TOTAL_MEM_KB / 1024))
    if [ "$TOTAL_MEM_MB" -ge 3000 ]; then
        echo "[ PASS ] (${TOTAL_MEM_MB} MB available)"
    else
        echo "[ WARN ] (${TOTAL_MEM_MB} MB - minimum recommended is 4096 MB)"
        WARNED=$((WARNED + 1))
    fi
else
    echo "[ SKIP ] (/proc/meminfo not found)"
fi

echo "=========================================================="
if [ "$FAILED" -eq 0 ]; then
    echo "Doctor check PASSED (Failures: $FAILED, Warnings: $WARNED)"
    exit 0
else
    echo "Doctor check FAILED (Failures: $FAILED, Warnings: $WARNED)"
    echo "Please resolve required tools before running the platform."
    exit 1
fi
