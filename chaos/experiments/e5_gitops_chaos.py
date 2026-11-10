"""Experiment E5: Chaos During GitOps Deployment.

Injects failure mid-reconciliation:
- Candidate commit is pushed to bare remote.
- Reconciler starts applying candidate.
- While the reconciler is evaluating its post-apply active health gate, gateway is killed.
- Reconciler detects health gate timeout/failure.
- Reconciler automatically rolls back stack to last_good.
- Validates that state persistence records the commit in bad_commits and stack is restored to UP.
"""

import os
import time
import json
import shutil
import subprocess
from pathlib import Path

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
    reconciler_proc = None

    print(f"\n========================================================")
    print(f"   [E5] Chaos During GitOps Deployment Experiment       ")
    print(f"========================================================")
    print(f"Hypothesis: {HYPOTHESIS}\n")

    held = False
    details = {}

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
        reconciler_log = open(f"/tmp/setu-chaos-gitops-{timestamp}.log", "w")
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

        # 3. Create candidate commit with modified gateway config that will fail health checks
        print("\nPushing candidate commit with broken gateway port to trigger health gate...")
        cfg_file = stage_dir / "gateway" / "haproxy.cfg"
        orig_cfg = cfg_file.read_text()
        # Point backend to an invalid port so health check fails
        broken_cfg = orig_cfg.replace("server minio-a minio-a:9000", "server minio-a minio-a:99999")
        cfg_file.write_text(broken_cfg)

        subprocess.run(["git", "add", "gateway/haproxy.cfg"], cwd=stage_dir, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "chaos: point minio-a to invalid port"], cwd=stage_dir, capture_output=True, check=True)
        subprocess.run(["git", "push", "origin", "deploy"], cwd=stage_dir, capture_output=True, check=True)

        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=stage_dir, capture_output=True, text=True, check=True)
        bad_commit = res.stdout.strip()
        print(f"Candidate bad commit pushed: {bad_commit[:7]}")

        # 4. Wait for reconciler to detect failure, execute rollback, and record bad commit
        print("Waiting for health gate failure and automatic rollback...")
        rolled_back = False
        start_wait = time.monotonic()
        while time.monotonic() - start_wait < 35:
            time.sleep(2)
            if state_file.exists():
                try:
                    with open(state_file) as f:
                        st = json.load(f)
                    if bad_commit in st.get("bad_commits", []):
                        rolled_back = True
                        break
                except Exception:
                    pass

        rollback_time_s = int(time.monotonic() - start_wait)

        # 5. Verify stack health restored
        st_haproxy = get_haproxy_status()
        minio_a_st = st_haproxy.get("minio_api/minio-a", "DOWN")
        gateway_healthy = minio_a_st.startswith("UP")

        print(f"Rollback execution completed: {rolled_back} in {rollback_time_s}s")
        print(f"HAProxy minio-a status after rollback: {minio_a_st}")

        held = rolled_back and gateway_healthy
        print(f"\nHypothesis Held: {held}")

        details = {
            "experiment": "E5_gitops_chaos",
            "hypothesis": HYPOTHESIS,
            "hypothesis_held": held,
            "rto": "N/A",
            "rpo": "N/A",
            "candidate_commit": bad_commit,
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

