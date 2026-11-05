# M3 evidence — fencing, checksum failback, and RPO measurement (2026-11-05)

> **Acceptance Test AT4 Definition (PROJECT_CONTEXT.md Section 6):**  
> *"AT4 A restart: automatic resync, checksums match."*

Commands were run in Ubuntu (`/home/cloud_automator/setu-starter`) on Docker Engine 29.9.2.

---

## 1. Fencing and Failover (Phase 2A)

When Region A (`minio-a`) is stopped, the DR controller (`controller/dr_controller.py`) detects health check failure, waits for the configured 3-second grace window, enters `FAILOVER`, fences `minio-a` on the HAProxy gateway via its admin socket, and performs a test write through the gateway.

### Controller Log:
```json
{"event": "start", "state": "HEALTHY", "grace_seconds": 3, "ts": "2026-11-05T14:58:48Z"}
{"event": "transition", "from": "HEALTHY", "to": "DEGRADED", "region_a": "DOWN", "region_b": "UP", "reason": "region A health failed", "ts": "2026-11-05T14:58:51Z"}
{"event": "transition", "from": "DEGRADED", "to": "FAILOVER", "reason": "region A still down after the grace window", "ts": "2026-11-05T14:58:54Z"}
{"event": "fence", "server": "minio-a", "action": "disable", "reply": "", "ts": "2026-11-05T14:58:54Z"}
{"event": "rto", "milliseconds": 3396, "write_attempt": 1, "write_ms": 388, "object": "gw/demo/rto-20261105T145854Z.txt", "region_b": "UP", "ts": "2026-11-05T14:58:54Z"}
```

### HAProxy Stat Check during FAILOVER:
```
# Query: show stat on TCP 127.0.0.1:9999
minio_api,minio-a,MAINT (resolution)
```
`minio-a` is confirmed fenced (`MAINT`) so no incoming client traffic can hit a half-dead or flapping primary.

---

## 2. Integrity Verification and Automatic Failback (Phase 2B & AT4)

When Region A restarts (`docker compose start minio-a`), the controller detects Region A is live and transitions from `FAILOVER` to `RECOVERING`. It refuses to fail back until SHA-256 checksums of every object on Region A and Region B match.

### Controller Log during Recovery:
```json
{"event": "transition", "from": "FAILOVER", "to": "RECOVERING", "reason": "region A is live again; checksums must match before FAILBACK", "ts": "2026-11-05T14:59:03Z"}
{"event": "checksum", "match": false, "count_a": 25, "count_b": 26, "only_a": [], "only_b": ["demo/rto-20261105T145854Z.txt"], "different": [], "ts": "2026-11-05T14:59:23Z"}
{"event": "checksum", "match": true, "count_a": 26, "count_b": 26, "only_a": [], "only_b": [], "different": [], "ts": "2026-11-05T14:59:44Z"}
{"event": "transition", "from": "RECOVERING", "to": "FAILBACK", "reason": "checksums match, so Region A may take traffic again", "reply": "", "ts": "2026-11-05T14:59:44Z"}
{"event": "transition", "from": "FAILBACK", "to": "HEALTHY", "reason": "failback complete", "ts": "2026-11-05T14:59:44Z"}
```

### Observations:
1. **Defensive hold in RECOVERING**: At 14:59:23Z, object `rto-20261105T145854Z.txt` written during the outage to Region B had not yet completed replication to Region A. The controller logged `match: false` and kept `minio-a` fenced.
2. **Reconciliation**: MinIO site replication automatically caught up. At 14:59:44Z, both sites showed 26 objects with identical SHA-256 hashes (`match: true`).
3. **Unfencing and Failback**: The controller un-fenced `minio-a` (`enable server minio_api/minio-a`) and returned to `HEALTHY`.
4. **HAProxy Stat Check after FAILBACK**:
   ```
   minio_api,minio-a,UP
   ```
5. **Execution Scaling & Blocking Behavior**:
   At ~26 objects per site (52 objects total), `compare_sites()` took **18.92 seconds** to list objects and read each SHA-256 hash via individual `mc cat` container invocations. Because `compare_sites()` runs synchronously, the controller event loop blocks for the entire ~19-second execution duration; runtime scales linearly $O(N)$ with total object count across both sites.

---

## 3. Negative / Divergence Handling (Phase 2C)

Direct writes to Region B during Region A downtime were tested:
1. Region A stopped.
2. Object `demo/neg-test.txt` piped directly to `site-b`.
3. Region A restarted.
4. The controller maintained `RECOVERING` until MinIO active-active site replication caught up and reconciled the object.
5. Verifying content on Region A after failback:
   ```
   $ ./scripts/mc.sh cat site-a/demo/neg-test.txt
   direct-to-b at 2026-11-05T15:02:47Z
   ```

---

## 4. RPO Measurement — Graceful Stop vs Hard Kill (Phase 2D)

Measured using `python3 controller/proof.py`.
The test writes a sequential stream of numbered objects directly to Region A and halts Region A mid-stream. RPO is defined as the count of acknowledged writes made to A that failed to replicate to B before A crashed.

Both shutdown mechanisms were measured with tagged distinct buckets:
1. **Graceful Stop (`docker compose stop minio-a`)**: sends `SIGTERM`, allows container stop timeout.
2. **Hard Kill (`docker compose kill minio-a`)**: sends `SIGKILL`, abrupt termination.

### Command Output:
```json
{
  "graceful_stop": {
    "mode": "graceful_stop",
    "tag": "stop-1793898355",
    "acked": 12,
    "missing": [],
    "rpo_objects": 0,
    "stopped_region_a": true,
    "stop_ms": 5611
  },
  "kill": {
    "mode": "kill",
    "tag": "kill-1793898374",
    "acked": 12,
    "missing": [],
    "rpo_objects": 0,
    "stopped_region_a": true,
    "stop_ms": 6451
  }
}
```

### Analysis and Engineering Trade-off:
rpo_objects 0 for graceful stop and SIGKILL, measured with sequential writes ~400 ms apart. NOT measured under burst/concurrent load; async replication lag under load is untested and RPO must not be assumed 0.

---

## 5. Failure Modes, Known Limits, and Open Items

1. **RPO Under Burst Load**:
   Untested. Sequential writes allow replication to keep up over local bridge networking. Under concurrent client writes or injected cross-region network latency (M5), acknowledged writes in flight or in local buffers at `SIGKILL` may be lost, producing non-zero RPO.
2. **Permanent Divergence in RECOVERING**:
   If an object exists only on A or has conflicting contents that active-active replication cannot reconcile, `compare_sites()` returns `match: false`. The controller has no timeout or alert mechanism; it remains in `RECOVERING` indefinitely, keeping Region A fenced in `MAINT`. Traffic fails safe by remaining pinned to Region B.
3. **Controller Restart During FAILOVER**:
   Tested live: if the controller is killed while Region A is fenced in `MAINT`, and a new controller starts after Region A is running, the new controller initializes in `HEALTHY` and does not check HAProxy's internal server state. Consequently, `minio-a` remains in `MAINT` in HAProxy (failing safe with traffic on Region B) until manually unfenced or cycled through another failover.
