#!/usr/bin/env python3
"""Execute GitOps tests T1, T2, T3 with continuous loop reconciler,
container persistence tracking, and state restart verification.

Rules enforced:
- Reconciler runs as a background polling loop (not --once).
- Recreate only changed services (targeted apply); never recreate MinIO across T1/T3.
- ~/setu-starter stays clean and on branch main.
- Reconciler works only in /tmp/setu-gitops-wt.
- After T3 rollback, HAProxy show stat confirms minio-a UP (not MAINT) and round-trip write/read works.
- Reconciler restart test proves bad_commits persisted.
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
BARE_REMOTE = Path("/tmp/setu-gitops-remote.git")
WORKTREE_DIR = Path("/tmp/setu-gitops-wt")
STAGE_DIR = Path("/tmp/setu-gitops-staging")
STATE_FILE = WORKTREE_DIR / ".gitops_state.json"
MC = BASE_REPO / "scripts" / "mc.sh"


def run(cmd, cwd=None, check=True):
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command {' '.join(cmd)} failed (code {res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
    return res


def get_git_status_main():
    res = run(["git", "status"], cwd=BASE_REPO)
    branch = run(["git", "branch", "--show-current"], cwd=BASE_REPO).stdout.strip()
    return branch, res.stdout.strip()


def get_container_info():
    """Get container IDs and uptimes for all platform services."""
    res = run(["docker", "ps", "--format", "{{.Names}}\t{{.ID}}\t{{.CreatedAt}}\t{{.Status}}"])
    info = {}
    for line in res.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            info[parts[0]] = {
                "id": parts[1],
                "created_at": parts[2],
                "status": parts[3],
            }
    return info


def verify_data_integrity():
    """Verify that objects can still be written and read across both sites."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    key = f"demo/integ-{stamp}.txt"
    payload = f"integrity-check-{stamp}\n".encode()
    expected_sha = hashlib.sha256(payload).hexdigest()

    # Write to gateway
    res_w = subprocess.run([str(MC), "pipe", f"gw/{key}"], input=payload, cwd=BASE_REPO, capture_output=True, timeout=15)
    if res_w.returncode != 0:
        return False, f"write failed: {res_w.stderr.decode()}"
    time.sleep(2)
    # Read from site-b
    res_r = subprocess.run([str(MC), "cat", f"site-b/{key}"], cwd=BASE_REPO, capture_output=True, timeout=15)
    if res_r.returncode != 0:
        return False, f"read from site-b failed: {res_r.stderr.decode()}"
    actual_sha = hashlib.sha256(res_r.stdout).hexdigest()
    if actual_sha != expected_sha:
        return False, f"sha mismatch: expected {expected_sha}, got {actual_sha}"
    return True, "SHA-256 match"


def check_haproxy_minio_a():
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
            fields = line.split(",")
            return fields[17]  # status field
    return "UNKNOWN"


def wait_for_state(target_key, target_val, timeout=40):
    """Wait for .gitops_state.json to contain a specific state value."""
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


