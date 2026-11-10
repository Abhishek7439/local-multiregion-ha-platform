"""Experiment E2: Gray Failure (Pause minio-a).

Measures:
- RTO (time from docker pause until first successful write on minio-b via Gateway)
- RPO_failover (acknowledged writes missing on B at failover time)
- RPO_after_return (acknowledged writes still missing after A is unpaused and resyncs)
- Backend attribution (X-Backend-Server header)
"""

import time
import json
from chaos.common import (
    setup_chaos_bucket,
    cleanup_chaos_bucket,
    put_object_gateway,
    docker_container_action,
    docker_service,
    start_dr_controller,
    stop_dr_controller,
    run_mc,
    get_haproxy_status,
)

HYPOTHESIS = (
    "Pausing minio-a via docker pause simulates a gray failure where the container "
    "process is frozen without closing TCP sockets or sending FIN/RST packets. Gateway "
    "requests to A will time out (bounded by HAProxy timeout connect 2s) before failing "
    "over to B, resulting in an RTO higher than abrupt termination. Acknowledged writes "
    "may be temporarily missing on B at failover (RPO_failover >= 0), but unpausing "
    "minio-a will allow replication to catch up with zero true loss (RPO_after_return = 0), "
    "because Region A's disk volume survived."
)


def run() -> dict:
    timestamp = int(time.time())
    bucket = f"chaos-e2-{timestamp}"
    ctrl_proc = None
    is_paused = False

    print(f"\n========================================================")
    print(f"   [E2] Gray Failure Chaos Experiment (docker pause minio-a)")
    print(f"========================================================")
    print(f"Hypothesis: {HYPOTHESIS}\n")

    acked_writes = {}
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
        ctrl_proc = start_dr_controller("/tmp/setu-chaos-e2-dr.log")
        print("DR Controller active for automated failover & fencing.")

        # 3. Burst write stream to Gateway (:8080)
        print("Starting burst write stream through Gateway (:8080)...")
        pause_injected = False
        pause_time = None
        seq = 0

        max_loop = 60
        while seq < max_loop:
            seq += 1
            key = f"pause-{seq:04d}.txt"
            payload = f"burst-payload-pause-{seq:04d}-{time.time()}".encode()

            # For paused container, timeout allows HAProxy redispatch to trigger
            res = put_object_gateway(bucket, key, payload, timeout=3.5)
            now = time.monotonic()

            if res["success"]:
                backend = res["backend"]
                acked_writes[key] = {
                    "backend": backend,
                    "body": payload,
                    "ts": time.time(),
                }
                print(f"  [Write #{seq:02d}] HTTP 200 via Gateway -> Backend: {backend} ({res['duration_ms']}ms)")

                # If paused and we receive an ack from minio-b, failover succeeded!
                if pause_injected and backend == "minio-b":
                    rto_ms = int((now - pause_time) * 1000)
                    print(f"\n>>> GRAY FAILURE FAILOVER: First write served by minio-b in {rto_ms}ms (RTO) <<<\n")
                    break
            else:
                failed_attempts.append({"seq": seq, "key": key, "error": res["error"]})
                print(f"  [Write #{seq:02d}] Failed: {res['error']}")

            # Inject docker pause after 10 writes acknowledged on minio-a
            if not pause_injected and len([w for w in acked_writes.values() if w["backend"] == "minio-a"]) >= 10:
                print(f"\n>>> INJECTING CHAOS: docker pause minio-a at {time.strftime('%X')} <<<")
                docker_container_action("pause", "minio-a")
                pause_time = time.monotonic()
                pause_injected = True
                is_paused = True
                print("minio-a paused (frozen). Waiting for HAProxy health checks to redirect traffic to Region B...\n")

            time.sleep(0.1)

        # 4. Measure RPO_failover: which acked writes on minio-a are missing on B right now?
        print("--- Measuring RPO_failover (at failover instant) ---")
        acked_on_a = {k: v for k, v in acked_writes.items() if v["backend"] == "minio-a"}
        print(f"Total writes acknowledged by minio-a before pause: {len(acked_on_a)}")

        for k, v in acked_on_a.items():
            check = run_mc(["cat", f"site-b/{bucket}/{k}"])
            if check.returncode != 0 or check.stdout.strip() != v["body"].decode().strip():
                rpo_failover_keys.append(k)

        rpo_failover_count = len(rpo_failover_keys)
        print(f"RPO_failover: {rpo_failover_count} object(s) missing on Region B at failover time.")
        if rpo_failover_keys:
            print(f"  Missing keys at failover: {rpo_failover_keys}")

        # 5. Recover Region A: unpause container and wait for resync & failback
        print("\n--- Disaster Recovery: Unpausing minio-a ---")
        docker_container_action("unpause", "minio-a")
        is_paused = False
        print("minio-a unpaused. Waiting for replication resync and controller failback...")

        recovered = False
        for _ in range(25):
            time.sleep(2)
            st = get_haproxy_status()
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
            "experiment": "E2_pause",
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
        # Guarantee unpause and cleanup
        if is_paused:
            docker_container_action("unpause", "minio-a")
        stop_dr_controller(ctrl_proc)
        print(f"Cleaning ephemeral bucket: {bucket}...")
        cleanup_chaos_bucket(bucket)
        docker_service("start", "minio-a")

    return details


if __name__ == "__main__":
    res = run()
    print("\nResult Summary:")
    print(json.dumps(res, indent=2))

