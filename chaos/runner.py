"""M5 Chaos Engineering Suite Runner.

Executes Stage 1 experiments (E1 Kill, E2 Pause, E5 GitOps Chaos),
records hypotheses, measured RTO/RPO metrics, and outputs the markdown
evidence report to docs/04-test-evidence/m5-chaos.md.
"""

import sys
import time
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from controller.proof import compare_sites
from chaos.common import get_project_name
from chaos.experiments import e1_kill, e2_pause, e5_gitops_chaos

REPORT_FILE = ROOT_DIR / "docs" / "04-test-evidence" / "m5-chaos.md"


def generate_markdown_report(results: list[dict], pre_check: dict, post_check: dict) -> None:
    now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    proj = get_project_name()

    lines = [
        "# M5 Evidence — Chaos Engineering & Resilience Under Stress",
        f"\n**Execution Date**: `{now_str}`  ",
        f"**Project**: `{proj}`  ",
        f"**Baseline Pre-Check Integrity**: `match: {pre_check.get('match')}` (count: {pre_check.get('count_a')})  ",
        f"**Post-Suite Integrity**: `match: {post_check.get('match')}` (count: {post_check.get('count_a')})  \n",
        "## Summary of Experiments\n",
        "| ID | Experiment | Hypothesis Held? | RTO (Failover) | RPO_failover | RPO_after_return | Primary Mechanism |",
        "|:---|:---|:---:|:---:|:---:|:---:|:---|",
    ]

    for r in results:
        eid = r.get("experiment", "unknown")
        held = "PASS (Held)" if r.get("hypothesis_held") else "FAIL (Did Not Hold)"
        rto = f"{r.get('rto_ms')} ms" if r.get("rto_ms") is not None else r.get("rto", "N/A")
        rpo_f = f"{r.get('rpo_failover')} objects" if r.get("rpo_failover") is not None else r.get("rpo", "N/A")
        rpo_r = f"{r.get('rpo_after_return')} objects" if r.get("rpo_after_return") is not None else r.get("rpo", "N/A")

        if eid == "E1_kill":
            name = "E1: Abrupt Crash (SIGKILL)"
            mech = "HAProxy health check failover to minio-b"
        elif eid == "E2_pause":
            name = "E2: Gray Failure (docker pause)"
            mech = "Socket freeze, TCP connect timeout & redispatch"
        elif eid == "E5_gitops_chaos":
            name = "E5: Chaos During GitOps Deploy"
            mech = "Active health gate failure & automatic rollback"
        else:
            name = eid
            mech = "Custom"

        lines.append(f"| `{eid}` | **{name}** | **{held}** | `{rto}` | `{rpo_f}` | `{rpo_r}` | {mech} |")

    lines.append("\n---\n")
    lines.append("## Detailed Experiment Logs\n")

    for r in results:
        eid = r.get("experiment", "unknown")
        lines.append(f"### {eid}\n")
        lines.append(f"**Hypothesis**:\n> *\"{r.get('hypothesis')}\"*\n")
        lines.append(f"- **Hypothesis Result**: `{'HELD' if r.get('hypothesis_held') else 'FAILED'}`")

        if "rto_ms" in r and r["rto_ms"] is not None:
            lines.append(f"- **Measured RTO**: `{r.get('rto_ms')} ms` (time from injection to first write served by backup)")

        if "rpo_failover" in r and r["rpo_failover"] is not None:
            lines.append(f"- **RPO_failover**: `{r.get('rpo_failover')} objects` missing on Region B at failover instant.")
            if r.get("rpo_failover_keys"):
                lines.append(f"  - Missing keys: `{r.get('rpo_failover_keys')}`")

        if "rpo_after_return" in r and r["rpo_after_return"] is not None:
            lines.append(f"- **RPO_after_return**: `{r.get('rpo_after_return')} objects` lost permanently across the platform.")
            lines.append(f"  *(Note: Region A disk volume survived, so this measures replication resync completeness, not physical disk wipe).*")

        if "total_acked" in r:
            lines.append(f"- **Client Request Attribution**:")
            lines.append(f"  - Total Acknowledged Writes: `{r.get('total_acked')}`")
            lines.append(f"  - Acknowledged by `minio-a`: `{r.get('acked_by_a')}`")
            lines.append(f"  - Acknowledged by `minio-b`: `{r.get('acked_by_b')}`")
            lines.append(f"  - Failed / Dropped Requests: `{r.get('failed_requests')}`")

        if eid == "E5_gitops_chaos":
            lines.append(f"- **Deployment Rollback Metrics**:")
            lines.append(f"  - Candidate Commit: `{r.get('candidate_commit', '')[:7]}`")
            lines.append(f"  - Rolled Back To: `{r.get('rolled_back_to', '')[:7]}`")
            lines.append(f"  - Rollback Duration: `{r.get('rollback_time_seconds')}s`")
            lines.append(f"  - Bad Commit Persisted: `{r.get('bad_commit_recorded')}`")
            lines.append(f"  - Gateway Restored: `{r.get('gateway_restored')}`")

        lines.append("\n```json\n" + json.dumps(r, indent=2) + "\n```\n")

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines))
    print(f"\nResilience report saved to: {REPORT_FILE}")


