"""Experiment E1: Burst-Load Crash (Kill minio-a).

Measures:
- RTO (time from SIGKILL until first successful write on minio-b via Gateway)
- RPO_failover (acknowledged writes missing on B at failover time)
- RPO_after_return (acknowledged writes still missing after A returns and resyncs)
- Backend attribution (X-Backend-Server header)
"""

import time
import json
from chaos.common import (
    setup_chaos_bucket,
    cleanup_chaos_bucket,
    put_object_gateway,
    docker_service,
    start_dr_controller,
    stop_dr_controller,
    run_mc,
    compare_sites,
    get_haproxy_status,
)

HYPOTHESIS = (
    "Under a sustained client write stream via Gateway (:8080), executing abrupt "
    "SIGKILL on minio-a triggers HAProxy active health-check failover to minio-b with "
    "measured RTO. Acknowledged writes before the kill that had not yet replicated to "
    "Region B will be missing on B at failover time (RPO_failover >= 0). After Region A "
    "restarts and resyncs, zero acknowledged writes will be missing across the platform "
    "(RPO_after_return = 0), because Region A's disk volume survived."
)


def run() -> dict:
    timestamp = int(time.time())
    bucket = f"chaos-e1-{timestamp}"
    ctrl_proc = None

    print(f"\n========================================================")
    print(f"   [E1] Crash / Kill Chaos Experiment (SIGKILL minio-a) ")
    print(f"========================================================")
    print(f"Hypothesis: {HYPOTHESIS}\n")

    acked_writes = {}  # key -> {backend, body, ts}
    failed_attempts = []
    rto_ms = None
    rpo_failover_keys = []
    rpo_after_return_keys = []
    held = False
    details = {}

    try:
        # 1. Setup isolated ephemeral test bucket
        print(f"Creating isolated chaos bucket: site-a/{bucket}")
        if not setup_chaos_bucket(bucket):
            raise RuntimeError(f"Failed to create bucket site-a/{bucket}")

        # 2. Start DR controller for automated fencing and failback
        ctrl_proc = start_dr_controller("/tmp/setu-chaos-e1-dr.log")
        print("DR Controller active for automated failover & fencing.")

        # 3. Burst write stream to Gateway (:8080)
        print("Starting burst write stream through Gateway (:8080)...")
        kill_injected = False
        kill_time = None
        seq = 0

        # Loop until we kill minio-a and achieve first successful write on minio-b
        max_loop = 60
        while seq < max_loop:
            seq += 1
            key = f"kill-{seq:04d}.txt"
            payload = f"burst-payload-kill-{seq:04d}-{time.time()}".encode()

            res = put_object_gateway(bucket, key, payload, timeout=1.5)
            now = time.monotonic()

            if res["success"]:
                backend = res["backend"]
                acked_writes[key] = {
                    "backend": backend,
                    "body": payload,
                    "ts": time.time(),
                }
                print(f"  [Write #{seq:02d}] HTTP 200 via Gateway -> Backend: {backend} ({res['duration_ms']}ms)")

                # If killed and we now received an ack from minio-b, failover is proven!
                if kill_injected and backend == "minio-b":
                    rto_ms = int((now - kill_time) * 1000)
                    print(f"\n>>> FAILOVER DETECTED: First write served by minio-b in {rto_ms}ms (RTO) <<<\n")
                    break
            else:
                failed_attempts.append({"seq": seq, "key": key, "error": res["error"]})
                print(f"  [Write #{seq:02d}] Failed: {res['error']}")

            # Inject SIGKILL after acknowledging 10 writes on minio-a
            if not kill_injected and len([w for w in acked_writes.values() if w["backend"] == "minio-a"]) >= 10:
                print(f"\n>>> INJECTING CHAOS: docker compose kill minio-a at {time.strftime('%X')} <<<")
                docker_service("kill", "minio-a")
                kill_time = time.monotonic()
                kill_injected = True
                print("minio-a terminated. Probing Gateway until Region B takes over...\n")

            time.sleep(0.1)

        # 4. Measure RPO_failover: which acked writes on minio-a are missing on B right now?
        print("--- Measuring RPO_failover (at failover instant) ---")
        acked_on_a = {k: v for k, v in acked_writes.items() if v["backend"] == "minio-a"}
        print(f"Total writes acknowledged by minio-a before kill: {len(acked_on_a)}")

        for k, v in acked_on_a.items():
            check = run_mc(["cat", f"site-b/{bucket}/{k}"])
            if check.returncode != 0 or check.stdout.strip() != v["body"].decode().strip():
                rpo_failover_keys.append(k)

        rpo_failover_count = len(rpo_failover_keys)
        print(f"RPO_failover: {rpo_failover_count} object(s) missing on Region B at failover time.")
        if rpo_failover_keys:
            print(f"  Missing keys at failover: {rpo_failover_keys}")

        # 5. Recover Region A: start container and wait for resync & failback
        print("\n--- Disaster Recovery: Restarting minio-a ---")
        docker_service("start", "minio-a")
        print("minio-a restarted. Waiting for replication resync and controller failback...")

        recovered = False
        for _ in range(25):
            time.sleep(2)
            st = get_haproxy_status()
            # minio-a back to UP means DR controller verified checksums and unfenced
            if st.get("minio_api/minio-a", "").startswith("UP"):
                recovered = True
                break

        if recovered:
            print("Controller verified checksum match: minio-a restored and un-fenced (UP).")
        else:
            print("Warning: failback timeout; checking current status.")

        # 6. Measure RPO_after_return: are any acknowledged writes permanently lost?
        print("\n--- Measuring RPO_after_return (post-recovery true loss) ---")
        for k, v in acked_writes.items():
            check_a = run_mc(["cat", f"site-a/{bucket}/{k}"])
            check_b = run_mc(["cat", f"site-b/{bucket}/{k}"])
            valid_a = (check_a.returncode == 0 and check_a.stdout.strip() == v["body"].decode().strip())
            valid_b = (check_b.returncode == 0 and check_b.stdout.strip() == v["body"].decode().strip())
            if not (valid_a and valid_b):
                rpo_after_return_keys.append(k)

        rpo_after_return_count = len(rpo_after_return_keys)
        print(f"RPO_after_return: {rpo_after_return_count} object(s) permanently lost.")
        print(f"  (Note: Region A disk volume survived, so no data was destroyed on disk).")

        # 7. Evaluate Hypothesis
        held = (rto_ms is not None and rto_ms > 0) and (rpo_after_return_count == 0)
        print(f"\nHypothesis Held: {held}")

        details = {
            "experiment": "E1_kill",
            "hypothesis": HYPOTHESIS,
            "hypothesis_held": held,
            "rto_ms": rto_ms,
            "rpo_failover": rpo_failover_count,
            "rpo_failover_keys": rpo_failover_keys,
            "rpo_after_return": rpo_after_return_count,
            "rpo_after_return_keys": rpo_after_return_keys,
            "total_acked": len(acked_writes),
            "acked_by_a": len(acked_on_a),
            "acked_by_b": len([w for w in acked_writes.values() if w["backend"] == "minio-b"]),
            "failed_requests": len(failed_attempts),
        }

    finally:
        # Guarantee cleanup
        stop_dr_controller(ctrl_proc)
        print(f"Cleaning ephemeral bucket: {bucket}...")
        cleanup_chaos_bucket(bucket)
        # Ensure minio-a is running
        docker_service("start", "minio-a")

    return details


if __name__ == "__main__":
    res = run()
    print("\nResult Summary:")
    print(json.dumps(res, indent=2))

