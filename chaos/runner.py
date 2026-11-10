"""M5 Chaos Engineering Suite Runner.

Executes all 5 experiments:
  Stage 1: E1 (Kill), E2 (Pause), E5 (GitOps Chaos)
  Stage 3: E3 (Latency/Bandwidth), E4 (Partition)
Records hypotheses, measured RTO/RPO metrics, and outputs the markdown
evidence report to docs/04-test-evidence/m5-chaos.md.
"""

import sys
import time
import json
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from controller.proof import compare_sites
from chaos.common import get_project_name, run_mc
from chaos.experiments import e1_kill, e2_pause, e3_latency, e4_partition, e5_gitops_chaos

REPORT_FILE = ROOT_DIR / "docs" / "04-test-evidence" / "m5-chaos.md"


def get_bucket_keys(target: str) -> set[str]:
    """Retrieve all object keys in a target bucket path (e.g. site-a/demo)."""
    res = run_mc(["ls", "--recursive", "--json", target])
    if res.returncode != 0:
        return set()
    keys = set()
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            keys.add(json.loads(line).get("key", ""))
        except Exception:
            pass
    return keys


def generate_markdown_report(results: list[dict], pre_check: dict, post_check: dict, cleaned_rto_keys: list[str]) -> None:
    now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    proj = get_project_name()

    lines = [
        "# M5 Evidence — Chaos Engineering & Resilience Under Stress",
        f"\n**Execution Date**: `{now_str}`  ",
        f"**Project**: `{proj}`  ",
        f"**Baseline Pre-Check Integrity**: `match: {pre_check.get('match')}` (count: {pre_check.get('count_a')})  ",
        f"**Post-Suite Integrity**: `match: {post_check.get('match')}` (count: {post_check.get('count_a')})  ",
        f"**Ephemeral Failover Probes Cleaned**: `{len(cleaned_rto_keys)}` (`{cleaned_rto_keys}`)  \n",
        "## Summary of Experiments\n",
        "| ID | Experiment | Hypothesis Held? | RTO (min / med / max) | RPO_failover | RPO_after_return | Primary Mechanism |",
        "|:---|:---|:---:|:---:|:---:|:---:|:---|",
    ]

    for r in results:
        eid = r.get("experiment", "unknown")
        held = "PASS (Held)" if r.get("hypothesis_held") else "FAIL (Did Not Hold)"
        
        if "rto_median_ms" in r and r["rto_median_ms"] is not None:
            rto = f"{r.get('rto_min_ms')} / {r.get('rto_median_ms')} / {r.get('rto_max_ms')} ms"
        elif "rto_ms" in r and r["rto_ms"] is not None:
            rto = f"{r.get('rto_ms')} ms"
        else:
            rto = r.get("rto", "N/A")

        rpo_f = f"{r.get('rpo_failover')} obj" if r.get("rpo_failover") is not None else r.get("rpo", "N/A")
        rpo_r = f"{r.get('rpo_after_return')} obj" if r.get("rpo_after_return") is not None else r.get("rpo", "N/A")

        if eid == "E1_kill":
            name = "E1: Abrupt Crash (SIGKILL)"
            mech = "HAProxy health check failover to minio-b under concurrent writes"
        elif eid == "E2_pause":
            name = "E2: Gray Failure (docker pause)"
            mech = "Socket freeze, client timeout/redispatch to minio-b"
        elif eid == "E3_latency":
            name = "E3: WAN Latency & Bandwidth Throttling"
            mech = "Toxiproxy latency/bandwidth toxics on replication path"
        elif eid == "E4_partition":
            name = "E4: Asymmetric Network Partition"
            mech = "Toxiproxy timeout toxic blocks A→B; conflict resolution after heal"
        elif eid == "E5_gitops_chaos":
            name = "E5: Chaos During GitOps Deploy"
            mech = "Active health gate failure & automated rollback to last_good"
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

        if "assertions" in r:
            lines.append("- **Explicit Falsifiable Assertions**:")
            for k, v in r["assertions"].items():
                lines.append(f"  - `{k}`: `{v}`")

        if "rto_median_ms" in r and r["rto_median_ms"] is not None:
            lines.append(f"- **Measured RTO Across Iterations**:")
            lines.append(f"  - Min RTO: `{r.get('rto_min_ms')} ms`")
            lines.append(f"  - Median RTO: `{r.get('rto_median_ms')} ms`")
            lines.append(f"  - Max RTO: `{r.get('rto_max_ms')} ms`")
            lines.append(f"  - Client Timeout Impact: In concurrent writes, client request timeout determines whether in-flight requests fail or succeed during backend transition.")

        if "avg_write_rate_req_sec" in r:
            lines.append(f"- **Load Level**: Sustained `{r.get('avg_write_rate_req_sec')} req/s` (5 concurrent worker threads)")

        if "rpo_failover" in r and r["rpo_failover"] is not None:
            lines.append(f"- **RPO_failover**: `{r.get('rpo_failover')} objects` missing on Region B at failover instant.")

        if "rpo_after_return" in r and r["rpo_after_return"] is not None:
            lines.append(f"- **RPO_after_return**: `{r.get('rpo_after_return')} objects` lost permanently across the platform.")
            lines.append(f"  *(Note: Region A disk volume survived, so this measures replication resync completeness, not physical disk wipe).*")

        if eid == "E5_gitops_chaos":
            lines.append(f"- **Deployment Rollback Metrics**:")
            lines.append(f"  - Candidate Commit: `{r.get('candidate_commit', '')[:7]}`")
            lines.append(f"  - Rolled Back To: `{r.get('rolled_back_to', '')[:7]}`")
            lines.append(f"  - Rollback Duration: `{r.get('rollback_time_seconds')}s`")
            lines.append(f"  - Bad Commit Persisted: `{r.get('bad_commit_recorded')}`")
            lines.append(f"  - Gateway Restored: `{r.get('gateway_restored')}`")

        if eid == "E3_latency" and "scenarios" in r:
            lines.append(f"\n**Scenario Breakdown**:")
            bl = r.get("baseline", {})
            lines.append(f"- Baseline (no toxics): lag = `{bl.get('replication_lag_s')}s`, "
                         f"replicated = `{bl.get('objects_replicated')}`")
            for s in r["scenarios"]:
                lines.append(f"- {s['scenario']}: lag = `{s['replication_lag_s']}s`, "
                             f"write rate = `{s['write_rate_req_s']} req/s`, "
                             f"replicated = `{s['objects_replicated']}/{s['acked']}`")

        if eid == "E4_partition":
            lines.append(f"- **Partition Duration**: `{r.get('partition_duration_s')}s`")
            lines.append(f"- **Catch-up Time After Heal**: `{r.get('catch_up_time_s')}s`")
            lines.append(f"- **Writes During Partition**: A = `{r.get('partition_writes_a')}`, "
                         f"B = `{r.get('partition_writes_b')}`")
            missing_a = r.get("missing_a_on_b_after_heal", [])
            missing_b = r.get("missing_b_on_a_after_heal", [])
            lines.append(f"- **Non-conflict writes lost**: A→B missing = `{len(missing_a)}`, "
                         f"B→A missing = `{len(missing_b)}`")
            if "conflict_resolution" in r:
                lines.append(f"\n**Conflict Resolution**:")
                for c in r["conflict_resolution"]:
                    lines.append(f"- `{c['key']}`: winner = `{c.get('winner')}`, "
                                 f"consistent = `{c.get('consistent')}`")

        if "iterations" in r:
            lines.append("\n**Iteration Breakdown**:")
            for it in r["iterations"]:
                lines.append(f"- Iteration {it['iteration']}: RTO = `{it['rto_ms']} ms`, Load = `{it['write_rate_req_sec']} req/s`, "
                             f"Pre-chaos acked = `{it.get('acked_before_kill', it.get('acked_before_pause', 0))}`, "
                             f"Acked on B = `{it['acked_on_b']}`, Failed = `{it['failed_requests']}`, "
                             f"RPO_failover = `{it['rpo_failover']}`, RPO_after_return = `{it['rpo_after_return']}`")

        lines.append("\n```json\n" + json.dumps(r, indent=2) + "\n```\n")

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines))
    print(f"\nResilience report saved to: {REPORT_FILE}")


