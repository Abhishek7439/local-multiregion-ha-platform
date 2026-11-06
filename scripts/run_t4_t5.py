#!/usr/bin/env python3
"""Execute T4 (Drift Report-Only), T5 (DR Interaction), and Broken Gateway Test.

Verifies:
1. Broken gateway (socket unreachable) does not defer forever when storage is UP.
2. T4 drift: stop monitor out-of-band -> reported, not auto-healed per D9.
3. T5 DR interaction: minio-a stopped -> controller FAILOVER (fenced in MAINT)
   -> push valid change -> reconciler defers (no gate, no rollback, no recreate)
   -> start minio-a -> failback completes -> reconciler deploys change.
4. Interleaved controller and reconciler JSON logs by timestamp.
5. After each test: git status in ~/setu-starter, compare_sites, and HAProxy show stat.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
BARE_REMOTE = Path("/tmp/setu-gitops-remote.git")
WORKTREE_DIR = Path("/tmp/setu-gitops-wt")
STAGE_DIR = Path("/tmp/setu-gitops-staging")
STATE_FILE = WORKTREE_DIR / ".gitops_state.json"
MC = BASE_REPO / "scripts" / "mc.sh"
PROJECT = "setu-multiregion"


def run(cmd, cwd=None, check=True):
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command {' '.join(cmd)} failed (code {res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
    return res


def get_git_status():
    res = run(["git", "status"], cwd=BASE_REPO)
    branch = run(["git", "branch", "--show-current"], cwd=BASE_REPO).stdout.strip()
    return branch, "working tree clean" in res.stdout


def get_haproxy_stat():
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
        statuses = {}
        for line in buf.decode(errors="replace").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            fields = line.split(",")
            if len(fields) > 17 and fields[0] == "minio_api":
                statuses[fields[1]] = fields[17]
        return statuses
    except Exception as e:
        return {"error": str(e)}


def run_compare_sites():
    res = subprocess.run(
        ["python3", "-c", "from controller.proof import compare_sites; import json; print(json.dumps(compare_sites()))"],
        cwd=BASE_REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if res.returncode != 0:
        return {"match": False, "error": res.stderr}
    return json.loads(res.stdout.strip())


def print_checkpoints(test_name):
    branch, clean = get_git_status()
    hastat = get_haproxy_stat()
    cs = run_compare_sites()
    print(f"\n--- Checkpoints after {test_name} ---")
    print(f"Git status ~/setu-starter: branch={branch}, clean={clean}")
    print(f"HAProxy stat: {hastat}")
    print(f"compare_sites: match={cs.get('match')}, count_a={cs.get('count_a')}, count_b={cs.get('count_b')}")
    assert clean, f"~/setu-starter was dirtied after {test_name}!"
    assert cs.get("match") is True, f"compare_sites failed after {test_name}!"


def setup_environment():
    print("=== SETUP: Preparing gitops environment ===")
    if BARE_REMOTE.exists():
        shutil.rmtree(BARE_REMOTE)
    run(["git", "init", "--bare", str(BARE_REMOTE)])

    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)

    run(["git", "clone", str(BASE_REPO), str(STAGE_DIR)])
    run(["git", "config", "user.name", "Abhishek7439"], cwd=STAGE_DIR)
    run(["git", "config", "user.email", run(["git", "config", "user.email"], cwd=BASE_REPO, check=False).stdout.strip() or "cloud_automator@localhost"], cwd=STAGE_DIR)
    if (BASE_REPO / ".env").exists():
        shutil.copy(BASE_REPO / ".env", STAGE_DIR / ".env")

    # Checkout deploy branch in staging and push to bare remote
    run(["git", "checkout", "-b", "deploy"], cwd=STAGE_DIR)
    baseline_commit = run(["git", "rev-parse", "HEAD"], cwd=STAGE_DIR).stdout.strip()
    run(["git", "remote", "add", "deploy_bare", str(BARE_REMOTE)], cwd=STAGE_DIR)
    run(["git", "push", "deploy_bare", "deploy:deploy"], cwd=STAGE_DIR)

    if not WORKTREE_DIR.exists():
        run(["git", "clone", "-b", "deploy", str(BARE_REMOTE), str(WORKTREE_DIR)])
    else:
        run(["git", "remote", "set-url", "origin", str(BARE_REMOTE)], cwd=WORKTREE_DIR)
        run(["git", "fetch", "origin"], cwd=WORKTREE_DIR)
        run(["git", "checkout", "-f", "deploy"], cwd=WORKTREE_DIR)
        run(["git", "reset", "--hard", "origin/deploy"], cwd=WORKTREE_DIR)
        run(["git", "clean", "-fd"], cwd=WORKTREE_DIR)
    if (BASE_REPO / ".env").exists():
        shutil.copy(BASE_REPO / ".env", WORKTREE_DIR / ".env")

    state = {
        "last_good": baseline_commit,
        "bad_commits": [],
        "deployed": baseline_commit,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    print(f"Environment ready. Baseline: {baseline_commit}")
    return baseline_commit


def test_broken_gateway(baseline):
    print("\n=======================================================")
    print("=== TEST: Broken Gateway Unreachable Recovery ===")
    print("=======================================================")
    # 1. Stop gateway container out-of-band
    run(["docker", "compose", "-p", PROJECT, "stop", "gateway"], cwd=WORKTREE_DIR)
    stat = get_haproxy_stat()
    print(f"HAProxy stat after stopping gateway: {stat}")
    assert "error" in stat, "HAProxy socket should be unreachable!"

    # 2. Push a valid change (update monitor comment)
    compose_path = STAGE_DIR / "docker-compose.yml"
    txt = compose_path.read_text()
    compose_path.write_text(txt + "\n# gw recovery test\n")
    run(["git", "add", "docker-compose.yml"], cwd=STAGE_DIR)
    run(["git", "commit", "-m", "Test: push while gateway stopped"], cwd=STAGE_DIR)
    gw_commit = run(["git", "rev-parse", "HEAD"], cwd=STAGE_DIR).stdout.strip()
    run(["git", "push", "deploy_bare", "deploy:deploy"], cwd=STAGE_DIR)

    # 3. Run reconciler once
    res = run([
        "python3", str(WORKTREE_DIR / "gitops" / "reconciler.py"),
        "--worktree", str(WORKTREE_DIR),
        "--remote", str(BARE_REMOTE),
        "--branch", "deploy",
        "--once",
    ], cwd=WORKTREE_DIR)
    print("Reconciler output when gateway was unreachable:")
    print(res.stdout.strip())

    # Verify reconciler detected storage healthy and applied change, recovering gateway
    with open(STATE_FILE) as f:
        st = json.load(f)
    print("State after gateway recovery:", st)
    assert st["deployed"] == gw_commit, "Reconciler failed to deploy and restore gateway!"

    stat_after = get_haproxy_stat()
    print(f"HAProxy stat after reconciler applied commit: {stat_after}")
    assert stat_after.get("minio-a") == "UP" and stat_after.get("minio-b") == "UP"

    print_checkpoints("Broken Gateway Test")
    return gw_commit


def test_t4():
    print("\n=======================================================")
    print("=== TEST T4: Drift Detection (Report-Only) ===")
    print("=======================================================")
    # 1. Stop monitor container out-of-band
    run(["docker", "compose", "-p", PROJECT, "stop", "monitor"], cwd=WORKTREE_DIR)

    # 2. Run drift check via reconciler
    res = run([
        "python3", str(WORKTREE_DIR / "gitops" / "reconciler.py"),
        "--worktree", str(WORKTREE_DIR),
        "--remote", str(BARE_REMOTE),
        "--branch", "deploy",
        "--check-drift",
    ], cwd=WORKTREE_DIR)
    print("Reconciler drift check output:")
    print(res.stdout.strip())

    # 3. Verify monitor is still stopped (not auto-healed per D9)
    ps_res = run(["docker", "compose", "-p", PROJECT, "ps", "--services", "--filter", "status=running"], cwd=WORKTREE_DIR)
    running = ps_res.stdout.strip().splitlines()
    print(f"Running services after drift check: {running}")
    assert "monitor" not in running, "Monitor container was auto-healed! Policy must be report-only."
    assert "drift_detected" in res.stdout, "Drift was not reported!"

    # Restart monitor for next test
    run(["docker", "compose", "-p", PROJECT, "start", "monitor"], cwd=WORKTREE_DIR)
    time.sleep(2)

    print_checkpoints("T4 (Drift Detection)")


def test_t5(last_good):
    print("\n=======================================================")
    print("=== TEST T5: DR Interaction (Deferral & Post-Failback Deploy) ===")
    print("=======================================================")
    controller_log = Path("/tmp/controller_t5.log")
    reconciler_log = Path("/tmp/reconciler_t5.log")
    if controller_log.exists():
        controller_log.unlink()
    if reconciler_log.exists():
        reconciler_log.unlink()

    # 1. Start DR controller in background
    c_out = open(controller_log, "a")
    controller_proc = subprocess.Popen(
        ["python3", str(BASE_REPO / "controller" / "dr_controller.py")],
        cwd=BASE_REPO,
        stdout=c_out,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    time.sleep(2)
    print(f"DR Controller started PID={controller_proc.pid}")

    # 2. Start Reconciler loop in background
    r_out = open(reconciler_log, "a")
    reconciler_proc = subprocess.Popen(
        [
            "python3", str(WORKTREE_DIR / "gitops" / "reconciler.py"),
            "--worktree", str(WORKTREE_DIR),
            "--remote", str(BARE_REMOTE),
            "--branch", "deploy",
            "--interval", "2",
        ],
        cwd=WORKTREE_DIR,
        stdout=r_out,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    time.sleep(2)
    print(f"Reconciler loop started PID={reconciler_proc.pid}")

    try:
        # 3. Stop minio-a to trigger DR FAILOVER
        print("\nStopping minio-a to trigger DR FAILOVER...")
        run(["docker", "compose", "-p", PROJECT, "stop", "minio-a"], cwd=WORKTREE_DIR)

        # Wait for minio-a to be fenced in MAINT (grace window is 3s)
        fenced = False
        stat = {}
        for _ in range(15):
            time.sleep(1)
            stat = get_haproxy_stat()
            if "MAINT" in stat.get("minio-a", ""):
                fenced = True
                break
        print(f"HAProxy stat during FAILOVER: minio-a={stat.get('minio-a')}")
        assert fenced, f"minio-a was not fenced in MAINT! Got {stat.get('minio-a')}"

        # 4. Push a valid change while minio-a is down/fenced
        compose_path = STAGE_DIR / "docker-compose.yml"
        txt = compose_path.read_text()
        compose_path.write_text(txt + "\n# t5 valid change pushed during DR outage\n")
        run(["git", "add", "docker-compose.yml"], cwd=STAGE_DIR)
        run(["git", "commit", "-m", "T5: valid change pushed during DR outage"], cwd=STAGE_DIR)
        t5_commit = run(["git", "rev-parse", "HEAD"], cwd=STAGE_DIR).stdout.strip()
        run(["git", "push", "deploy_bare", "deploy:deploy"], cwd=STAGE_DIR)
        print(f"Pushed T5 commit {t5_commit} while minio-a is fenced in MAINT")

        # Give reconciler 6s (3 poll intervals) to observe and defer
        time.sleep(6)

        # Check reconciler log: must log 'deferred', state must NOT have deployed t5_commit
        with open(reconciler_log) as f:
            r_logs = f.read()
        print("Checking reconciler deferral...")
        assert '"event": "deferred"' in r_logs, "Reconciler did not defer during MAINT outage!"
        assert t5_commit not in r_logs or '"event": "deployed"' not in r_logs, "Reconciler deployed prematurely!"
        with open(STATE_FILE) as f:
            st = json.load(f)
        assert st["deployed"] == last_good, f"Reconciler applied commit during outage! State: {st}"
        print(f"CONFIRMED: Reconciler deferred commit {t5_commit[:7]} without applying or rolling back.")

        # 5. Start minio-a to trigger automatic recovery and failback
        print("\nStarting minio-a to trigger automatic recovery & failback...")
        run(["docker", "compose", "-p", PROJECT, "start", "minio-a"], cwd=WORKTREE_DIR)

        # Wait for controller failback to complete (two compare_sites passes take ~165s for 100+ objects)
        print("Waiting for controller recovery, checksum gate, and failback (up to 240s)...")
        failback_done = False
        for _ in range(120):
            time.sleep(2)
            with open(controller_log) as f:
                c_logs = f.read()
            if '"to": "HEALTHY"' in c_logs and '"from": "FAILBACK"' in c_logs:
                failback_done = True
                break

        assert failback_done, "Controller did not complete FAILBACK to HEALTHY within 240s!"
        stat_failback = get_haproxy_stat()
        print(f"HAProxy stat after failback: minio-a={stat_failback.get('minio-a')}")
        assert stat_failback.get("minio-a") == "UP"

        # 6. Now wait for reconciler loop to detect backends UP and deploy t5_commit
        print("Waiting for reconciler loop to deploy deferred commit...")
        deployed_done = False
        for _ in range(15):
            time.sleep(2)
            with open(STATE_FILE) as f:
                st = json.load(f)
            if st.get("deployed") == t5_commit:
                deployed_done = True
                break

        assert deployed_done, f"Reconciler did not deploy deferred commit after failback! State: {st}"
        print(f"CONFIRMED: Commit {t5_commit[:7]} successfully deployed after failback completed!")

    finally:
        if controller_proc and controller_proc.poll() is None:
            os.killpg(os.getpgid(controller_proc.pid), signal.SIGTERM)
            controller_proc.wait(timeout=5)
        if reconciler_proc and reconciler_proc.poll() is None:
            os.killpg(os.getpgid(reconciler_proc.pid), signal.SIGTERM)
            reconciler_proc.wait(timeout=5)

    # 7. Interleave logs by timestamp
    print("\n=======================================================")
    print("=== INTERLEAVED CONTROLLER & RECONCILER JSON LOGS ===")
    print("=======================================================")
    all_events = []
    if controller_log.exists():
        for line in controller_log.read_text().splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    obj = json.loads(line)
                    obj["_source"] = "CONTROLLER"
                    all_events.append(obj)
                except Exception:
                    pass

    if reconciler_log.exists():
        for line in reconciler_log.read_text().splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    obj = json.loads(line)
                    obj["_source"] = "RECONCILER"
                    all_events.append(obj)
                except Exception:
                    pass

    all_events.sort(key=lambda x: x.get("ts", ""))
    for ev in all_events:
        src = ev.pop("_source")
        print(f"[{src}] {json.dumps(ev)}")

    print_checkpoints("T5 (DR Interaction)")


if __name__ == '__main__':
    base = setup_environment()
    gw_commit = test_broken_gateway(base)
    test_t4()
    test_t5(gw_commit)

    print("\n=======================================================")
    print("=== ALL TESTS COMPLETED SUCCESSFULLY ===")
    print("=======================================================")
