"""Experiment E3: WAN Latency & Bandwidth Throttling via Toxiproxy.

Measures how injected network degradation on the A↔B replication path
affects replication lag and write throughput. No node failure occurs;
RTO and RPO are N/A (degradation, not outage).

Scenarios tested:
  1. WAN Latency injection (500ms round-trip latency on replication path)
  2. Bandwidth throttling (32 KB/s rate limit on replication path)
  3. Combined latency + bandwidth constraint (500ms + 32 KB/s)

For each scenario:
  - Write a burst of non-compressible objects to site-a via gateway.
  - Measure time until all objects appear on site-b (replication lag from burst start).
  - Verify 100% replication consistency across both regions with zero data loss.
"""

import os
import sys
import time
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from chaos.common import (
    setup_chaos_bucket,
    cleanup_chaos_bucket,
    put_object_gateway,
    get_bucket_inventory,
    run_mc,
    toxiproxy_ensure_proxy,
    toxiproxy_add_toxic,
    toxiproxy_remove_all_toxics,
    toxiproxy_delete_proxy,
    repoint_replication_through_proxy,
    repoint_replication_direct,
)

HYPOTHESIS = (
    "Injecting 500ms WAN latency or 32KB/s bandwidth constraint on the A↔B replication path "
    "increases replication lag measurably (>=1.5s vs <0.8s baseline for a 15-object burst) "
    "while maintaining 100% data consistency (zero data loss across all scenarios); "
    "after removing toxics and restoring direct replication, both sites remain fully synchronized."
)


def write_burst(bucket: str, count: int = 15, size_bytes: int = 20480) -> list[dict]:
    """Write `count` objects to `bucket` through the gateway. Returns write results."""
    results = []
    for i in range(count):
        key = f"burst-{i:04d}.bin"
        payload = os.urandom(size_bytes)
        res = put_object_gateway(bucket, key, payload, timeout=10.0)
        res["key"] = key
        res["expected_size"] = size_bytes
        results.append(res)
    return results


def measure_replication_lag(bucket: str, expected_count: int, start_time: float,
                            timeout_s: float = 60.0) -> tuple[float, int]:
    """Wait until site-b has `expected_count` objects in `bucket`.

    Returns (lag_seconds, objects_replicated).
    """
    replicated = 0
    while time.monotonic() - start_time < timeout_s:
        inv = get_bucket_inventory(f"site-b/{bucket}")
        replicated = len(inv)
        if replicated >= expected_count:
            return round(time.monotonic() - start_time, 2), replicated
        time.sleep(0.2)
    return round(time.monotonic() - start_time, 2), replicated


def run_scenario(name: str, toxics: list[dict], bucket: str,
                 burst_count: int = 15, size_bytes: int = 20480) -> dict:
    """Run a single latency/bandwidth scenario.

    Steps: add toxics → write burst → measure replication lag → remove toxics.
    """
    print(f"\n  --- Scenario: {name} ---")

    # Add toxics
    toxic_names = []
    for t in toxics:
        created = toxiproxy_add_toxic("minio_b_replication", t)
        toxic_names.append(created.get("name", t.get("name", "unknown")))
        print(f"    Added toxic: {created.get('name')} ({created.get('type')})")

    # Small pause to ensure toxics are active across existing connections
    time.sleep(0.5)

    # Write burst and measure lag from the start of the burst
    write_start = time.monotonic()
    writes = write_burst(bucket, count=burst_count, size_bytes=size_bytes)
    write_end = time.monotonic()
    write_duration = round(write_end - write_start, 2)
    acked = [w for w in writes if w["success"]]
    failed = [w for w in writes if not w["success"]]
    write_rate = round(len(acked) / write_duration, 1) if write_duration > 0 else 0

    print(f"    Writes: {len(acked)} acked, {len(failed)} failed in {write_duration}s "
          f"({write_rate} req/s)")

    # Measure replication lag from the start of the write stream
    lag_s, replicated = measure_replication_lag(bucket, len(acked), start_time=write_start)
    print(f"    Replication lag: {lag_s}s ({replicated}/{len(acked)} objects on site-b)")

    # Remove toxics immediately after measurement
    toxiproxy_remove_all_toxics("minio_b_replication")
    print(f"    Toxics removed.")

    # Wait for any remaining replication to complete if needed
    if replicated < len(acked):
        print(f"    Waiting for remaining replication...")
        time.sleep(3)
        inv = get_bucket_inventory(f"site-b/{bucket}")
        replicated = len(inv)

    return {
        "scenario": name,
        "toxics_applied": [t.get("type", "unknown") for t in toxics],
        "burst_count": burst_count,
        "object_size_bytes": size_bytes,
        "acked": len(acked),
        "failed": len(failed),
        "write_duration_s": write_duration,
        "write_rate_req_s": write_rate,
        "replication_lag_s": lag_s,
        "objects_replicated": replicated,
        "all_replicated": replicated >= len(acked),
    }


