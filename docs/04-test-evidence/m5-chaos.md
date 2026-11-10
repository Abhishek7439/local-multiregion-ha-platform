# M5 Evidence — Chaos Engineering & Resilience Under Stress

**Execution Date**: `2026-11-10 10:51:02 UTC`  
**Project**: `setu-multiregion`  
**Baseline Pre-Check Integrity**: `match: True` (count: 136)  
**Post-Suite Integrity**: `match: True` (count: 137)  
**Ephemeral Failover Probes Cleaned**: `6` (`['rto-20261110T104615Z.txt', 'rto-20261110T104648Z.txt', 'rto-20261110T104718Z.txt', 'rto-20261110T104801Z.txt', 'rto-20261110T104833Z.txt', 'rto-20261110T104905Z.txt']`)  

## Summary of Experiments

| ID | Experiment | Hypothesis Held? | RTO (min / med / max) | RPO_failover | RPO_after_return | Primary Mechanism |
|:---|:---|:---:|:---:|:---:|:---:|:---|
| `E1_kill` | **E1: Abrupt Crash (SIGKILL)** | **PASS (Held)** | `2764 / 4732 / 4787 ms` | `0 obj` | `0 obj` | HAProxy health check failover to minio-b under concurrent writes |
| `E2_pause` | **E2: Gray Failure (docker pause)** | **PASS (Held)** | `7169 / 7192 / 7214 ms` | `0 obj` | `0 obj` | Socket freeze, client timeout/redispatch to minio-b |
| `E3_latency` | **E3: WAN Latency & Bandwidth Throttling** | **PASS (Held)** | `N/A` | `N/A` | `N/A` | Toxiproxy latency/bandwidth toxics on replication path |
| `E4_partition` | **E4: Asymmetric Network Partition** | **PASS (Held)** | `N/A` | `N/A` | `N/A` | Toxiproxy timeout toxic blocks A→B; conflict resolution after heal |
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
  - Min RTO: `2764 ms`
  - Median RTO: `4732 ms`
  - Max RTO: `4787 ms`
  - Client Timeout Impact: In concurrent writes, client request timeout determines whether in-flight requests fail or succeed during backend transition.
- **Load Level**: Sustained `37.2 req/s` (5 concurrent worker threads)
- **RPO_failover**: `0 objects` missing on Region B at failover instant.
- **RPO_after_return**: `0 objects` lost permanently across the platform.
  *(Note: Region A disk volume survived, so this measures replication resync completeness, not physical disk wipe).*

