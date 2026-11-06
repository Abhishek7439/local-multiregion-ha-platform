#!/usr/bin/env python3
"""GitOps Reconciler for SETU multi-region platform.

Polls a git remote branch, validates docker compose syntax, applies changes
using `docker compose up -d` with a fixed project name, enforces an active
health gate (gateway live + write through gateway + read on Region B),
and automatically rolls back to the last known good commit if health checks fail.

Design rules enforced:
- Zero external Python dependencies (standard library only).
- Never touches dev checkout (~/setu-starter); works only in its deployment worktree.
- Targeted container recreation: never recreate minio-a/minio-b unless their
  own definition changed. Only recreate services whose files changed.
- Apply only when HAProxy reports both backends UP and minio-a not in MAINT.
- Skips known-bad commits on subsequent cycles until a new commit arrives.
- Persists state (last_good, bad_commits, deployed) across restarts.
- Drift policy: report-only (D9) to prevent fighting automated DR failover.
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_event(event):
    """Print one JSON object per line so GitOps events are machine-readable."""
    event["ts"] = utc_now()
    print(json.dumps(event), flush=True)


def run_cmd(cmd, cwd=None, timeout=60, check=False):
    """Run a subprocess command and return CompletedProcess."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


class GitOpsReconciler:
    def __init__(self, worktree_dir, remote_url, branch="deploy",
                 project_name="setu-multiregion", state_file=None):
        self.worktree_dir = Path(worktree_dir).resolve()
        self.remote_url = remote_url
        self.branch = branch
        self.project_name = project_name
        self.state_file = Path(state_file).resolve() if state_file else self.worktree_dir / ".gitops_state.json"
        self.state = self.load_state()

    def load_state(self):
        default = {
            "last_good": None,
            "bad_commits": [],
            "deployed": None,
        }
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    st = {**default, **json.load(f)}
                    if not st.get("last_good"):
                        st["last_good"] = st.get("deployed")
                    return st
            except Exception as e:
                log_event({"event": "state_load_error", "detail": str(e)})
        return default

    def save_state(self):
        tmp_path = self.state_file.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self.state, f, indent=2)
        tmp_path.replace(self.state_file)

    def direct_minio_healthy(self):
        """Check if direct MinIO endpoints :9100 and :9200 return HTTP 200."""
        a_ok = False
        b_ok = False
        try:
            req_a = urllib.request.Request("http://127.0.0.1:9100/minio/health/live", method="GET")
            with urllib.request.urlopen(req_a, timeout=2) as resp:
                a_ok = (resp.status == 200)
        except Exception:
            a_ok = False
        try:
            req_b = urllib.request.Request("http://127.0.0.1:9200/minio/health/live", method="GET")
            with urllib.request.urlopen(req_b, timeout=2) as resp:
                b_ok = (resp.status == 200)
        except Exception:
            b_ok = False
        return a_ok and b_ok

    def haproxy_backends_ready(self):
        """Query HAProxy admin socket on 127.0.0.1:9999.
        Returns (ready: bool, reason: str, statuses: dict).
        Ready only if both minio-a and minio-b are UP and minio-a is not in MAINT.
        If HAProxy socket is unreachable, checks direct MinIO health so the
        reconciler does not defer forever when the gateway is broken.
        """
        try:
            with socket.create_connection(("127.0.0.1", 9999), timeout=3) as sock:
                sock.sendall(b"show stat\n")
                sock.shutdown(socket.SHUT_WR)
                buf = b""
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break
                    buf += data
            lines = buf.decode(errors="replace").splitlines()
            statuses = {}
            for line in lines:
                if line.startswith("#") or not line.strip():
                    continue
                fields = line.split(",")
                if len(fields) > 17 and fields[0] == "minio_api":
                    statuses[fields[1]] = fields[17]

            a_stat = statuses.get("minio-a", "DOWN")
            b_stat = statuses.get("minio-b", "DOWN")

            if "MAINT" in a_stat:
                return False, f"minio-a is fenced in MAINT ({a_stat})", statuses
            if a_stat != "UP":
                return False, f"minio-a is not UP ({a_stat})", statuses
            if b_stat != "UP":
                return False, f"minio-b is not UP ({b_stat})", statuses
            return True, "backends healthy", statuses
        except Exception as e:
            # Gateway/socket unreachable: check if storage layer is healthy
            if self.direct_minio_healthy():
                return True, f"HAProxy socket unreachable ({e}) but direct MinIO A and B are UP; applying to restore gateway", {"gateway": "DOWN", "minio-a": "UP", "minio-b": "UP"}
            return False, f"HAProxy socket unreachable: {e}", {}

    def check_gateway_live(self, timeout=2):
        """HTTP GET to gateway live check endpoint."""
        try:
            req = urllib.request.Request("http://127.0.0.1:8080/minio/health/live", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def check_write_read_roundtrip(self):
        """Write through gateway and read on Region B, verifying SHA-256."""
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        key = f"demo/gitops-gate-{stamp}.txt"
        payload = f"gitops-gate-{stamp}\n".encode()
        expected_sha = hashlib.sha256(payload).hexdigest()

        mc = self.worktree_dir / "scripts" / "mc.sh"
        if not mc.exists():
            return False, "scripts/mc.sh not found in worktree"

        # 1. Write via gateway
        res_w = subprocess.run(
            [str(mc), "pipe", f"gw/{key}"],
            input=payload,
            cwd=self.worktree_dir,
            capture_output=True,
            timeout=15,
        )
        if res_w.returncode != 0:
            return False, f"write via gateway failed: {res_w.stderr.decode(errors='replace')[-200:]}"

        # Allow replication time
        time.sleep(2)

        # 2. Read from Region B
        res_r = subprocess.run(
            [str(mc), "cat", f"site-b/{key}"],
            cwd=self.worktree_dir,
            capture_output=True,
            timeout=15,
        )
        if res_r.returncode != 0:
            return False, f"read from site-b failed: {res_r.stderr.decode(errors='replace')[-200:]}"

        actual_sha = hashlib.sha256(res_r.stdout).hexdigest()
        if actual_sha != expected_sha:
            return False, f"sha mismatch: expected {expected_sha}, got {actual_sha}"

        return True, "ok"

    def run_health_gate(self, max_attempts=6, poll_sec=2):
        """Execute health gate with retries based on container startup times."""
        for attempt in range(1, max_attempts + 1):
            if self.check_gateway_live(timeout=2):
                ok, msg = self.check_write_read_roundtrip()
                if ok:
                    return True, f"passed on attempt {attempt}"
                err = msg
            else:
                err = "gateway :8080 not responding HTTP 200"
            if attempt < max_attempts:
                time.sleep(poll_sec)
        return False, err

    def check_drift(self):
        """Report-only drift detection (D9)."""
        res_cfg = run_cmd(
            ["docker", "compose", "-p", self.project_name, "config", "--services"],
            cwd=self.worktree_dir,
        )
        if res_cfg.returncode != 0:
            return []
        expected = set(res_cfg.stdout.strip().splitlines())

        res_ps = run_cmd(
            ["docker", "compose", "-p", self.project_name, "ps", "--services", "--filter", "status=running"],
            cwd=self.worktree_dir,
        )
        if res_ps.returncode != 0:
            return []
        running = set(res_ps.stdout.strip().splitlines())

        missing = sorted(list(expected - running))
        if missing:
            log_event({
                "event": "drift_detected",
                "policy": "report_only",
                "missing_services": missing,
                "reason": "containers stopped out-of-band; not auto-healed per D9",
            })
        return missing

    def apply_targeted(self, from_commit, to_commit):
        """Determine which services changed and apply/recreate only those.
        Never recreates minio-a or minio-b unless their definition in compose changed.
        """
        diff_res = run_cmd(
            ["git", "diff", "--name-only", from_commit, to_commit],
            cwd=self.worktree_dir,
        )
        changed_files = diff_res.stdout.strip().splitlines() if diff_res.returncode == 0 else []
        log_event({"event": "diff_detected", "from": from_commit, "to": to_commit, "changed_files": changed_files})

        # 1. If docker-compose.yml changed, run normal compose up
        # Docker Compose inspects service definitions and only recreates changed services
        if "docker-compose.yml" in changed_files or not from_commit:
            up_res = run_cmd(
                ["docker", "compose", "-p", self.project_name, "up", "-d"],
                cwd=self.worktree_dir,
            )
            if up_res.returncode != 0:
                return False, f"compose up failed: {up_res.stderr.strip()[:300]}"

        # 2. If gateway configuration (haproxy.cfg) changed, force-recreate gateway only
        gateway_changed = any(f.startswith("gateway/") for f in changed_files)
        if gateway_changed:
            log_event({"event": "service_recreate", "service": "gateway", "reason": "gateway configuration changed"})
            gw_res = run_cmd(
                ["docker", "compose", "-p", self.project_name, "up", "-d", "--no-deps", "--force-recreate", "gateway"],
                cwd=self.worktree_dir,
            )
            if gw_res.returncode != 0:
                return False, f"gateway recreate failed: {gw_res.stderr.strip()[:300]}"

            # Immediately re-check HAProxy show stat after gateway recreate
            time.sleep(1)
            ready, reason, statuses = self.haproxy_backends_ready()
            log_event({"event": "haproxy_post_recreate_stat", "ready": ready, "reason": reason, "statuses": statuses})

        return True, "applied"

    def reconcile_cycle(self):
        # 1. Fetch remote branch into FETCH_HEAD
        fetch = run_cmd(
            ["git", "fetch", self.remote_url, self.branch],
            cwd=self.worktree_dir,
        )
        if fetch.returncode != 0:
            log_event({"event": "fetch_failed", "error": fetch.stderr.strip()})
            return False

        # Get latest commit from remote branch
        rev = run_cmd(["git", "rev-parse", "FETCH_HEAD"], cwd=self.worktree_dir)
        if rev.returncode != 0:
            log_event({"event": "rev_parse_failed", "error": rev.stderr.strip()})
            return False
        remote_commit = rev.stdout.strip()

        # If initial state has no last_good or deployed, initialize from current worktree HEAD
        if not self.state["deployed"]:
            wt_head = run_cmd(["git", "rev-parse", "HEAD"], cwd=self.worktree_dir).stdout.strip()
            self.state["deployed"] = wt_head
            if not self.state["last_good"]:
                self.state["last_good"] = wt_head
            self.save_state()

        # 2. Check if remote_commit is already deployed
        if remote_commit == self.state["deployed"]:
            self.check_drift()
            return True

        # 3. Check if remote_commit is a known bad commit
        if remote_commit in self.state["bad_commits"]:
            log_event({
                "event": "skip_bad_commit",
                "commit": remote_commit,
                "reason": "previously marked bad; waiting for new commit",
            })
            return True

        # 4. Check HAProxy pre-condition: backends ready & minio-a not MAINT
        ready, reason, statuses = self.haproxy_backends_ready()
        if not ready:
            log_event({
                "event": "deferred",
                "commit": remote_commit,
                "reason": reason,
                "statuses": statuses,
            })
            return False

        # 5. Check out candidate commit in worktree
        log_event({"event": "reconcile_start", "commit": remote_commit})
        co = run_cmd(["git", "checkout", "-f", remote_commit], cwd=self.worktree_dir)
        if co.returncode != 0:
            log_event({"event": "checkout_failed", "commit": remote_commit, "error": co.stderr.strip()})
            return False

        start_time = time.monotonic()

        # 6. Syntax validation (docker compose config)
        val = run_cmd(
            ["docker", "compose", "-p", self.project_name, "config"],
            cwd=self.worktree_dir,
        )
        if val.returncode != 0:
            log_event({
                "event": "validation_failed",
                "commit": remote_commit,
                "error": val.stderr.strip()[:300],
            })
            self.state["bad_commits"].append(remote_commit)
            # Revert worktree checkout to last_good
            run_cmd(["git", "checkout", "-f", self.state["last_good"]], cwd=self.worktree_dir)
            self.save_state()
            return False

        # 7. Apply candidate via targeted application
        ok_apply, apply_msg = self.apply_targeted(self.state["last_good"], remote_commit)
        if not ok_apply:
            log_event({
                "event": "apply_failed",
                "commit": remote_commit,
                "error": apply_msg,
            })
            self.rollback(remote_commit, reason=apply_msg)
            return False

        # 8. Active Health Gate (gateway :8080 live + e2e write/read roundtrip)
        passed, gate_msg = self.run_health_gate(max_attempts=6, poll_sec=2)
        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        if passed:
            self.state["last_good"] = remote_commit
            self.state["deployed"] = remote_commit
            self.save_state()
            log_event({
                "event": "deployed",
                "commit": remote_commit,
                "duration_ms": elapsed_ms,
                "health_gate": gate_msg,
            })
            return True
        else:
            log_event({
                "event": "gate_failed",
                "commit": remote_commit,
                "reason": gate_msg,
                "duration_ms": elapsed_ms,
            })
            self.rollback(remote_commit, reason=f"health gate failed: {gate_msg}")
            return False

    def rollback(self, failed_commit, reason=""):
        rb_start = time.monotonic()
        last_good = self.state["last_good"]
        log_event({
            "event": "rollback_start",
            "from": failed_commit,
            "to": last_good,
            "reason": reason,
        })
        self.state["bad_commits"].append(failed_commit)

        # Checkout last good commit in worktree
        run_cmd(["git", "checkout", "-f", last_good], cwd=self.worktree_dir)

        # Re-apply last good configuration using targeted apply
        self.apply_targeted(failed_commit, last_good)

        # Verify health gate on rolled back stack
        passed, msg = self.run_health_gate(max_attempts=6, poll_sec=2)
        rb_elapsed_ms = int((time.monotonic() - rb_start) * 1000)

        if passed:
            self.state["deployed"] = last_good
            self.save_state()
            log_event({
                "event": "rolled_back",
                "to": last_good,
                "success": True,
                "duration_ms": rb_elapsed_ms,
            })
        else:
            log_event({
                "event": "rollback_failed",
                "to": last_good,
                "detail": msg,
                "duration_ms": rb_elapsed_ms,
            })


def main():
    parser = argparse.ArgumentParser(description="GitOps Reconciler")
    parser.add_argument("--worktree", default="/tmp/setu-gitops-wt", help="Path to deployment worktree")
    parser.add_argument("--remote", default="/tmp/setu-gitops-remote.git", help="Git remote URL or path")
    parser.add_argument("--branch", default="deploy", help="Branch to track")
    parser.add_argument("--project", default="setu-multiregion", help="Docker Compose project name")
    parser.add_argument("--state-file", default=None, help="State file path")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=2, help="Poll interval in seconds")
    parser.add_argument("--check-drift", action="store_true", help="Check drift only and exit")
    args = parser.parse_args()

    reconciler = GitOpsReconciler(
        worktree_dir=args.worktree,
        remote_url=args.remote,
        branch=args.branch,
        project_name=args.project,
        state_file=args.state_file,
    )

    if args.check_drift:
        reconciler.check_drift()
        return

    if args.once:
        reconciler.reconcile_cycle()
        return

    log_event({
        "event": "reconciler_loop_start",
        "worktree": str(reconciler.worktree_dir),
        "remote": reconciler.remote_url,
        "branch": reconciler.branch,
        "interval_seconds": args.interval,
    })

    try:
        while True:
            reconciler.reconcile_cycle()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log_event({"event": "reconciler_stop", "reason": "keyboard interrupt"})


if __name__ == "__main__":
    main()