def main():
    print("==========================================================")
    print("   SETU SWFW_5S_02 — Milestone 5 Chaos Engineering Suite  ")
    print("   Stage 1: E1 (Kill), E2 (Pause), E5 (Deploy Chaos)      ")
    print("==========================================================")

    # 1. Baseline Pre-check
    print("\n--- Running Pre-Flight Baseline Integrity Check ---")
    pre_check = compare_sites()
    print(f"Baseline: match={pre_check.get('match')}, objects={pre_check.get('count_a')}")
    if not pre_check.get("match"):
        print("ERROR: Platform has pre-existing divergence before chaos tests!", file=sys.stderr)
        sys.exit(1)

    results = []

    # 2. Run E1: Crash / Kill
    try:
        e1_res = e1_kill.run()
        results.append(e1_res)
    except Exception as e:
        print(f"ERROR in E1_kill: {e}", file=sys.stderr)
        results.append({"experiment": "E1_kill", "hypothesis_held": False, "error": str(e)})

    # Settle
    time.sleep(3)

    # 3. Run E2: Gray Failure / Pause
    try:
        e2_res = e2_pause.run()
        results.append(e2_res)
    except Exception as e:
        print(f"ERROR in E2_pause: {e}", file=sys.stderr)
        results.append({"experiment": "E2_pause", "hypothesis_held": False, "error": str(e)})

    # Settle
    time.sleep(3)

    # 4. Run E5: GitOps Deploy Chaos
    try:
        e5_res = e5_gitops_chaos.run()
        results.append(e5_res)
    except Exception as e:
        print(f"ERROR in E5_gitops_chaos: {e}", file=sys.stderr)
        results.append({"experiment": "E5_gitops_chaos", "hypothesis_held": False, "error": str(e)})

    # 5. Post-Flight Integrity Check
    print("\n--- Running Post-Suite Integrity Check ---")
    post_check = compare_sites()
    print(f"Post-Suite: match={post_check.get('match')}, count_a={post_check.get('count_a')}, count_b={post_check.get('count_b')}")

    # 6. Generate Markdown Report
    generate_markdown_report(results, pre_check, post_check)

    all_held = all(r.get("hypothesis_held") for r in results)
    print("\n==========================================================")
    if all_held:
        print("   STAGE 1 CHAOS SUITE PASSED: All Hypotheses Held        ")
        print("==========================================================")
        sys.exit(0)
    else:
        print("   STAGE 1 CHAOS SUITE COMPLETED: One or more failed      ")
        print("==========================================================")
        sys.exit(1)


if __name__ == "__main__":
    main()