**Iteration Breakdown**:
- Iteration 1: RTO = `4787 ms`, Load = `34.5 req/s`, Pre-chaos acked = `172`, Acked on B = `204`, Failed = `4`, RPO_failover = `0`, RPO_after_return = `0`
- Iteration 2: RTO = `2764 ms`, Load = `42.4 req/s`, Pre-chaos acked = `173`, Acked on B = `207`, Failed = `5`, RPO_failover = `0`, RPO_after_return = `0`
- Iteration 3: RTO = `4732 ms`, Load = `34.6 req/s`, Pre-chaos acked = `172`, Acked on B = `207`, Failed = `4`, RPO_failover = `0`, RPO_after_return = `0`

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
  "rto_ms": 4732,
  "rto_min_ms": 2764,
  "rto_median_ms": 4732,
  "rto_max_ms": 4787,
  "rpo_failover": 0,
  "rpo_after_return": 0,
  "avg_write_rate_req_sec": 37.2,
  "iterations": [
    {
      "iteration": 1,
      "rto_ms": 4787,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 392,
      "write_rate_req_sec": 34.5,
      "acked_before_kill": 172,
      "in_flight_at_kill": 0,
      "acked_on_b": 204,
      "failed_requests": 4,
      "failback_ok": true
    },
    {
      "iteration": 2,
      "rto_ms": 2764,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 396,
      "write_rate_req_sec": 42.4,
      "acked_before_kill": 173,
      "in_flight_at_kill": 1,
      "acked_on_b": 207,
      "failed_requests": 5,
      "failback_ok": true
    },
    {
      "iteration": 3,
      "rto_ms": 4732,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 391,
      "write_rate_req_sec": 34.6,
      "acked_before_kill": 172,
      "in_flight_at_kill": 1,
      "acked_on_b": 207,
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
  - Min RTO: `7169 ms`
  - Median RTO: `7192 ms`
  - Max RTO: `7214 ms`
  - Client Timeout Impact: In concurrent writes, client request timeout determines whether in-flight requests fail or succeed during backend transition.
- **Load Level**: Sustained `28.5 req/s` (5 concurrent worker threads)
- **RPO_failover**: `0 objects` missing on Region B at failover instant.
- **RPO_after_return**: `0 objects` lost permanently across the platform.
  *(Note: Region A disk volume survived, so this measures replication resync completeness, not physical disk wipe).*

**Iteration Breakdown**:
- Iteration 1: RTO = `7214 ms`, Load = `28.4 req/s`, Pre-chaos acked = `176`, Acked on B = `204`, Failed = `8`, RPO_failover = `0`, RPO_after_return = `0`
- Iteration 2: RTO = `7192 ms`, Load = `28.7 req/s`, Pre-chaos acked = `175`, Acked on B = `209`, Failed = `8`, RPO_failover = `0`, RPO_after_return = `0`
- Iteration 3: RTO = `7169 ms`, Load = `28.5 req/s`, Pre-chaos acked = `178`, Acked on B = `206`, Failed = `8`, RPO_failover = `0`, RPO_after_return = `0`

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
  "rto_ms": 7192,
  "rto_min_ms": 7169,
  "rto_median_ms": 7192,
  "rto_max_ms": 7214,
  "rpo_failover": 0,
  "rpo_after_return": 0,
  "avg_write_rate_req_sec": 28.5,
  "iterations": [
    {
      "iteration": 1,
      "rto_ms": 7214,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 392,
      "write_rate_req_sec": 28.4,
      "acked_before_pause": 176,
      "in_flight_at_pause": 0,
      "acked_on_b": 204,
      "failed_requests": 8,
      "failback_ok": true
    },
    {
      "iteration": 2,
      "rto_ms": 7192,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 395,
      "write_rate_req_sec": 28.7,
      "acked_before_pause": 175,
      "in_flight_at_pause": 0,
      "acked_on_b": 209,
      "failed_requests": 8,
      "failback_ok": true
    },
    {
      "iteration": 3,
      "rto_ms": 7169,
      "rpo_failover": 0,
      "rpo_failover_keys": [],
      "rpo_after_return": 0,
      "rpo_after_return_keys": [],
      "total_requests": 392,
      "write_rate_req_sec": 28.5,
      "acked_before_pause": 178,
      "in_flight_at_pause": 0,
      "acked_on_b": 206,
      "failed_requests": 8,
      "failback_ok": true
    }
  ]
}
```

### E3_latency

**Hypothesis**:
> *"Injecting 500ms WAN latency or 32KB/s bandwidth constraint on the A↔B replication path increases replication lag measurably (>=1.5s vs <0.8s baseline for a 15-object burst) while maintaining 100% data consistency (zero data loss across all scenarios); after removing toxics and restoring direct replication, both sites remain fully synchronized."*

- **Hypothesis Result**: `HELD`
- **Explicit Falsifiable Assertions**:
  - `latency_increases_lag_to_threshold`: `True`
  - `zero_data_loss_all_scenarios`: `True`
  - `bandwidth_increases_lag_to_threshold`: `True`
  - `baseline_proxy_works`: `True`

**Scenario Breakdown**:
- Baseline (no toxics): lag = `0.73s`, replicated = `15`
- 500ms WAN Latency: lag = `3.05s`, write rate = `83.3 req/s`, replicated = `15/15`
- 32KB/s Bandwidth: lag = `2.39s`, write rate = `125.0 req/s`, replicated = `15/15`
- 500ms Latency + 32KB/s BW: lag = `2.21s`, write rate = `136.4 req/s`, replicated = `15/15`

```json
{
  "experiment": "E3_latency",
  "hypothesis": "Injecting 500ms WAN latency or 32KB/s bandwidth constraint on the A\u2194B replication path increases replication lag measurably (>=1.5s vs <0.8s baseline for a 15-object burst) while maintaining 100% data consistency (zero data loss across all scenarios); after removing toxics and restoring direct replication, both sites remain fully synchronized.",
  "hypothesis_held": true,
  "assertions": {
    "latency_increases_lag_to_threshold": true,
    "zero_data_loss_all_scenarios": true,
    "bandwidth_increases_lag_to_threshold": true,
    "baseline_proxy_works": true
  },
  "rto": "N/A",
  "rpo": "N/A",
  "baseline": {
    "replication_lag_s": 0.73,
    "objects_replicated": 15
  },
  "scenarios": [
    {
      "scenario": "500ms WAN Latency",
      "toxics_applied": [
        "latency",
        "latency"
      ],
      "burst_count": 15,
      "object_size_bytes": 20480,
      "acked": 15,
      "failed": 0,
      "write_duration_s": 0.18,
      "write_rate_req_s": 83.3,
      "replication_lag_s": 3.05,
      "objects_replicated": 15,
      "all_replicated": true
    },
    {
      "scenario": "32KB/s Bandwidth",
      "toxics_applied": [
        "bandwidth",
        "bandwidth"
      ],
      "burst_count": 15,
      "object_size_bytes": 20480,
      "acked": 15,
      "failed": 0,
      "write_duration_s": 0.12,
      "write_rate_req_s": 125.0,
      "replication_lag_s": 2.39,
      "objects_replicated": 15,
      "all_replicated": true
    },
    {
      "scenario": "500ms Latency + 32KB/s BW",
      "toxics_applied": [
        "latency",
        "bandwidth"
      ],
      "burst_count": 15,
      "object_size_bytes": 20480,
      "acked": 15,
      "failed": 0,
      "write_duration_s": 0.11,
      "write_rate_req_s": 136.4,
      "replication_lag_s": 2.21,
      "objects_replicated": 15,
      "all_replicated": true
    }
  ]
}
```

### E4_partition

**Hypothesis**:
> *"During an asymmetric network partition (A cannot reach B via Toxiproxy timeout), writes to site-a are acknowledged but not replicated. After the partition heals (toxic removed), site-a's writes catch up to site-b within 60 seconds. For conflict keys (same key written on both sides), MinIO's last-write-wins resolution preserves exactly one version on both sites (no data loss for non-conflicting keys)."*

- **Hypothesis Result**: `HELD`
- **Explicit Falsifiable Assertions**:
  - `partition_blocked_replication`: `True`
  - `a_writes_replicated_after_heal`: `True`
  - `b_writes_replicated_after_heal`: `True`
  - `catch_up_within_60s`: `True`
  - `conflict_keys_consistent`: `True`
- **Partition Duration**: `2.7s`
- **Catch-up Time After Heal**: `4.91s`
- **Writes During Partition**: A = `10`, B = `10`
- **Non-conflict writes lost**: A→B missing = `0`, B→A missing = `0`

**Conflict Resolution**:
- `conflict-00.txt`: winner = `B`, consistent = `True`
- `conflict-01.txt`: winner = `B`, consistent = `True`
- `conflict-02.txt`: winner = `B`, consistent = `True`

```json
{
  "experiment": "E4_partition",
  "hypothesis": "During an asymmetric network partition (A cannot reach B via Toxiproxy timeout), writes to site-a are acknowledged but not replicated. After the partition heals (toxic removed), site-a's writes catch up to site-b within 60 seconds. For conflict keys (same key written on both sides), MinIO's last-write-wins resolution preserves exactly one version on both sites (no data loss for non-conflicting keys).",
  "hypothesis_held": true,
  "assertions": {
    "partition_blocked_replication": true,
    "a_writes_replicated_after_heal": true,
    "b_writes_replicated_after_heal": true,
    "catch_up_within_60s": true,
    "conflict_keys_consistent": true
  },
  "rto": "N/A",
  "rpo": "N/A",
  "partition_duration_s": 2.7,
  "catch_up_time_s": 4.91,
  "partition_writes_a": 10,
  "partition_writes_b": 10,
  "missing_a_on_b_after_heal": [],
  "missing_b_on_a_after_heal": [],
  "conflict_resolution": [
    {
      "key": "conflict-00.txt",
      "a_sha256": "2bd6ae5371240de3efec230110e73eb2e303b3dc431d67b0c863b90954d00a70",
      "b_sha256": "8c386ea05ec613e7d3dae48670e1f4f429a488c8490ccc64df7cd2d8a03a3513",
      "a_acked": true,
      "b_acked": true,
      "final_sha_a": "8c386ea05ec613e7d3dae48670e1f4f429a488c8490ccc64df7cd2d8a03a3513",
      "final_sha_b": "8c386ea05ec613e7d3dae48670e1f4f429a488c8490ccc64df7cd2d8a03a3513",
      "consistent": true,
      "winner": "B"
    },
    {
      "key": "conflict-01.txt",
      "a_sha256": "0d4a70a0d45078a6495f76d0bac3c8fb2f3a0f8841e4bb73cfdbd6bc9f6796bc",
      "b_sha256": "9bb737e09dcb2598885321113b79cb0b3fee7968e0ec02475013e800f79895cc",
      "a_acked": true,
      "b_acked": true,
      "final_sha_a": "9bb737e09dcb2598885321113b79cb0b3fee7968e0ec02475013e800f79895cc",
      "final_sha_b": "9bb737e09dcb2598885321113b79cb0b3fee7968e0ec02475013e800f79895cc",
      "consistent": true,
      "winner": "B"
    },
    {
      "key": "conflict-02.txt",
      "a_sha256": "d6224dee44eb85ae228965027e540fa71f305bd62aebeb4ab640b5c068676a1f",
      "b_sha256": "bf6d92c74fdbfe0e120a58331574e0c062a6b93e9d34625247c0902ed03ab690",
      "a_acked": true,
      "b_acked": true,
      "final_sha_a": "bf6d92c74fdbfe0e120a58331574e0c062a6b93e9d34625247c0902ed03ab690",
      "final_sha_b": "bf6d92c74fdbfe0e120a58331574e0c062a6b93e9d34625247c0902ed03ab690",
      "consistent": true,
      "winner": "B"
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
  - Candidate Commit: `6f05e54`
  - Rolled Back To: `122cf3e`
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
  "candidate_commit": "6f05e54915204d273da03da38ccb6de27d3d175c",
  "rolled_back_to": "122cf3e33faf4f1b04ed45e7233a8bea365ed364",
  "rollback_time_seconds": 16,
  "bad_commit_recorded": true,
  "gateway_restored": true
}
```
