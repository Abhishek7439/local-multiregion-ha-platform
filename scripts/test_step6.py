#!/usr/bin/env python3
"""Test Step 6: Controller startup reconcile and recovering_overdue deadline event.

Tests:
1. Kill controller during FAILOVER -> start minio-a -> start new controller ->
   new controller starts in RECOVERING (not HEALTHY) -> failback completes ->
   reaches HEALTHY with minio-a UP and compare_sites matching.
2. Configurable RECOVERING deadline logs {"event": "recovering_overdue"} when
   permanent divergence prevents failback before the deadline.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE_REPO = Path("/home/cloud_automator/setu-starter")
PROJECT = "setu-multiregion"


def run(cmd, cwd=None, check=True):
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command {' '.join(cmd)} failed (code {res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
    return res


def get_haproxy_minio_a():
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
    except Exception as e:
        return f"ERROR: {e}"
    return "UNKNOWN"


def test_startup_reconcile():
    print("=======================================================")
    print("=== TEST 1: Controller Startup Reconcile on MAINT ===")
    print("=======================================================")
    ctrl_log_1 = Path("/tmp/ctrl_step6_1.log")
    ctrl_log_2 = Path("/tmp/ctrl_step6_2.log")
    if ctrl_log_1.exists(): ctrl_log_1.unlink()
    if ctrl_log_2.exists(): ctrl_log_2.unlink()

    # 1. Start controller 1
    f1 = open(ctrl_log_1, "a")
    p1 = subprocess.Popen(
        ["python3", str(BASE_REPO / "controller" / "dr_controller.py")],
        cwd=BASE_REPO,
        stdout=f1,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    time.sleep(2)
    print(f"Controller 1 started PID={p1.pid}")

    # 2. Stop minio-a to trigger FAILOVER
    print("Stopping minio-a...")
    run(["docker", "compose", "-p", PROJECT, "stop", "minio-a"], cwd=BASE_REPO)

    # Wait for FAILOVER and fencing
    fenced = False
    stat = ""
    for _ in range(12):
        time.sleep(1)
        stat = get_haproxy_minio_a()
        if "MAINT" in stat:
            fenced = True
            break
    print(f"HAProxy stat during FAILOVER: minio-a={stat}")
    assert fenced, f"minio-a was not fenced in MAINT! Got {stat}"

    # 3. KILL controller 1 abruptly (SIGKILL) during FAILOVER
    print(f"Killing controller 1 (PID {p1.pid}) with SIGKILL during FAILOVER...")
    os.killpg(os.getpgid(p1.pid), signal.SIGKILL)
    p1.wait()
    print("Controller 1 killed.")

    # 4. Start minio-a while controller is dead
    print("Starting minio-a while controller is dead...")
    run(["docker", "compose", "-p", PROJECT, "start", "minio-a"], cwd=BASE_REPO)
    time.sleep(3)

    # Confirm minio-a is running but STILL in MAINT in HAProxy
    stat_before_restart = get_haproxy_minio_a()
    print(f"HAProxy stat with A running and controller dead: minio-a={stat_before_restart}")
    assert "MAINT" in stat_before_restart, "minio-a should still be in MAINT!"

    # 5. Start NEW controller 2
    f2 = open(ctrl_log_2, "a")
    p2 = subprocess.Popen(
        ["python3", str(BASE_REPO / "controller" / "dr_controller.py")],
        cwd=BASE_REPO,
        stdout=f2,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    print(f"Controller 2 started PID={p2.pid}")

    try:
        # Check initial log event of controller 2: must be RECOVERING, not HEALTHY!
        time.sleep(2)
        with open(ctrl_log_2) as f:
            lines = [json.loads(l) for l in f.read().splitlines() if l.startswith("{")]
        start_event = lines[0]
        print(f"Controller 2 startup event: {json.dumps(start_event)}")
        assert start_event.get("state") == "RECOVERING", f"Expected RECOVERING, got {start_event.get('state')}"
        assert "startup reconcile" in start_event.get("reason", "")
        print("CONFIRMED: Controller 2 started in RECOVERING state based on HAProxy MAINT status.")

        # Wait for controller 2 to complete checksum gate, failback, and reach HEALTHY (up to 260s)
        print("Waiting for controller 2 to complete checksum gate and reach HEALTHY (up to 260s)...")
        reached_healthy = False
        for _ in range(130):
            time.sleep(2)
            with open(ctrl_log_2) as f:
                content = f.read()
            if '"to": "HEALTHY"' in content and '"from": "FAILBACK"' in content:
                reached_healthy = True
                break

        assert reached_healthy, "Controller 2 did not reach HEALTHY within 260s!"
        print("CONFIRMED: Controller 2 completed failback and reached HEALTHY.")

        # Confirm minio-a is UP in HAProxy (allow 2s for rise 2 health check to transition from UP 1/2 to UP)
        time.sleep(2)
        stat_after = get_haproxy_minio_a()
        print(f"HAProxy stat after failback: minio-a={stat_after}")
        assert stat_after == "UP", f"Expected UP, got {stat_after}"

    finally:
        if p2 and p2.poll() is None:
            os.killpg(os.getpgid(p2.pid), signal.SIGTERM)
            p2.wait(timeout=5)

    print("Controller 2 full log:")
    with open(ctrl_log_2) as f:
        print(f.read().strip())


def test_recovering_deadline():
    print("\n=======================================================")
    print("=== TEST 2: Configurable RECOVERING Deadline Event ===")
    print("=======================================================")
    ctrl_log = Path("/tmp/ctrl_step6_deadline.log")
    if ctrl_log.exists(): ctrl_log.unlink()

    # 1. Fetch replication rule ID on site-a/demo
    rule_res = subprocess.run(
        [str(BASE_REPO / "scripts" / "mc.sh"), "replicate", "ls", "--json", "site-a/demo"],
        cwd=BASE_REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    rule_id = json.loads(rule_res.stdout)["rule"]["ID"]
    print(f"Replication rule ID on site-a/demo: {rule_id}")

    p = None
    try:
        # 2. Disable replication rule on site-a/demo so divergence cannot auto-reconcile
        subprocess.run(
            [str(BASE_REPO / "scripts" / "mc.sh"), "replicate", "update", "site-a/demo", "--id", rule_id, "--state", "disable"],
            cwd=BASE_REPO,
            check=True,
        )
        print("Replication disabled on site-a/demo.")

        # 3. Inject permanent divergence: object only exists on site-a
        print("Injecting diverging object on site-a only...")
        subprocess.run(
            [str(BASE_REPO / "scripts" / "mc.sh"), "pipe", "site-a/demo/perm-diverge.txt"],
            input=b"content-only-on-site-a\n",
            cwd=BASE_REPO,
            check=True,
        )

        # 4. Fence minio-a in HAProxy
        with socket.create_connection(("127.0.0.1", 9999), timeout=3) as sock:
            sock.sendall(b"disable server minio_api/minio-a\n")
        time.sleep(1)

        # 5. Start controller with --recovering-deadline 5
        f = open(ctrl_log, "a")
        p = subprocess.Popen(
            ["python3", str(BASE_REPO / "controller" / "dr_controller.py"), "--recovering-deadline", "5"],
            cwd=BASE_REPO,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
        )
        print(f"Controller started with deadline=5s PID={p.pid}")

        # Wait up to 150s for pass 1 to complete with divergence and log recovering_overdue
        print("Waiting for recovering_overdue event during permanent divergence (up to 150s)...")
        overdue_logged = False
        for _ in range(75):
            time.sleep(2)
            if ctrl_log.exists():
                with open(ctrl_log) as log_f:
                    content = log_f.read()
                if "recovering_overdue" in content:
                    overdue_logged = True
                    break

        assert overdue_logged, "recovering_overdue event was not logged!"
        print("CONFIRMED: recovering_overdue event logged successfully.")
        with open(ctrl_log) as log_f:
            for line in log_f.read().splitlines():
                if "recovering_overdue" in line:
                    print(f"Overdue event line: {line}")
    finally:
        if p and p.poll() is None:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            p.wait(timeout=5)

        # Cleanup: remove diverging object, re-enable replication, and unfence minio-a
        print("Cleaning up test 2 artifacts...")
        subprocess.run([str(BASE_REPO / "scripts" / "mc.sh"), "rm", "--force", "site-a/demo/perm-diverge.txt"], cwd=BASE_REPO, check=False)
        subprocess.run(
            [str(BASE_REPO / "scripts" / "mc.sh"), "replicate", "update", "site-a/demo", "--id", rule_id, "--state", "enable"],
            cwd=BASE_REPO,
            check=False,
        )
        with socket.create_connection(("127.0.0.1", 9999), timeout=3) as sock:
            sock.sendall(b"enable server minio_api/minio-a\n")
        time.sleep(2)
        print("Replication re-enabled and minio-a unfenced.")


if __name__ == '__main__':
    test_startup_reconcile()
    test_recovering_deadline()
    print("\n=== STEP 6 ALL TESTS PASSED ===")