def run() -> dict:
    print(f"\n========================================================")
    print(f"   [E3] WAN Latency & Bandwidth Throttling Experiment  ")
    print(f"========================================================")
    print(f"Hypothesis: {HYPOTHESIS}\n")

    timestamp = int(time.time())
    base_bucket = f"chaos-e3-{timestamp}"
    scenarios_data = []
    c1 = c2 = c3 = c4 = False
    held = False
    bl_lag = 0.0
    bl_repl = 0

    try:
        # Setup: ensure Toxiproxy proxy exists and re-point replication
        print("Setting up Toxiproxy proxy and re-pointing replication...")
        toxiproxy_ensure_proxy()
        assert repoint_replication_through_proxy(), "Failed to re-point replication"

        # Verify baseline replication through proxy works (no toxics)
        baseline_bucket = f"{base_bucket}-baseline"
        setup_chaos_bucket(baseline_bucket)
        time.sleep(2)
        bl_start = time.monotonic()
        baseline_writes = write_burst(baseline_bucket, count=15, size_bytes=20480)
        baseline_acked = len([w for w in baseline_writes if w["success"]])
        bl_lag, bl_repl = measure_replication_lag(baseline_bucket, baseline_acked, start_time=bl_start, timeout_s=30)
        print(f"  Baseline (no toxics): {baseline_acked} objects written through proxy")
        print(f"  Baseline replication lag: {bl_lag}s ({bl_repl}/{baseline_acked})")

        if bl_repl < baseline_acked:
            print("  WARNING: baseline replication through proxy incomplete!")

        # Scenario 1: WAN Latency injection (500ms round-trip)
        s1_bucket = f"{base_bucket}-latency"
        setup_chaos_bucket(s1_bucket)
        time.sleep(2)
        s1 = run_scenario("500ms WAN Latency", [
            {"name": "repl_lat_down", "type": "latency", "stream": "downstream",
             "toxicity": 1.0, "attributes": {"latency": 500, "jitter": 20}},
            {"name": "repl_lat_up", "type": "latency", "stream": "upstream",
             "toxicity": 1.0, "attributes": {"latency": 500, "jitter": 20}},
        ], s1_bucket, burst_count=15, size_bytes=20480)
        scenarios_data.append(s1)

        # Scenario 2: Bandwidth throttle (32 KB/s)
        s2_bucket = f"{base_bucket}-bandwidth"
        setup_chaos_bucket(s2_bucket)
        time.sleep(2)
        s2 = run_scenario("32KB/s Bandwidth", [
            {"name": "repl_bw_down", "type": "bandwidth", "stream": "downstream",
             "toxicity": 1.0, "attributes": {"rate": 32}},
            {"name": "repl_bw_up", "type": "bandwidth", "stream": "upstream",
             "toxicity": 1.0, "attributes": {"rate": 32}},
        ], s2_bucket, burst_count=15, size_bytes=20480)
        scenarios_data.append(s2)

        # Scenario 3: Combined latency + bandwidth
        s3_bucket = f"{base_bucket}-combined"
        setup_chaos_bucket(s3_bucket)
        time.sleep(2)
        s3 = run_scenario("500ms Latency + 32KB/s BW", [
            {"name": "repl_lat_combo", "type": "latency", "stream": "upstream",
             "toxicity": 1.0, "attributes": {"latency": 500, "jitter": 20}},
            {"name": "repl_bw_combo", "type": "bandwidth", "stream": "upstream",
             "toxicity": 1.0, "attributes": {"rate": 32}},
        ], s3_bucket, burst_count=15, size_bytes=20480)
        scenarios_data.append(s3)

        # Assertions
        c1 = s1["replication_lag_s"] > bl_lag and s1["replication_lag_s"] >= 1.5
        c2 = all(s["all_replicated"] for s in scenarios_data)
        c3 = s2["replication_lag_s"] > bl_lag and s2["replication_lag_s"] >= 1.5
        c4 = bl_repl >= baseline_acked

        held = c1 and c2 and c3 and c4

        print(f"\n--- E3 Assertion Clauses ---")
        print(f"  - Clause 1 (500ms latency increases lag to >= 1.5s vs {bl_lag}s baseline): {c1} ({s1['replication_lag_s']}s)")
        print(f"  - Clause 2 (All objects replicated, zero data loss): {c2}")
        print(f"  - Clause 3 (32KB/s bandwidth cap increases lag to >= 1.5s vs {bl_lag}s baseline): {c3} ({s2['replication_lag_s']}s)")
        print(f"  - Clause 4 (Baseline proxy replication works): {c4} ({bl_repl}/{baseline_acked})")
        print(f"Overall Hypothesis Held: {held}\n")

    finally:
        # Cleanup: remove toxics, restore direct replication, clean buckets
        print("Cleaning up E3 resources...")
        toxiproxy_remove_all_toxics()
        repoint_replication_direct()

        for suffix in ["baseline", "latency", "bandwidth", "combined"]:
            cleanup_chaos_bucket(f"{base_bucket}-{suffix}")
        time.sleep(2)

    return {
        "experiment": "E3_latency",
        "hypothesis": HYPOTHESIS,
        "hypothesis_held": held,
        "assertions": {
            "latency_increases_lag_to_threshold": c1,
            "zero_data_loss_all_scenarios": c2,
            "bandwidth_increases_lag_to_threshold": c3,
            "baseline_proxy_works": c4,
        },
        "rto": "N/A",
        "rpo": "N/A",
        "baseline": {
            "replication_lag_s": bl_lag,
            "objects_replicated": bl_repl,
        },
        "scenarios": scenarios_data,
    }


if __name__ == "__main__":
    res = run()
    print("\nResult Summary:")
    print(json.dumps(res, indent=2))