def main():
    print("==========================================================")
    print("   SETU SWFW_5S_02 — Milestone 5 Chaos Engineering Suite  ")
    print("   E1 (Kill), E2 (Pause), E3 (Latency), E4 (Partition),  ")
    print("   E5 (Deploy Chaos) — 5 experiments total                ")
    print("==========================================================")

    # 1. Baseline Pre-check
    print("\n--- Running Pre-Flight Baseline Integrity Check ---")
    pre_check = compare_sites()
    pre_demo_keys = get_bucket_keys("site-a/demo")
    print(f"Baseline: match={pre_check.get('match')}, count_a={pre_check.get('count_a')}, demo_keys={len(pre_demo_keys)}")
    if not pre_check.get("match"):
        print("ERROR: Platform has pre-existing divergence before chaos tests!", file=sys.stderr)
        sys.exit(1)

    results = []

    # 2. Run E1: Crash / Kill (3 iterations)
    try:
        e1_res = e1_kill.run()
        results.append(e1_res)
    except Exception as e:
        print(f"ERROR in E1_kill: {e}", file=sys.stderr)
        results.append({"experiment": "E1_kill", "hypothesis_held": False, "error": str(e)})

    # Settle
    time.sleep(3)

    # 3. Run E2: Gray Failure / Pause (3 iterations)
    try:
        e2_res = e2_pause.run()
        results.append(e2_res)
    except Exception as e:
        print(f"ERROR in E2_pause: {e}", file=sys.stderr)
        results.append({"experiment": "E2_pause", "hypothesis_held": False, "error": str(e)})

    # Settle
    time.sleep(3)

    # 4. Run E3: WAN Latency & Bandwidth Throttling (via Toxiproxy)
    try:
        e3_res = e3_latency.run()
        results.append(e3_res)
    except Exception as e:
        print(f"ERROR in E3_latency: {e}", file=sys.stderr)
        results.append({"experiment": "E3_latency", "hypothesis_held": False, "error": str(e)})

    # Settle
    time.sleep(3)

    # 5. Run E4: Asymmetric Network Partition & Conflict Resolution
    try:
        e4_res = e4_partition.run()
        results.append(e4_res)
    except Exception as e:
        print(f"ERROR in E4_partition: {e}", file=sys.stderr)
        results.append({"experiment": "E4_partition", "hypothesis_held": False, "error": str(e)})

    # Settle
    time.sleep(3)

    # 6. Run E5: GitOps Deploy Chaos
    try:
        e5_res = e5_gitops_chaos.run()
        results.append(e5_res)
    except Exception as e:
        print(f"ERROR in E5_gitops_chaos: {e}", file=sys.stderr)
        results.append({"experiment": "E5_gitops_chaos", "hypothesis_held": False, "error": str(e)})

    # 7. Clean ephemeral failover probe files generated by DR controller during tests
    post_demo_keys = get_bucket_keys("site-a/demo")
    new_rto_keys = sorted(list(post_demo_keys - pre_demo_keys))
    cleaned_rto_keys = []
    for k in new_rto_keys:
        if k.startswith("rto-"):
            run_mc(["rm", "--force", f"site-a/demo/{k}"])
            run_mc(["rm", "--force", f"site-b/demo/{k}"])
            cleaned_rto_keys.append(k)

    if cleaned_rto_keys:
        print(f"\nCleaned {len(cleaned_rto_keys)} ephemeral DR probe files from demo: {cleaned_rto_keys}")
        time.sleep(2)

    # 8. Post-Flight Integrity Check
    print("\n--- Running Post-Suite Integrity Check ---")
    post_check = compare_sites()
    print(f"Post-Suite: match={post_check.get('match')}, count_a={post_check.get('count_a')}, count_b={post_check.get('count_b')}")

    # 9. Generate Markdown Report
    generate_markdown_report(results, pre_check, post_check, cleaned_rto_keys)

    all_held = all(r.get("hypothesis_held") for r in results)
    print("\n==========================================================")
    if all_held:
        print("   M5 CHAOS SUITE PASSED: All 5 Hypotheses Held          ")
        print("==========================================================")
        sys.exit(0)
    else:
        print("   M5 CHAOS SUITE COMPLETED: One or more hypotheses failed")
        print("==========================================================")
        sys.exit(1)


if __name__ == "__main__":
    main()
