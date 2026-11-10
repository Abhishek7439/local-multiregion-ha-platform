# M5 Evidence — Chaos Engineering & Resilience Under Stress

**Execution Date**: `2026-11-10 09:48:25 UTC`  
**Project**: `setu-multiregion`  
**Baseline Pre-Check Integrity**: `match: True` (count: 126)  
**Post-Suite Integrity**: `match: True` (count: 127)  
**Ephemeral Failover Probes Cleaned**: `6` (`['rto-20261110T094455Z.txt', 'rto-20261110T094528Z.txt', 'rto-20261110T094602Z.txt', 'rto-20261110T094641Z.txt', 'rto-20261110T094708Z.txt', 'rto-20261110T094739Z.txt']`)  

## Summary of Experiments

| ID | Experiment | Hypothesis Held? | RTO (min / med / max) | RPO_failover | RPO_after_return | Primary Mechanism |
|:---|:---|:---:|:---:|:---:|:---:|:---|
| `E1_kill` | **E1: Abrupt Crash (SIGKILL)** | **PASS (Held)** | `4702 / 4721 / 4754 ms` | `0 obj` | `0 obj` | HAProxy health check failover to minio-b under concurrent writes |
| `E2_pause` | **E2: Gray Failure (docker pause)** | **PASS (Held)** | `3632 / 3647 / 7208 ms` | `0 obj` | `0 obj` | Socket freeze, client timeout/redispatch to minio-b |
| `E5_gitops_chaos` | **E5: Chaos During GitOps Deploy** | **PASS (Held)** | `N/A` | `N/A` | `N/A` | Active health gate failure & automated rollback to last_good |

---

## Detailed Experiment Logs

### E1_kill

**Hypothesis**:
> *"Under concurrent client write load (~30-50 req/s), executing abrupt SIGKILL on minio-a triggers HAProxy failover with first successful write on minio-b within 10,000 ms (RTO <= 10s), zero true data loss after recovery (RPO_after_return == 0), and all pre-failover writes accounted for."*

- **Hypothesis Result**: `HELD`
- **Explicit Falsifiable Assertions**:
  - `rto_within_10s`: `True`
  - `zero_true_data_loss`: `True`
  - `sustained_load_rate`: `True`
  - `pre_failover_acked_positive`: `True`
- **Measured RTO Across Iterations**:
  - Min RTO: `4702 ms`
  - Median RTO: `4721 ms`
  - Max RTO: `4754 ms`
  - Client Timeout Impact: In concurrent writes, client request timeout determines whether in-flight requests fail or succeed during backend transition.
- **Load Level**: Sustained `36.1 req/s` (5 concurrent worker threads)
- **RPO_failover**: `0 objects` missing on Region B at failover instant.
- **RPO_after_return**: `0 objects` lost permanently across the platform.
  *(Note: Region A disk volume survived, so this measures replication resync completeness, not physical disk wipe).*

**Iteration Breakdown**:
- Iteration 1: RTO = `4721 ms`, Load = `36.2 req/s`, Pre-chaos acked = `180`, Acked on B = `216`, Failed = `4`, RPO_failover = `0`, RPO_after_return = `0`
- Iteration 2: RTO = `4754 ms`, Load = `36.3 req/s`, Pre-chaos acked = `184`, Acked on B = `216`, Failed = `8`, RPO_failover = `0`, RPO_after_return = `0`
- Iteration 3: RTO = `4702 ms`, Load = `35.9 req/s`, Pre-chaos acked = `180`, Acked on B = `212`, Failed = `4`, RPO_failover = `0`, RPO_after_return = `0`

```json
{
  "experiment": "E1_kill",
  "hypothesis": "Under concurrent client write load (~30-50 req/s), executing abrupt SIGKILL on minio-a triggers HAProxy failover with first successful write on minio-b within 10,000 ms (RTO <= 10s), zero true data loss after recovery (RPO_after_return == 0), and all pre-failover writes accounted for.",
  "hypothesis_held": true,
  "assertions": {
    "rto_within_10s": true,
    "zero_true_data_loss": true,
    "sustained_load_rate": true,
    "pre_failover_acked_positive": true
  },
  "rto_ms": 4721,
  "rto_min_ms": 4702,
  "rto_median_ms": 4721,
  "rto_max_ms": 4754,
  "rpo_failover": 0,
  "rpo_after_return": 0,
  "avg_write_rate_req_sec": 36.1,
  "iterations": [
    {
      "iteration": 1,
      "rto_ms": 4721,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 408,
      "write_rate_req_sec": 36.2,
      "acked_before_kill": 180,
      "in_flight_at_kill": 0,
      "acked_on_b": 216,
      "failed_requests": 4,
      "failback_ok": true
    },
    {
      "iteration": 2,
      "rto_ms": 4754,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 412,
      "write_rate_req_sec": 36.3,
      "acked_before_kill": 184,
      "in_flight_at_kill": 0,
      "acked_on_b": 216,
      "failed_requests": 8,
      "failback_ok": true
    },
    {
      "iteration": 3,
      "rto_ms": 4702,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 404,
      "write_rate_req_sec": 35.9,
      "acked_before_kill": 180,
      "in_flight_at_kill": 4,
      "acked_on_b": 212,
      "failed_requests": 4,
      "failback_ok": true
    }
  ]
}
```

### E2_pause

**Hypothesis**:
> *"Under concurrent client write load (~30-50 req/s), executing docker pause on minio-a freezes container sockets without TCP RST. In-flight requests to A time out and HAProxy failover routes traffic to minio-b with first successful write within 10,000 ms (RTO <= 10s). Unpausing minio-a restores two-way consistency with zero true data loss (RPO_after_return == 0)."*

