#!/usr/bin/env python3
"""Standalone GitOps Self-Healing & Auto-Rollback Demo (M4 AT5).

Demonstrates:
1. Pushing a valid configuration change -> automatically DEPLOYED.
2. Pushing a broken configuration (invalid haproxy port) -> active health gate
   detects failure and triggers automatic ROLLBACK to last known good commit.
3. Completely self-contained: creates and cleans up its own temp remote and worktree.
"""

import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE_REPO = Path("/home/cloud_automator/setu-starter")
BARE_REMOTE = Path("/tmp/setu-demo-remote.git")
WORKTREE_DIR = Path("/tmp/setu-demo-wt")
STAGE_DIR = Path("/tmp/setu-demo-staging")
STATE_FILE = WORKTREE_DIR / ".gitops_state.json"
MC = BASE_REPO / "scripts" / "mc.sh"


def run(cmd, cwd=None, check=True):
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command {' '.join(cmd)} failed (code {res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
    return res


def check_haproxy_minio_a():
    try:
        with socket.create_connection(("127.0.0.1", 9999), timeout=3) as sock:
            sock.sendall(b"show stat\n")
            sock.shutdown(socket.SHUT_WR)
            buf = b""
            while True:
                d = sock.recv(4096)
                if not d:
                    break
                buf += d
        for line in buf.decode(errors="replace").splitlines():
            if line.startswith("minio_api,minio-a,"):
                return line.split(",")[17]
    except Exception:
        return "UNKNOWN"
    return "UNKNOWN"


def wait_for_state(target_key, target_val, timeout=40):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    st = json.load(f)
                if target_key == "bad_commits" and target_val in st.get("bad_commits", []):
                    return st, time.monotonic() - start
                elif st.get(target_key) == target_val:
                    return st, time.monotonic() - start
            except Exception:
                pass
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for state {target_key} == {target_val}")


def main():
    print("==========================================================")
    print("   GitOps Self-Healing & Continuous Deployment (M4 AT5)   ")
    print("==========================================================")

    # 1. Cleanup old demo artifacts if any
    for d in (BARE_REMOTE, STAGE_DIR, WORKTREE_DIR):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    # Get local git identity dynamically
    author_name = run(["git", "config", "user.name"], cwd=BASE_REPO).stdout.strip() or "Abhishek7439"
    author_email = run(["git", "config", "user.email"], cwd=BASE_REPO).stdout.strip() or "cloud_automator@localhost"

    # 2. Initialize bare remote and staging clone
    print("Creating temporary bare remote and deployment worktree...")
    run(["git", "init", "--bare", str(BARE_REMOTE)])
    run(["git", "clone", str(BASE_REPO), str(STAGE_DIR)])
    run(["git", "config", "user.name", author_name], cwd=STAGE_DIR)
    run(["git", "config", "user.email", author_email], cwd=STAGE_DIR)
    run(["git", "checkout", "-b", "deploy"], cwd=STAGE_DIR)
    run(["git", "remote", "add", "deploy_bare", str(BARE_REMOTE)], cwd=STAGE_DIR)
    run(["git", "push", "-u", "deploy_bare", "deploy:deploy"], cwd=STAGE_DIR)

    # 3. Create deployment worktree
    run(["git", "clone", "--branch", "deploy", str(BARE_REMOTE), str(WORKTREE_DIR)])
    if (BASE_REPO / ".env").exists():
        shutil.copy(BASE_REPO / ".env", WORKTREE_DIR / ".env")

    # Initial state with both deployed and last_good populated
    base_commit = run(["git", "rev-parse", "HEAD"], cwd=STAGE_DIR).stdout.strip()
    with open(STATE_FILE, "w") as f:
        json.dump({"deployed": base_commit, "last_good": base_commit, "last_processed": base_commit, "bad_commits": []}, f)

    # 4. Start continuous reconciler in background
    reconciler_log = open("/tmp/gitops-demo-reconciler.log", "w")
    proc = subprocess.Popen(
        ["python3", str(WORKTREE_DIR / "gitops" / "reconciler.py"),
         "--worktree", str(WORKTREE_DIR),
         "--remote", str(BARE_REMOTE),
         "--branch", "deploy",
         "--interval", "2"],
        cwd=WORKTREE_DIR,
        stdout=reconciler_log,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    print(f"Reconciler polling daemon started (PID {proc.pid})")

    try:
        # Part A: Benign configuration change (T1)
        print("\n--- Phase A: Benign Configuration Change (Auto-Apply) ---")
        monitor_file = STAGE_DIR / "docker-compose.yml"
        compose_text = monitor_file.read_text()
        # Change monitor sleep 5 to sleep 4
        new_text = compose_text.replace("sleep 5", "sleep 4")
        monitor_file.write_text(new_text)
        run(["git", "add", "docker-compose.yml"], cwd=STAGE_DIR)
        run(["git", "commit", "-m", "Demo: update monitor sleep to 4s"], cwd=STAGE_DIR)
        t1_commit = run(["git", "rev-parse", "HEAD"], cwd=STAGE_DIR).stdout.strip()
        run(["git", "push", "deploy_bare", "deploy:deploy"], cwd=STAGE_DIR)
        print(f"Pushed valid commit {t1_commit[:7]}; waiting for reconciler to deploy...")

        st, elapsed_t1 = wait_for_state("deployed", t1_commit, timeout=40)
        print(f"PASS: Commit {t1_commit[:7]} deployed successfully in {elapsed_t1:.1f}s")

        # Part B: Broken configuration change & rollback (T3)
        print("\n--- Phase B: Broken Gateway Configuration (Auto-Rollback) ---")
        haproxy_cfg = STAGE_DIR / "gateway" / "haproxy.cfg"
        orig_cfg = haproxy_cfg.read_text()
        broken_cfg = orig_cfg + "\n    server broken_backend 127.0.0.1:99999 check\n"
        haproxy_cfg.write_text(broken_cfg)
        run(["git", "add", "gateway/haproxy.cfg"], cwd=STAGE_DIR)
        run(["git", "commit", "-m", "Demo: inject broken haproxy configuration"], cwd=STAGE_DIR)
        t3_commit = run(["git", "rev-parse", "HEAD"], cwd=STAGE_DIR).stdout.strip()
        run(["git", "push", "deploy_bare", "deploy:deploy"], cwd=STAGE_DIR)
        print(f"Pushed bad commit {t3_commit[:7]}; waiting for health gate failure and rollback...")

        st, elapsed_t3 = wait_for_state("bad_commits", t3_commit, timeout=60)
        print(f"PASS: Bad commit {t3_commit[:7]} rolled back in {elapsed_t3:.1f}s")
        print(f"      Active deployed commit restored to: {st['deployed'][:7]}")
        assert st["deployed"] == t1_commit

        # Allow rise-2 health check to transition from UP 1/2 to UP
        time.sleep(2)
        stat = check_haproxy_minio_a()
        print(f"HAProxy minio-a status after rollback: {stat}")
        assert stat == "UP", f"Expected UP, got {stat}"
        print("PASS: Gateway restored and healthy.")

    finally:
        # Stop reconciler daemon
        if proc and proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
            print("Reconciler daemon stopped.")

        # Re-apply gateway from BASE_REPO to ensure Docker container bind mount points back to base repo
        run(["docker", "compose", "up", "-d", "--no-deps", "gateway"], cwd=BASE_REPO)

        # Cleanup temporary directories
        print("Cleaning up temporary bare remote and worktrees...")
        shutil.rmtree(BARE_REMOTE, ignore_errors=True)
        shutil.rmtree(STAGE_DIR, ignore_errors=True)
        shutil.rmtree(WORKTREE_DIR, ignore_errors=True)
        print("Cleanup complete. No temporary worktrees or remotes left behind.")

    print("\n==========================================================")
    print(f"   GITOPS DEMO COMPLETE: AT5 Proven Live")
    print(f"   - Valid change: deployed in {elapsed_t1:.1f}s")
    print(f"   - Bad change: rolled back in {elapsed_t3:.1f}s")
    print(f"   - Working directory clean; temporary remotes cleaned")
    print("==========================================================")


if __name__ == '__main__':
    main()
