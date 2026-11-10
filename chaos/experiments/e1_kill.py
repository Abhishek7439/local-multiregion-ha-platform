"""Experiment E1: Burst-Load Crash (Kill minio-a).

Tests system resilience under concurrent write load (~30-50 req/s for ~11s) with abrupt SIGKILL.
Repeats 3 times to measure min/median/max RTO, RPO_failover, and RPO_after_return.
"""

import sys
import time
import json
import statistics
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from controller.proof import haproxy_command
from chaos.common import (
    setup_chaos_bucket,
    cleanup_chaos_bucket,
    get_bucket_inventory,
    ConcurrentWriter,
    docker_service,
    start_dr_controller,
    stop_dr_controller,
    run_mc,
    get_haproxy_status,
)

HYPOTHESIS = (
    "Under concurrent client write load (~30-50 req/s), executing abrupt SIGKILL on minio-a "
    "triggers HAProxy failover with first successful write on minio-b within 10,000 ms (RTO <= 10s), "
    "zero true data loss after recovery (RPO_after_return == 0), and all pre-failover writes accounted for."
)


def ensure_clean_baseline():
    """Ensure minio-a is running and un-fenced before starting an iteration."""
    docker_service("start", "minio-a")
    time.sleep(1)
    try:
        haproxy_command("enable server minio_api/minio-a")
    except Exception:
        pass
    time.sleep(1)


def run_single_iteration(iter_idx: int) -> dict:
    bucket = f"chaos-e1-i{iter_idx}-{int(time.time())}"
    ctrl_proc = None
    writer = None

    print(f"\n--- [E1 Iteration {iter_idx}/3] Bucket: {bucket} ---")
    ensure_clean_baseline()
    setup_chaos_bucket(bucket)

    try:
        # Start DR controller for automated fencing and failback
        ctrl_proc = start_dr_controller(f"/tmp/setu-chaos-e1-dr-i{iter_idx}.log")

        # Concurrent writer: 4 threads, 60ms delay ~ 35-50 req/s
        writer = ConcurrentWriter(bucket, concurrency=4, request_timeout=2.5, delay_between_req=0.06)
        writer.start()
        start_time = time.monotonic()

        # Let writer ramp up for 3.0s and acknowledge writes on minio-a
        print("  Ramping up concurrent writes (~35-45 req/s)...")
        time.sleep(3.0)

        # Inject SIGKILL while writers are actively in-flight
        kill_time = time.monotonic()
        print(f"  >>> INJECTING CHAOS: docker compose kill minio-a at T+{kill_time - start_time:.2f}s <<<")
        docker_service("kill", "minio-a")

        # Wait for first successful write on minio-b
        first_b_time = None
        timeout_wait = 12.0
        while time.monotonic() - kill_time < timeout_wait:
            results = writer.get_results()
            b_writes = [r for r in results if r["success"] and r["backend"] == "minio-b" and r["end_ts"] >= kill_time]
            if b_writes:
                first_b_time = min(r["end_ts"] for r in b_writes)
                break
            time.sleep(0.05)

        # Allow write stream to stabilize on minio-b for 3.5 more seconds (total write duration ~11s)
        time.sleep(3.5)
        writer.stop()
        all_writes = writer.get_results()

        # Calculate RTO
        if first_b_time is not None:
            rto_ms = int((first_b_time - kill_time) * 1000)
        else:
            rto_ms = None

        # Classify writes based on timestamps relative to kill
        acked_before_kill = [r for r in all_writes if r["success"] and r["backend"] == "minio-a" and r["end_ts"] <= kill_time]
        in_flight_at_kill = [r for r in all_writes if r["start_ts"] < kill_time < r["end_ts"]]
        acked_on_b = [r for r in all_writes if r["success"] and r["backend"] == "minio-b"]
        failed = [r for r in all_writes if not r["success"]]

        total_time_s = time.monotonic() - start_time
        write_rate = len(all_writes) / total_time_s if total_time_s > 0 else 0

        print(f"  Load Level: {len(all_writes)} requests in {total_time_s:.2f}s ({write_rate:.1f} req/s)")
        print(f"  Acknowledged by minio-a before kill: {len(acked_before_kill)}")
        print(f"  In-flight during kill: {len(in_flight_at_kill)}")
        print(f"  Failed / reset during failover: {len(failed)}")
        print(f"  Acknowledged by minio-b after failover: {len(acked_on_b)}")
        print(f"  Measured RTO: {rto_ms} ms")

        # Measure RPO_failover (at failover instant on Region B via fast listing inventory)
        b_inv = get_bucket_inventory(f"site-b/{bucket}")
        missing_on_b_at_failover = []
        for w in acked_before_kill:
            k = w["key"]
            expected_size = len(w["payload"])
            if k not in b_inv or b_inv[k].get("size") != expected_size:
                missing_on_b_at_failover.append(k)

        rpo_failover = len(missing_on_b_at_failover)
        print(f"  RPO_failover: {rpo_failover} object(s) missing on B at failover instant.")

        # Disaster recovery: restart minio-a and wait for failback
        print("  Restarting minio-a and waiting for failback...")
        docker_service("start", "minio-a")

        failback_ok = False
        for attempt in range(1, 41):
            time.sleep(2)
            st = get_haproxy_status()
            if st.get("minio_api/minio-a", "") == "UP":
                failback_ok = True
                print(f"  Failback verified: minio-a restored and un-fenced (UP) after {attempt * 2}s.")
                break

        # Measure RPO_after_return (permanent loss across both sites via fast listing inventory)
        a_inv = get_bucket_inventory(f"site-a/{bucket}")
        b_inv_after = get_bucket_inventory(f"site-b/{bucket}")
        missing_after_return = []
        for w in acked_before_kill:
            k = w["key"]
            expected_size = len(w["payload"])
            in_a = k in a_inv and a_inv[k].get("size") == expected_size
            in_b = k in b_inv_after and b_inv_after[k].get("size") == expected_size
            if not (in_a and in_b):
                missing_after_return.append(k)

        rpo_after_return = len(missing_after_return)
        print(f"  RPO_after_return: {rpo_after_return} object(s) permanently lost.")
        print(f"  (Note: Region A disk survived, so this reflects replication resync completeness).")

    finally:
        if writer:
            writer.stop()
        if ctrl_proc:
            stop_dr_controller(ctrl_proc)
        cleanup_chaos_bucket(bucket)
        ensure_clean_baseline()

    return {
        "iteration": iter_idx,
        "rto_ms": rto_ms,
        "rpo_failover": rpo_failover,
        "rpo_failover_keys": missing_on_b_at_failover,
        "rpo_after_return": rpo_after_return,
        "rpo_after_return_keys": missing_after_return,
        "total_requests": len(all_writes),
        "write_rate_req_sec": round(write_rate, 1),
        "acked_before_kill": len(acked_before_kill),
        "in_flight_at_kill": len(in_flight_at_kill),
        "acked_on_b": len(acked_on_b),
        "failed_requests": len(failed),
        "failback_ok": failback_ok,
    }


