"""Experiment E4: Asymmetric Network Partition & Conflict Resolution.

Simulates a network partition where site-a cannot replicate to site-b
(via Toxiproxy timeout toxic), while both sites remain individually healthy.
Writes are made to both sites independently during the partition.
After the partition heals, we observe MinIO's conflict resolution behavior.

RTO/RPO: N/A (partition, not outage). Reports:
  - Catch-up time after heal (time for inventories to converge).
  - Whether any writes are lost or duplicated.
  - Which version wins when the same key is written on both sides.
"""

import sys
import time
import json
import hashlib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from chaos.common import (
    setup_chaos_bucket,
    cleanup_chaos_bucket,
    put_object_gateway,
    get_bucket_inventory,
    sign_s3_headers,
    run_mc,
    get_credentials,
    toxiproxy_ensure_proxy,
    toxiproxy_add_toxic,
    toxiproxy_remove_all_toxics,
    toxiproxy_delete_proxy,
    repoint_replication_through_proxy,
    repoint_replication_direct,
)
import urllib.request
import urllib.error

HYPOTHESIS = (
    "During an asymmetric network partition (A cannot reach B via Toxiproxy timeout), "
    "writes to site-a are acknowledged but not replicated. After the partition heals "
    "(toxic removed), site-a's writes catch up to site-b within 60 seconds. "
    "For conflict keys (same key written on both sides), MinIO's last-write-wins "
    "resolution preserves exactly one version on both sites (no data loss for "
    "non-conflicting keys)."
)


def put_object_direct(host: str, port: int, bucket: str, key: str,
                      body: bytes, timeout: float = 5.0) -> dict:
    """Send an authenticated S3 PUT directly to a MinIO region (bypassing gateway)."""
    host_header = f"127.0.0.1:{port}"
    headers = sign_s3_headers(bucket, key, body, host=host_header)
    url = f"http://127.0.0.1:{port}/{bucket}/{key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="PUT")
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            end = time.monotonic()
            return {"success": True, "status": resp.status,
                    "duration_ms": int((end - start) * 1000), "error": None}
    except Exception as e:
        end = time.monotonic()
        return {"success": False, "status": 0,
                "duration_ms": int((end - start) * 1000), "error": str(e)}


def get_object_sha256(alias_path: str) -> str | None:
    """Get SHA-256 of an object via mc cat piped to sha256sum."""
    res = run_mc(["cat", alias_path], timeout=10)
    if res.returncode != 0:
        return None
    return hashlib.sha256(res.stdout.encode("latin-1")).hexdigest()


