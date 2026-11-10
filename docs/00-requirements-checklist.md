# Requirements Checklist & Acceptance Test Traceability

**Course Project**: SETU SWFW_5S_02: Local Multi-Region Highly Available Data Platform  
**Target Submission**: November 2026 Review  

---

## 1. High-Level Requirements Matrix

| # | Requirement | Implementation in Codebase | How It Is Proven | Status | Primary Evidence |
|:---:|:---|:---|:---|:---:|:---|
| **1** | Two independent regions | Docker networks `setu_region_a`, `setu_region_b`, private named volumes `minio_a_data`, `minio_b_data` | Verified via `docker network inspect` and `docker volume ls` | **[x] Complete** | `docs/04-test-evidence/m0-at1-at2.md` |
| **2** | Cross-region data replication | MinIO two-way active-active site replication over `setu_global` transit network | Automated S3 write on A replicated to B with identical SHA-256 hash | **[x] Complete** | `docs/04-test-evidence/m0-at1-at2.md` |
| **3** | High availability & failover | HAProxy layer-7 reverse proxy with active health checks on `/minio/health/live` | Region A killed; gateway immediately serves client writes via Region B | **[x] Complete** | `docs/04-test-evidence/m1-gateway.md` |
| **4** | Automated disaster recovery | Python FSM controller (`HEALTHY` -> `DEGRADED` -> `FAILOVER` -> `RECOVERING` -> `FAILBACK`) | Autonomous failover, admin socket fencing to `MAINT`, and RTO measurement | **[x] Complete** | `docs/04-test-evidence/m2-controller.md` |
| **5** | Cryptographic failback gate | Fast listing inventory comparison (`compare_sites`) with SHA-256 fallback | Primary restarts; failback held until 100% object parity verified | **[x] Complete** | `docs/04-test-evidence/m3-failback-rpo.md` |
| **6** | Independent RPO measurement | Numbered write streams during graceful stop and SIGKILL | Zero acknowledged writes missing on backup (`rpo_objects: 0`) | **[x] Complete** | `docs/04-test-evidence/m3-failback-rpo.md` |
| **7** | GitOps continuous deployment | Autonomous reconciler polling bare remote, targeted compose apply, active health gate | Valid commit auto-deployed; broken config detected and automatically rolled back | **[x] Complete** | `docs/04-test-evidence/m4-gitops.md` |
| **8** | Chaos engineering suite | Automated runner executing 5 experiments (E1 crash, E2 pause, E3 latency, E4 partition, E5 deploy chaos) | Executable via `make chaos`; all 5 hypotheses empirically verified | **[x] Complete** | `docs/04-test-evidence/m5-chaos.md` |
| **9** | Production runbook & tooling | Single-command interfaces: `make doctor`, `make demo`, `make chaos`, `make audit` | Verified clean execution on Ubuntu Linux / WSL2 with exit code 0 | **[x] Complete** | `docs/05-runbook.md` |

---

## 2. Acceptance Test Traceability Matrix (AT1 – AT7)

Every acceptance test defined in the course specification is directly traced to executable scripts and empirical evidence files:

| Test ID | Formal Acceptance Criteria | Executing Script / Target | Real Output Summary | Evidence Citation |
|:---:|:---|:---|:---|:---|
| **AT1** | Multi-region health endpoints return HTTP 200 | `make health` / `scripts/demo.sh` | Region A `:9100`, Region B `:9200`, Gateway `:8080` all return HTTP 200 | `docs/04-test-evidence/m0-at1-at2.md` |
| **AT2** | Object written to Region A replicates to Region B | `scripts/demo.sh` (Step 2) | Payload read from Region B; SHA-256 hashes match across both sites | `docs/04-test-evidence/m0-at1-at2.md` |
| **AT3** | Region A dies: automated failover, fencing, RTO measured | `scripts/demo.sh` (Steps 4–5) / `controller/dr_controller.py` | RTO measured: **`3448 ms`**; `minio-a` fenced to `MAINT` on HAProxy socket | `docs/04-test-evidence/m2-controller.md` |
| **AT4** | Region A restarts: automatic resync, checksums match, failback | `scripts/demo.sh` (Step 6) / `controller/proof.py` | Gated in `RECOVERING`; un-fenced only when `compare_sites()` returns `match: true` | `docs/04-test-evidence/m3-failback-rpo.md` |
| **AT5** | GitOps auto-apply on good commit; auto-rollback on bad commit | `scripts/demo-gitops.sh` / `gitops/reconciler.py` | Valid commit applied in **`10.0s`**; broken config rolled back to `last_good` in **`19.0s`** | `docs/04-test-evidence/m4-gitops.md` |
| **AT6** | Resilience under concurrent burst load & gray failure | `make chaos` (`e1_kill.py`, `e2_pause.py`) | E1 crash RTO: **`4732 ms`**, RPO: 0; E2 socket freeze RTO: **`7192 ms`**, RPO: 0 | `docs/04-test-evidence/m5-chaos.md` |
| **AT7** | Resilience under network degradation & partition | `make chaos` (`e3_latency.py`, `e4_partition.py`) | 500ms latency replication lag: **`3.05s`**; partition catch-up: **`4.91s`** (LWW verified) | `docs/04-test-evidence/m5-chaos.md` |