- **Hypothesis Result**: `HELD`
- **Explicit Falsifiable Assertions**:
  - `rto_within_10s`: `True`
  - `zero_true_data_loss`: `True`
  - `sustained_load_rate`: `True`
  - `pre_failover_acked_positive`: `True`
- **Measured RTO Across Iterations**:
  - Min RTO: `3632 ms`
  - Median RTO: `3647 ms`
  - Max RTO: `7208 ms`
  - Client Timeout Impact: In concurrent writes, client request timeout determines whether in-flight requests fail or succeed during backend transition.
- **Load Level**: Sustained `35.9 req/s` (5 concurrent worker threads)
- **RPO_failover**: `0 objects` missing on Region B at failover instant.
- **RPO_after_return**: `0 objects` lost permanently across the platform.
  *(Note: Region A disk volume survived, so this measures replication resync completeness, not physical disk wipe).*

**Iteration Breakdown**:
- Iteration 1: RTO = `3632 ms`, Load = `39.3 req/s`, Pre-chaos acked = `180`, Acked on B = `212`, Failed = `4`, RPO_failover = `0`, RPO_after_return = `0`
- Iteration 2: RTO = `7208 ms`, Load = `29.3 req/s`, Pre-chaos acked = `180`, Acked on B = `212`, Failed = `8`, RPO_failover = `0`, RPO_after_return = `0`
- Iteration 3: RTO = `3647 ms`, Load = `39.2 req/s`, Pre-chaos acked = `177`, Acked on B = `214`, Failed = `4`, RPO_failover = `0`, RPO_after_return = `0`

```json
{
  "experiment": "E2_pause",
  "hypothesis": "Under concurrent client write load (~30-50 req/s), executing docker pause on minio-a freezes container sockets without TCP RST. In-flight requests to A time out and HAProxy failover routes traffic to minio-b with first successful write within 10,000 ms (RTO <= 10s). Unpausing minio-a restores two-way consistency with zero true data loss (RPO_after_return == 0).",
  "hypothesis_held": true,
  "assertions": {
    "rto_within_10s": true,
    "zero_true_data_loss": true,
    "sustained_load_rate": true,
    "pre_failover_acked_positive": true
  },
  "rto_ms": 3647,
  "rto_min_ms": 3632,
  "rto_median_ms": 3647,
  "rto_max_ms": 7208,
  "rpo_failover": 0,
  "rpo_after_return": 0,
  "avg_write_rate_req_sec": 35.9,
  "iterations": [
    {
      "iteration": 1,
      "rto_ms": 3632,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 400,
      "write_rate_req_sec": 39.3,
      "acked_before_pause": 180,
      "in_flight_at_pause": 2,
      "acked_on_b": 212,
      "failed_requests": 4,
      "failback_ok": true
    },
    {
      "iteration": 2,
      "rto_ms": 7208,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 404,
      "write_rate_req_sec": 29.3,
      "acked_before_pause": 180,
      "in_flight_at_pause": 0,
      "acked_on_b": 212,
      "failed_requests": 8,
      "failback_ok": true
    },
    {
      "iteration": 3,
      "rto_ms": 3647,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 400,
      "write_rate_req_sec": 39.2,
      "acked_before_pause": 177,
      "in_flight_at_pause": 1,
      "acked_on_b": 214,
      "failed_requests": 4,
      "failback_ok": true
    }
  ]
}
```

### E5_gitops_chaos

**Hypothesis**:
> *"If a failure is injected during active GitOps continuous reconciliation (terminating the gateway container while the reconciler is evaluating its post-apply health gate), the reconciler will detect the health gate failure, automatically execute rollback to last_good, recreate affected containers, restore platform health, and persist the bad commit in bad_commits, without human intervention. (RTO/RPO: N/A)."*

- **Hypothesis Result**: `HELD`
- **Explicit Falsifiable Assertions**:
  - `gateway_killed_mid_gate`: `True`
  - `reconciler_triggered_rollback`: `True`
  - `rollback_within_35s`: `True`
  - `bad_commit_recorded`: `True`
  - `gateway_restored_healthy`: `True`
- **Deployment Rollback Metrics**:
  - Candidate Commit: `49b1d1d`
  - Rolled Back To: `00a85b9`
  - Rollback Duration: `16s`
  - Bad Commit Persisted: `True`
  - Gateway Restored: `True`

```json
{
  "experiment": "E5_gitops_chaos",
  "hypothesis": "If a failure is injected during active GitOps continuous reconciliation (terminating the gateway container while the reconciler is evaluating its post-apply health gate), the reconciler will detect the health gate failure, automatically execute rollback to last_good, recreate affected containers, restore platform health, and persist the bad commit in bad_commits, without human intervention. (RTO/RPO: N/A).",
  "hypothesis_held": true,
  "assertions": {
    "gateway_killed_mid_gate": true,
    "reconciler_triggered_rollback": true,
    "rollback_within_35s": true,
    "bad_commit_recorded": true,
    "gateway_restored_healthy": true
  },
  "rto": "N/A",
  "rpo": "N/A",
  "candidate_commit": "49b1d1de33b6a7f32a64ab21b7b43d15d87276e1",
  "rolled_back_to": "00a85b9b431fe1f85fd14fcc9bf755e959ba59e1",
  "rollback_time_seconds": 16,
  "bad_commit_recorded": true,
  "gateway_restored": true
}
```