def run() -> dict:
    print(f"\n========================================================")
    print(f"   [E4] Asymmetric Network Partition Experiment         ")
    print(f"========================================================")
    print(f"Hypothesis: {HYPOTHESIS}\n")

    timestamp = int(time.time())
    bucket = f"chaos-e4-{timestamp}"

    # Track all variables for the finally/return blocks
    partition_writes_a = []
    partition_writes_b = []
    conflict_results = []
    catch_up_time_s = None
    c1 = c2 = c3 = c4 = c5 = False
    held = False

    try:
        # 1. Setup Toxiproxy and re-point replication
        print("Setting up Toxiproxy and re-pointing replication...")
        toxiproxy_ensure_proxy()
        assert repoint_replication_through_proxy(), "Failed to re-point replication"

        # Create test bucket and verify baseline replication works
        setup_chaos_bucket(bucket)
        time.sleep(3)

        # Write a baseline object and verify it replicates
        baseline_body = b"partition-baseline-check"
        res = put_object_gateway(bucket, "baseline.txt", baseline_body, timeout=5.0)
        assert res["success"], f"Baseline write failed: {res['error']}"
        time.sleep(3)
        b_inv = get_bucket_inventory(f"site-b/{bucket}")
        assert "baseline.txt" in b_inv, "Baseline replication through proxy failed"
        print("  Baseline replication through proxy verified.\n")

        # 2. INJECT PARTITION: timeout toxic blocks A→B replication
        print(">>> INJECTING PARTITION: Adding timeout toxic (A cannot reach B) <<<")
        toxiproxy_add_toxic("minio_b_replication", {
            "name": "partition_block",
            "type": "timeout",
            "stream": "downstream",
            "toxicity": 1.0,
            "attributes": {"timeout": 1}  # 1ms timeout = effectively blocked
        })
        # Also block upstream (B→A responses) for full partition
        toxiproxy_add_toxic("minio_b_replication", {
            "name": "partition_block_up",
            "type": "timeout",
            "stream": "upstream",
            "toxicity": 1.0,
            "attributes": {"timeout": 1}
        })
        partition_start = time.monotonic()
        print("  Partition active. A↔B replication blocked.\n")

        # 3. Write objects to BOTH sides independently during partition
        print("Writing objects during partition...")

        # 3a. Write 10 objects to site-a (via gateway, which routes to minio-a)
        print("  Writing 10 objects to site-a (via gateway)...")
        for i in range(10):
            key = f"partition-a-{i:03d}.txt"
            body = f"written-to-A-during-partition-{i}-{timestamp}".encode()
            res = put_object_gateway(bucket, key, body, timeout=5.0)
            partition_writes_a.append({
                "key": key, "body_sha256": hashlib.sha256(body).hexdigest(),
                "size": len(body), "success": res["success"],
                "side": "A", "error": res.get("error"),
            })

        # 3b. Write 10 objects to site-b (direct, bypassing gateway)
        print("  Writing 10 objects to site-b (direct :9200)...")
        for i in range(10):
            key = f"partition-b-{i:03d}.txt"
            body = f"written-to-B-during-partition-{i}-{timestamp}".encode()
            res = put_object_direct("127.0.0.1", 9200, bucket, key, body)
            partition_writes_b.append({
                "key": key, "body_sha256": hashlib.sha256(body).hexdigest(),
                "size": len(body), "success": res["success"],
                "side": "B", "error": res.get("error"),
            })

        # 3c. Write CONFLICT keys: same key on both sides with different content
        print("  Writing 3 conflict keys (same key, different content on A and B)...")
        for i in range(3):
            key = f"conflict-{i:02d}.txt"
            body_a = f"CONFLICT-version-A-{i}-{timestamp}".encode()
            body_b = f"CONFLICT-version-B-{i}-{timestamp}".encode()
            res_a = put_object_gateway(bucket, key, body_a, timeout=5.0)
            res_b = put_object_direct("127.0.0.1", 9200, bucket, key, body_b)
            conflict_results.append({
                "key": key,
                "a_sha256": hashlib.sha256(body_a).hexdigest(),
                "b_sha256": hashlib.sha256(body_b).hexdigest(),
                "a_acked": res_a["success"],
                "b_acked": res_b["success"],
            })

        acked_a = [w for w in partition_writes_a if w["success"]]
        acked_b = [w for w in partition_writes_b if w["success"]]
        print(f"\n  During partition: A acked {len(acked_a)}/10, B acked {len(acked_b)}/10, "
              f"conflicts: {len(conflict_results)}")

        # Verify partition held: A's objects should NOT be on B yet
        time.sleep(2)
        b_inv_during = get_bucket_inventory(f"site-b/{bucket}")
        a_keys_on_b = [w["key"] for w in acked_a if w["key"] in b_inv_during]
        print(f"  Partition verification: {len(a_keys_on_b)} of A's objects on B "
              f"(expect 0 if partition held)")
        partition_held = len(a_keys_on_b) == 0

        partition_duration = round(time.monotonic() - partition_start, 1)
        print(f"  Partition duration: {partition_duration}s\n")

        # 4. HEAL PARTITION: remove toxics
        print(">>> HEALING PARTITION: Removing all toxics <<<")
        toxiproxy_remove_all_toxics("minio_b_replication")
        heal_time = time.monotonic()

        # 5. Wait for catch-up: A's objects appear on B, B's objects appear on A
        print("Waiting for replication catch-up...")
        all_expected_keys = (
            [w["key"] for w in acked_a] +
            [w["key"] for w in acked_b] +
            [c["key"] for c in conflict_results]
        )
        total_expected = len(set(all_expected_keys)) + 1  # +1 for baseline.txt

        caught_up = False
        for attempt in range(1, 121):  # 60s timeout
            time.sleep(0.5)
            a_inv = get_bucket_inventory(f"site-a/{bucket}")
            b_inv = get_bucket_inventory(f"site-b/{bucket}")
            if len(a_inv) >= total_expected and len(b_inv) >= total_expected:
                caught_up = True
                catch_up_time_s = round(time.monotonic() - heal_time, 2)
                print(f"  Catch-up complete in {catch_up_time_s}s "
                      f"(A: {len(a_inv)}, B: {len(b_inv)} objects)")
                break

        if not caught_up:
            catch_up_time_s = round(time.monotonic() - heal_time, 2)
            a_inv = get_bucket_inventory(f"site-a/{bucket}")
            b_inv = get_bucket_inventory(f"site-b/{bucket}")
            print(f"  Catch-up INCOMPLETE after {catch_up_time_s}s "
                  f"(A: {len(a_inv)}, B: {len(b_inv)}, expected: {total_expected})")

        # 6. Verify non-conflicting writes
        a_inv_final = get_bucket_inventory(f"site-a/{bucket}")
        b_inv_final = get_bucket_inventory(f"site-b/{bucket}")

        missing_a_on_b = [w["key"] for w in acked_a if w["key"] not in b_inv_final]
        missing_b_on_a = [w["key"] for w in acked_b if w["key"] not in a_inv_final]

        print(f"\n  Non-conflict verification:")
        print(f"    A's writes missing on B: {len(missing_a_on_b)} {missing_a_on_b}")
        print(f"    B's writes missing on A: {len(missing_b_on_a)} {missing_b_on_a}")

        # 7. Check conflict resolution
        print(f"\n  Conflict resolution:")
        for c in conflict_results:
            key = c["key"]
            # Read the final content from both sides
            sha_on_a = get_object_sha256(f"site-a/{bucket}/{key}")
            sha_on_b = get_object_sha256(f"site-b/{bucket}/{key}")
            c["final_sha_a"] = sha_on_a
            c["final_sha_b"] = sha_on_b
            c["consistent"] = (sha_on_a == sha_on_b)
            if sha_on_a == c["a_sha256"]:
                c["winner"] = "A"
            elif sha_on_a == c["b_sha256"]:
                c["winner"] = "B"
            else:
                c["winner"] = "unknown"
            print(f"    {key}: winner={c['winner']}, consistent={c['consistent']}")

        # Assertions
        c1 = partition_held  # Partition actually blocked replication
        c2 = len(missing_a_on_b) == 0  # All non-conflict A writes replicated after heal
        c3 = len(missing_b_on_a) == 0  # All non-conflict B writes replicated after heal
        c4 = catch_up_time_s is not None and catch_up_time_s <= 60  # Catch-up within 60s
        c5 = all(c["consistent"] for c in conflict_results)  # Conflict keys consistent

        held = c1 and c2 and c3 and c4 and c5

        print(f"\n--- E4 Assertion Clauses ---")
        print(f"  - Clause 1 (Partition blocked replication): {c1}")
        print(f"  - Clause 2 (A's writes on B after heal): {c2} "
              f"(missing: {len(missing_a_on_b)})")
        print(f"  - Clause 3 (B's writes on A after heal): {c3} "
              f"(missing: {len(missing_b_on_a)})")
        print(f"  - Clause 4 (Catch-up within 60s): {c4} ({catch_up_time_s}s)")
        print(f"  - Clause 5 (Conflict keys consistent across sites): {c5}")
        print(f"Overall Hypothesis Held: {held}\n")

    finally:
        # Cleanup: remove toxics, restore direct replication, remove bucket
        print("Cleaning up E4 resources...")
        toxiproxy_remove_all_toxics()
        repoint_replication_direct()
        cleanup_chaos_bucket(bucket)
        time.sleep(2)

    return {
        "experiment": "E4_partition",
        "hypothesis": HYPOTHESIS,
        "hypothesis_held": held,
        "assertions": {
            "partition_blocked_replication": c1,
            "a_writes_replicated_after_heal": c2,
            "b_writes_replicated_after_heal": c3,
            "catch_up_within_60s": c4,
            "conflict_keys_consistent": c5,
        },
        "rto": "N/A",
        "rpo": "N/A",
        "partition_duration_s": partition_duration,
        "catch_up_time_s": catch_up_time_s,
        "partition_writes_a": len(acked_a),
        "partition_writes_b": len(acked_b),
        "missing_a_on_b_after_heal": missing_a_on_b,
        "missing_b_on_a_after_heal": missing_b_on_a,
        "conflict_resolution": conflict_results,
    }


if __name__ == "__main__":
    res = run()
    print("\nResult Summary:")
    print(json.dumps(res, indent=2))

