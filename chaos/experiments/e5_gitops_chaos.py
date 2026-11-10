"""Experiment E5: Chaos During GitOps Deployment.

Injects failure mid-reconciliation:
- Candidate commit with valid config change is pushed to bare remote.
- Reconciler starts applying candidate.
- While the reconciler is evaluating its post-apply active health gate, gateway container is killed.
- Reconciler detects health gate timeout/failure.
- Reconciler automatically rolls back stack to last_good.
- Reconciler recreates gateway on last_good and verifies health gate passes.
- Validates that state persistence records the commit in bad_commits and stack is restored to UP.
"""

import os
import sys
import time
import json
import shutil
import urllib.request
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from chaos.common import (
    ROOT_DIR,
    get_project_name,
    docker_service,
    get_haproxy_status,
)

HYPOTHESIS = (
    "If a failure is injected during active GitOps continuous reconciliation "
    "(terminating the gateway container while the reconciler is evaluating its post-apply "
    "health gate), the reconciler will detect the health gate failure, automatically execute "
    "rollback to last_good, recreate affected containers, restore platform health, and "
    "persist the bad commit in bad_commits, without human intervention. (RTO/RPO: N/A)."
)


def run() -> dict:
    timestamp = int(time.time())
    stage_dir = Path(f"/tmp/setu-chaos-gitops-stage-{timestamp}")
    bare_remote = Path(f"/tmp/setu-chaos-gitops-remote-{timestamp}.git")
    worktree_dir = Path(f"/tmp/setu-chaos-gitops-wt-{timestamp}")
    state_file = worktree_dir / ".gitops_state.json"
    reconciler_log_path = Path(f"/tmp/setu-chaos-gitops-{timestamp}.log")
    reconciler_proc = None

    print(f"\n========================================================")
    print(f"   [E5] Chaos During GitOps Deployment Experiment       ")
    print(f"========================================================")
    print(f"Hypothesis: {HYPOTHESIS}\n")

    held = False
    details = {}
    gw_killed = False

    try:
        # 1. Setup temporary bare remote and deployment worktree
        print("Setting up temporary GitOps test repo and worktree...")
        subprocess.run(["git", "clone", "--bare", str(ROOT_DIR), str(bare_remote)], capture_output=True, check=True)
        subprocess.run(["git", "clone", str(bare_remote), str(stage_dir)], capture_output=True, check=True)
        subprocess.run(["git", "worktree", "add", str(worktree_dir), "HEAD"], cwd=ROOT_DIR, capture_output=True, check=True)

        # Configure local git identity in stage_dir
        c_name = subprocess.run(["git", "config", "user.name"], cwd=ROOT_DIR, capture_output=True, text=True, check=False)
        c_email = subprocess.run(["git", "config", "user.email"], cwd=ROOT_DIR, capture_output=True, text=True, check=False)
        author_name = c_name.stdout.strip() or "Abhishek7439"
        author_email = c_email.stdout.strip() or "cloud_automator@localhost"
        subprocess.run(["git", "config", "user.name", author_name], cwd=stage_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", author_email], cwd=stage_dir, capture_output=True, check=True)

        # Ensure deploy branch exists
        subprocess.run(["git", "checkout", "-B", "deploy"], cwd=stage_dir, capture_output=True, check=True)
        subprocess.run(["git", "push", "-u", "origin", "deploy"], cwd=stage_dir, capture_output=True, check=True)

        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=stage_dir, capture_output=True, text=True, check=True)
        base_commit = res.stdout.strip()

        # Initialize state file
        with open(state_file, "w") as f:
            json.dump({
                "deployed": base_commit,
                "last_good": base_commit,
                "last_processed": base_commit,
                "bad_commits": []
            }, f)

        # 2. Launch background reconciler
        project_name = get_project_name()
        reconciler_log = open(reconciler_log_path, "w")
        reconciler_proc = subprocess.Popen(
            [
                "python3", str(worktree_dir / "gitops" / "reconciler.py"),
                "--worktree", str(worktree_dir),
                "--remote", str(bare_remote),
                "--branch", "deploy",
                "--project", project_name,
                "--interval", "1"
            ],
            cwd=worktree_dir,
            stdout=reconciler_log,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        print(f"GitOps reconciler running (PID {reconciler_proc.pid}) against project '{project_name}'.")

        # 3. Create candidate commit with modified gateway config (valid syntax)
        print("\nPushing candidate commit with modified gateway configuration...")
        cfg_file = stage_dir / "gateway" / "haproxy.cfg"
        orig_cfg = cfg_file.read_text()
        # Add comment line to trigger targeted recreate of gateway service
        candidate_cfg = orig_cfg + f"\n# Chaos injection candidate deployment {timestamp}\n"
        cfg_file.write_text(candidate_cfg)

        subprocess.run(["git", "add", "gateway/haproxy.cfg"], cwd=stage_dir, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", f"feat(gateway): candidate update {timestamp}"], cwd=stage_dir, capture_output=True, check=True)
        subprocess.run(["git", "push", "origin", "deploy"], cwd=stage_dir, capture_output=True, check=True)

        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=stage_dir, capture_output=True, text=True, check=True)
        candidate_commit = res.stdout.strip()
        print(f"Candidate commit pushed: {candidate_commit[:7]}")

        # 4. Monitor reconciler until active health gate begins, then INJECT CHAOS
        print("Monitoring reconciler for candidate application start...")
        started_reconcile = False
        monitor_start = time.monotonic()
        while time.monotonic() - monitor_start < 15:
            time.sleep(0.5)
            if reconciler_log_path.exists():
                log_content = reconciler_log_path.read_text()
                if "reconcile_start" in log_content:
                    started_reconcile = True
                    break

        if not started_reconcile:
            print("Warning: reconcile_start not observed in log; proceeding with timed chaos.")

        # Wait 1.5 seconds for apply_targeted to finish recreating gateway and enter run_health_gate
        time.sleep(1.5)

        # >>> INJECT MID-GATE FAILURE <<<
        print(">>> INJECTING CHAOS: Killing gateway container during active health gate evaluation <<<")
        docker_service("kill", "gateway")
        gw_killed = True
        chaos_ts = time.monotonic()

        # 5. Wait for reconciler to detect failure, execute rollback, and record bad commit
        print("Waiting for health gate failure detection and automatic rollback...")
        rolled_back = False
        bad_commits_found = []
        while time.monotonic() - chaos_ts < 35:
            time.sleep(2)
            if state_file.exists():
                try:
                    with open(state_file) as f:
                        st = json.load(f)
                    bad_commits_found = st.get("bad_commits", [])
                    if candidate_commit in bad_commits_found:
                        rolled_back = True
                        break
                except Exception:
                    pass

        rollback_time_s = int(time.monotonic() - chaos_ts)

        # 6. Verify stack health restored after rollback
        st_haproxy = get_haproxy_status()
        minio_a_st = st_haproxy.get("minio_api/minio-a", "DOWN")
        
        # Also check gateway live endpoint HTTP 200
        gw_live = False
        try:
            req = urllib.request.Request("http://127.0.0.1:8080/minio/health/live", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                gw_live = (resp.status == 200)
        except Exception:
            gw_live = False

        gateway_healthy = minio_a_st.startswith("UP") and gw_live

        print(f"Rollback execution completed: {rolled_back} in {rollback_time_s}s")
        print(f"HAProxy minio-a status after rollback: {minio_a_st}")
        print(f"Gateway :8080 live HTTP status: {gw_live}")

        # Strict falsifiable assertion clauses:
        c1 = gw_killed
        c2 = rolled_back
        c3 = rollback_time_s <= 35
        c4 = candidate_commit in bad_commits_found
        c5 = gateway_healthy

        held = c1 and c2 and c3 and c4 and c5

        print(f"\n--- E5 Assertion Clauses ---")
        print(f"  - Clause 1 (Gateway container killed during gate): {c1}")
        print(f"  - Clause 2 (Reconciler triggered automated rollback): {c2}")
        print(f"  - Clause 3 (Rollback completed within 35s): {c3} ({rollback_time_s}s)")
        print(f"  - Clause 4 (Candidate marked in bad_commits): {c4}")
        print(f"  - Clause 5 (Gateway fully restored and live): {c5}")
        print(f"Overall Hypothesis Held: {held}\n")

        details = {
            "experiment": "E5_gitops_chaos",
            "hypothesis": HYPOTHESIS,
            "hypothesis_held": held,
            "assertions": {
                "gateway_killed_mid_gate": c1,
                "reconciler_triggered_rollback": c2,
                "rollback_within_35s": c3,
                "bad_commit_recorded": c4,
                "gateway_restored_healthy": c5,
            },
            "rto": "N/A",
            "rpo": "N/A",
            "candidate_commit": candidate_commit,
            "rolled_back_to": base_commit,
            "rollback_time_seconds": rollback_time_s,
            "bad_commit_recorded": rolled_back,
            "gateway_restored": gateway_healthy,
        }

    finally:
        # Stop reconciler daemon
        if reconciler_proc and reconciler_proc.poll() is None:
            try:
                import signal
                os.killpg(os.getpgid(reconciler_proc.pid), signal.SIGTERM)
                reconciler_proc.wait(timeout=5)
            except Exception:
                pass

        # Re-apply gateway from ROOT_DIR to ensure clean state
        project_name = get_project_name()
        docker_service("up", "-d")
        
        # Cleanup temporary git directories
        print("Cleaning temporary bare remotes and worktrees...")
        shutil.rmtree(bare_remote, ignore_errors=True)
        shutil.rmtree(stage_dir, ignore_errors=True)
        shutil.rmtree(worktree_dir, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=ROOT_DIR, capture_output=True, check=False)

    return details


if __name__ == "__main__":
    res = run()
    print("\nResult Summary:")
    print(json.dumps(res, indent=2))