def run() -> dict:
    print(f"\n========================================================")
    print(f"   [E1] Crash / Kill Chaos Experiment (SIGKILL minio-a) ")
    print(f"========================================================")
    print(f"Hypothesis: {HYPOTHESIS}\n")

    iterations_data = []
    for i in range(1, 4):
        res = run_single_iteration(i)
        iterations_data.append(res)
        time.sleep(2)

    rtos = [r["rto_ms"] for r in iterations_data if r["rto_ms"] is not None]
    min_rto = min(rtos) if rtos else None
    max_rto = max(rtos) if rtos else None
    med_rto = int(statistics.median(rtos)) if rtos else None

    # Explicit hypothesis assertions (falsifiable):
    c1 = (len(rtos) == len(iterations_data)) and (max_rto is not None and max_rto <= 10000)
    c2 = all(r["rpo_after_return"] == 0 for r in iterations_data)
    c3 = all(r["write_rate_req_sec"] >= 25.0 for r in iterations_data)
    c4 = all(r["acked_before_kill"] > 0 for r in iterations_data)

    held = c1 and c2 and c3 and c4

    print("\n--- E1 Summary Across 3 Iterations ---")
    print(f"  RTO min / median / max: {min_rto}ms / {med_rto}ms / {max_rto}ms")
    print(f"  Assertion Clauses:")
    print(f"    - Clause 1 (RTO <= 10s across all runs): {c1} (max: {max_rto}ms)")
    print(f"    - Clause 2 (RPO_after_return == 0): {c2}")
    print(f"    - Clause 3 (Load rate >= 25 req/s): {c3}")
    print(f"    - Clause 4 (Pre-failover acked > 0): {c4}")
    print(f"  Overall Hypothesis Held: {held}\n")

    return {
        "experiment": "E1_kill",
        "hypothesis": HYPOTHESIS,
        "hypothesis_held": held,
        "assertions": {
            "rto_within_10s": c1,
            "zero_true_data_loss": c2,
            "sustained_load_rate": c3,
            "pre_failover_acked_positive": c4,
        },
        "rto_ms": med_rto,
        "rto_min_ms": min_rto,
        "rto_median_ms": med_rto,
        "rto_max_ms": max_rto,
        "rpo_failover": max(r["rpo_failover"] for r in iterations_data),
        "rpo_after_return": max(r["rpo_after_return"] for r in iterations_data),
        "avg_write_rate_req_sec": round(statistics.mean(r["write_rate_req_sec"] for r in iterations_data), 1),
        "iterations": iterations_data,
    }


if __name__ == "__main__":
    res = run()
    print(json.dumps(res, indent=2))