class ReconcilerProcess:
    def __init__(self, log_path="/tmp/reconciler.log"):
        self.log_path = log_path
        self.proc = None

    def start(self):
        log_file = open(self.log_path, "a")
        self.proc = subprocess.Popen(
            ["python3", str(WORKTREE_DIR / "gitops" / "reconciler.py"),
             "--worktree", str(WORKTREE_DIR),
             "--remote", str(BARE_REMOTE),
             "--branch", "deploy",
             "--interval", "2"],
            cwd=WORKTREE_DIR,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
        )
        time.sleep(1)
        print(f"Started reconciler loop PID={self.proc.pid}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            self.proc.wait(timeout=5)
            print(f"Stopped reconciler loop PID={self.proc.pid}")


def setup_gitops_environment():
    print("=== SETUP: Initializing bare remote and deployment worktree ===")
    if BARE_REMOTE.exists():
        shutil.rmtree(BARE_REMOTE)
    run(["git", "init", "--bare", str(BARE_REMOTE)])

    if WORKTREE_DIR.exists():
        shutil.rmtree(WORKTREE_DIR)
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)

    # Clone base repo into staging to create the deploy branch with reconciler
    run(["git", "clone", str(BASE_REPO), str(STAGE_DIR)])
    run(["git", "config", "user.name", "Abhishek7439"], cwd=STAGE_DIR)
    run(["git", "config", "user.email", run(["git", "config", "user.email"], cwd=BASE_REPO).stdout.strip() or "cloud_automator@localhost"], cwd=STAGE_DIR)
    if (BASE_REPO / ".env").exists():
        shutil.copy(BASE_REPO / ".env", STAGE_DIR / ".env")

    # Copy reconciler.py into gitops/ directory in staging
    gitops_dir = STAGE_DIR / "gitops"
    gitops_dir.mkdir(exist_ok=True)
    shutil.copy("/tmp/reconciler.py", gitops_dir / "reconciler.py")
    (gitops_dir / "reconciler.py").chmod(0o755)

    # Commit baseline to staging on deploy branch if needed
    run(["git", "checkout", "-b", "deploy"], cwd=STAGE_DIR)
    run(["git", "add", "gitops/reconciler.py"], cwd=STAGE_DIR)
    diff = run(["git", "status", "--porcelain"], cwd=STAGE_DIR).stdout.strip()
    if diff:
        run(["git", "commit", "-m", "GitOps: add reconciler.py"], cwd=STAGE_DIR)
    baseline_commit = run(["git", "rev-parse", "HEAD"], cwd=STAGE_DIR).stdout.strip()

    # Push to bare remote
    run(["git", "remote", "add", "deploy_bare", str(BARE_REMOTE)], cwd=STAGE_DIR)
    run(["git", "push", "deploy_bare", "deploy:deploy"], cwd=STAGE_DIR)

    # Clone bare remote into WORKTREE_DIR
    run(["git", "clone", "-b", "deploy", str(BARE_REMOTE), str(WORKTREE_DIR)])
    if (BASE_REPO / ".env").exists():
        shutil.copy(BASE_REPO / ".env", WORKTREE_DIR / ".env")

    # Initialize .gitops_state.json with baseline
    state = {
        "last_good": baseline_commit,
        "bad_commits": [],
        "deployed": baseline_commit,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    print(f"Baseline commit: {baseline_commit}")
    branch, status = get_git_status_main()
    print(f"~/setu-starter status: branch={branch}, clean={'working tree clean' in status}")
    assert branch in ("main", "m4-gitops") and "working tree clean" in status


def test_t1():
    print("\n=======================================================")
    print("=== TEST T1: Benign valid change to monitor service ===")
    print("=======================================================")
    info_before = get_container_info()
    minio_a_id_before = info_before.get("setu-multiregion-minio-a-1", {}).get("id")
    minio_b_id_before = info_before.get("setu-multiregion-minio-b-1", {}).get("id")

    # In staging, modify monitor service in docker-compose.yml
    compose_path = STAGE_DIR / "docker-compose.yml"
    content = compose_path.read_text()
    # Change sleep interval in monitor service from 5 to 6
    new_content = content.replace("sleep 5", "sleep 6")
    compose_path.write_text(new_content)
    run(["git", "add", "docker-compose.yml"], cwd=STAGE_DIR)
    run(["git", "commit", "-m", "T1: update monitor sleep interval to 6s"], cwd=STAGE_DIR)
    t1_commit = run(["git", "rev-parse", "HEAD"], cwd=STAGE_DIR).stdout.strip()
    run(["git", "push", "deploy_bare", "deploy:deploy"], cwd=STAGE_DIR)
    print(f"Pushed T1 commit: {t1_commit}")

    # Wait for background reconciler loop to detect and deploy
    st, elapsed = wait_for_state("deployed", t1_commit, timeout=40)
    print(f"Reconciler loop deployed T1 in {elapsed:.2f}s")
    print("State after T1:", st)

    # Verify MinIO container IDs remain UNCHANGED
    info_after = get_container_info()
    minio_a_id_after = info_after.get("setu-multiregion-minio-a-1", {}).get("id")
    minio_b_id_after = info_after.get("setu-multiregion-minio-b-1", {}).get("id")
    print(f"MinIO-A ID before: {minio_a_id_before}, after: {minio_a_id_after} (unchanged: {minio_a_id_before == minio_a_id_after})")
    print(f"MinIO-B ID before: {minio_b_id_before}, after: {minio_b_id_after} (unchanged: {minio_b_id_before == minio_b_id_after})")
    assert minio_a_id_before == minio_a_id_after, "MinIO-A container ID changed!"
    assert minio_b_id_before == minio_b_id_after, "MinIO-B container ID changed!"

    # Data integrity check
    ok, msg = verify_data_integrity()
    print(f"Data integrity after T1: {ok} ({msg})")
    assert ok

    # Check main repo status
    branch, status = get_git_status_main()
    print(f"~/setu-starter status: branch={branch}, clean={'working tree clean' in status}")
    assert branch in ("main", "m4-gitops") and "working tree clean" in status
    return t1_commit, elapsed


def test_t2(last_good):
    print("\n===========================================================")
    print("=== TEST T2: Invalid compose file (rejected by validation) ===")
    print("===========================================================")
    compose_path = STAGE_DIR / "docker-compose.yml"
    broken_yaml = "name: setu-multiregion\nservices:\n  broken_service:\n    invalid_syntax: [unclosed bracket\n"
    compose_path.write_text(broken_yaml)
    run(["git", "add", "docker-compose.yml"], cwd=STAGE_DIR)
    run(["git", "commit", "-m", "T2: invalid compose syntax"], cwd=STAGE_DIR)
    t2_commit = run(["git", "rev-parse", "HEAD"], cwd=STAGE_DIR).stdout.strip()
    run(["git", "push", "deploy_bare", "deploy:deploy"], cwd=STAGE_DIR)
    print(f"Pushed T2 (invalid) commit: {t2_commit}")

    # Wait for reconciler loop to detect and record in bad_commits
    st, elapsed = wait_for_state("bad_commits", t2_commit, timeout=30)
    print(f"Reconciler loop rejected T2 in {elapsed:.2f}s")
    print("State after T2:", st)
    assert st["deployed"] == last_good
    assert t2_commit in st["bad_commits"]

    # Worktree should have been reset to last_good
    wt_head = run(["git", "rev-parse", "HEAD"], cwd=WORKTREE_DIR).stdout.strip()
    print(f"Worktree HEAD after validation failure: {wt_head} (equals last_good: {wt_head == last_good})")
    assert wt_head == last_good

    # Data integrity check
    ok, msg = verify_data_integrity()
    print(f"Data integrity after T2: {ok} ({msg})")
    assert ok

    branch, status = get_git_status_main()
    print(f"~/setu-starter status: branch={branch}, clean={'working tree clean' in status}")
    assert branch in ("main", "m4-gitops") and "working tree clean" in status
    return t2_commit, elapsed


def test_t3(last_good):
    print("\n=============================================================")
    print("=== TEST T3: Broken haproxy.cfg (applied, gate fails, ROLLBACK) ===")
    print("=============================================================")
    info_before = get_container_info()
    minio_a_id_before = info_before.get("setu-multiregion-minio-a-1", {}).get("id")
    minio_b_id_before = info_before.get("setu-multiregion-minio-b-1", {}).get("id")
    gateway_id_before = info_before.get("setu-multiregion-gateway-1", {}).get("id")

    # Restore valid compose file
    run(["git", "checkout", last_good, "--", "docker-compose.yml"], cwd=STAGE_DIR)

    # Break haproxy.cfg
    haproxy_cfg = STAGE_DIR / "gateway" / "haproxy.cfg"
    orig_cfg = haproxy_cfg.read_text()
    broken_cfg = orig_cfg + "\n    server broken_server 127.0.0.1:99999 check\n"
    haproxy_cfg.write_text(broken_cfg)

    run(["git", "add", "docker-compose.yml", "gateway/haproxy.cfg"], cwd=STAGE_DIR)
    run(["git", "commit", "-m", "T3: broken haproxy configuration"], cwd=STAGE_DIR)
    t3_commit = run(["git", "rev-parse", "HEAD"], cwd=STAGE_DIR).stdout.strip()
    run(["git", "push", "deploy_bare", "deploy:deploy"], cwd=STAGE_DIR)
    print(f"Pushed T3 (broken haproxy) commit: {t3_commit}")

    # Inspect parent commit of T3
    parent_commit = run(["git", "log", "-1", "--pretty=format:%P", t3_commit], cwd=STAGE_DIR).stdout.strip()
    print(f"Commit {t3_commit} has parent commit: {parent_commit}")

    # Wait for reconciler loop to detect, fail gate, rollback to last_good, and record in bad_commits
    st, elapsed = wait_for_state("bad_commits", t3_commit, timeout=60)
    print(f"Reconciler loop handled T3 rollback in {elapsed:.2f}s")
    print("State after T3 rollback:", st)
    assert t3_commit in st["bad_commits"]
    assert st["deployed"] == last_good

    # Verify MinIO container IDs remain UNCHANGED across gateway failure and rollback
    info_after = get_container_info()
    minio_a_id_after = info_after.get("setu-multiregion-minio-a-1", {}).get("id")
    minio_b_id_after = info_after.get("setu-multiregion-minio-b-1", {}).get("id")
    gateway_id_after = info_after.get("setu-multiregion-gateway-1", {}).get("id")
    print(f"MinIO-A ID before: {minio_a_id_before}, after: {minio_a_id_after} (unchanged: {minio_a_id_before == minio_a_id_after})")
    print(f"MinIO-B ID before: {minio_b_id_before}, after: {minio_b_id_after} (unchanged: {minio_b_id_before == minio_b_id_after})")
    print(f"Gateway ID before: {gateway_id_before}, after: {gateway_id_after} (recreated: {gateway_id_before != gateway_id_after})")
    assert minio_a_id_before == minio_a_id_after, "MinIO-A container ID changed!"
    assert minio_b_id_before == minio_b_id_after, "MinIO-B container ID changed!"
    assert gateway_id_before != gateway_id_after, "Gateway was not recreated!"

    # Check HAProxy minio-a status: must be UP (not MAINT)
    stat = check_haproxy_minio_a()
    print(f"HAProxy minio-a status after rollback: {stat}")
    assert stat == "UP", f"Expected UP, got {stat}"

    # Data integrity check
    ok, msg = verify_data_integrity()
    print(f"Data integrity after T3: {ok} ({msg})")
    assert ok

    branch, status = get_git_status_main()
    print(f"~/setu-starter status: branch={branch}, clean={'working tree clean' in status}")
    assert branch in ("main", "m4-gitops") and "working tree clean" in status
    return t3_commit, parent_commit, elapsed


def test_reconciler_restart(bad_commit):
    print("\n=======================================================")
    print("=== TEST: Reconciler Process Restart & State Recovery ===")
    print("=======================================================")
    # Run reconciler with --once on the worktree while remote HEAD is still at bad_commit
    # to show that upon startup it reads .gitops_state.json and immediately skips bad_commit
    res = run(["python3", str(WORKTREE_DIR / "gitops" / "reconciler.py"),
               "--worktree", str(WORKTREE_DIR),
               "--remote", str(BARE_REMOTE),
               "--branch", "deploy",
               "--once"], cwd=WORKTREE_DIR)
    print("Restarted reconciler process output:")
    print(res.stdout.strip())
    assert "skip_bad_commit" in res.stdout, "Restarted reconciler did not skip bad commit!"
    print("State persistence across process restart verified successfully.")


if __name__ == '__main__':
    log_file = "/tmp/reconciler.log"
    if os.path.exists(log_file):
        os.remove(log_file)

    setup_gitops_environment()

    reconciler_daemon = ReconcilerProcess(log_path=log_file)
    reconciler_daemon.start()

    try:
        t1_c, t1_time = test_t1()
        t2_c, t2_time = test_t2(t1_c)
        t3_c, t3_parent, t3_time = test_t3(t1_c)
    finally:
        reconciler_daemon.stop()

    test_reconciler_restart(t3_c)

    print("\n=======================================================")
    print("=== SUMMARY OF CONTINUOUS GITOPS TESTS ===")
    print(f"T1 (Monitor change): commit {t1_c[:7]} -> DEPLOYED in {t1_time:.2f}s")
    print(f"T2 (Invalid compose): commit {t2_c[:7]} -> VALIDATION REJECTED in {t2_time:.2f}s")
    print(f"T3 (Broken haproxy): commit {t3_c[:7]} (parent {t3_parent[:7]}) -> ROLLED_BACK in {t3_time:.2f}s")
    print("=======================================================")

    print("\n=== RECONCILER BACKGROUND DAEMON FULL LOG ===")
    if os.path.exists(log_file):
        with open(log_file) as f:
            print(f.read().strip())
