# SETU SWFW_5S_02: Live Demonstration & Narration Script

**Project**: Local Multi-Region Highly Available Data Platform with Automated Disaster Recovery, Chaos Engineering, and GitOps  
**Author**: Abhishek Kothe  
**Target Audience**: Zoho Technical Reviewers & Evaluators (November 2026 Review)  
**Total Target Video Duration**: 4 to 6 minutes  

---

## 1. Recording Pre-Flight Checklist

Before hitting record, ensure the environment adheres to this exact checklist:

- [ ] **Terminal Setup**: Open a clean terminal window with a large, legible font (18–20pt minimum), high contrast, full width (120+ columns).
- [ ] **Working Directory**: Start directly in `/home/cloud_automator/setu-starter` on the `main` branch.
- [ ] **Sensitive Files Guard**: Never open or print `.env` or any file containing plaintext credentials. (All credentials in this demo use environment variables and stdlib SigV4 signing).
- [ ] **Order of Demonstration**:
  1. Show `make doctor` live to prove host prerequisites and memory limits pass.
  2. Run `make demo` live (uninterrupted, normal speed, ~1m50s).
  3. Walk through `docs/04-test-evidence/m5-chaos.md` and `docs/04-test-evidence/m6-deep-audit.md` to explain chaos results and cryptographic audit without waiting out the full 5-minute chaos suite.
- [ ] **Pacing & Honesty**: Do not speed up the recording or edit the video timestamps in any way that misrepresents true failover, recovery, or rollback durations. If any pause or transition is edited, display an on-screen caption.

---

## 2. Step-by-Step Narration Guide

### Intro (0:00 – 0:45)
- **What to Say**:
  > *"Hello, my name is Abhishek Kothe. This is the live technical demonstration of my SETU 5th-semester project: a Local Multi-Region Highly Available Data Platform with Automated Disaster Recovery, Chaos Engineering, and GitOps. The entire architecture runs deterministically on a single developer workstation using standard Linux primitives, Docker Compose, and Python's standard library with zero third-party packages. Let us first run `make doctor` to verify system prerequisites."*
- **Action**: Run `make doctor`.
- **What the Audience Sees**: The terminal prints the checklist verifying Docker, Compose v2, Python 3, memory allocation (7.6 GiB VM, >4 GiB free), and traffic control CLI. Zero failures reported.

---

### Step 1: Stack Health Verification (0:45 – 1:00)
- **What to Say**:
  > *"Now I will execute `make demo`. This is a single-command end-to-end self-healing demonstration. Step 1 verifies that HAProxy ingress on port 8080 and both storage backends—Region A on port 9100 and Region B on port 9200—are healthy and responding with HTTP 200."*
- **Action**: Run `make demo` (or `./scripts/demo.sh`).
- **What the Audience Sees**: Container statuses shown as running; Region A, Region B, and Gateway all report `UP (HTTP 200)`.

---

### Step 2: Cross-Region Write & Active Replication (1:00 – 1:15)
- **What to Say**:
  > *"In Step 2, a client writes a test object through HAProxy. HAProxy routes the request to Region A. Under the hood, MinIO two-way site replication immediately replicates the object across the bridge transit network to Region B. The script directly queries Region B and confirms the SHA-256 payload checksum matches bit-for-bit."*
- **What the Audience Sees**: `test-object.txt` written; read from `site-b`; identical SHA-256 hash printed.

---

### Step 3: Ingress Inactive Failover & Backend Header (1:15 – 1:30)
- **What to Say**:
  > *"Step 3 inspects the Layer-7 response headers from HAProxy. The custom `X-Backend-Server` response header shows `minio-a`. In the gateway configuration, Region A is primary and Region B is designated as a backup server, keeping traffic deterministic."*
- **What the Audience Sees**: `X-Backend-Server: minio-a` returned on HTTP 200.

---

### Step 4 & 5: Region A Crash, Failover RTO & Administrative Fencing (1:30 – 2:05)
- **What to Say**:
  > *"Now we inject disaster: Region A is abruptly killed. In Step 4, HAProxy detects socket termination and immediately redispatches incoming client traffic to Region B. Notice that the write probe through the gateway succeeds seamlessly without dropping requests. In Step 5, the autonomous DR controller detects the primary failure, transitions through DEGRADED to FAILOVER, measures the Recovery Time Objective at approximately 3.4 seconds, and issues an administrative command to HAProxy's control socket locking Region A into MAINTENANCE mode. This administrative fencing prevents split-brain writes."*
- **What the Audience Sees**:
  - `docker stop setu-multiregion-minio-a-1` completes.
  - Gateway write probe succeeds via Region B.
  - DR controller logs state transition `HEALTHY -> DEGRADED -> FAILOVER`.
  - HAProxy admin command: `set server minio_api/minio-a state maint`.

---

### Step 6: Region A Restores & Cryptographic Failback Gate (2:05 – 2:35)
- **What to Say**:
  > *"In Step 6, Region A is restarted. A naive system would immediately switch client traffic back to primary, causing data loss or inconsistency because writes occurred on Region B during the outage. Our DR controller transitions to RECOVERING and holds Region A fenced in MAINTENANCE mode. It repeatedly evaluates `compare_sites` in fast metadata mode. While replication catches up, it refuses to fail back (`match: false`). Once MinIO site replication completes and all objects match across both sites (`match: true`), the controller safely un-fences Region A and returns to HEALTHY."*
- **What the Audience Sees**:
  - Container `minio-a` restarted.
  - Controller enters `RECOVERING`.
  - Integrity failback gate evaluates listing and sizes; transitions to `FAILBACK` then `HEALTHY` once `match: true`.
  - HAProxy un-fences `minio-a`: `set server minio_api/minio-a state ready`.

---

### Step 7 & 8: Recovery Point Objective (RPO) Measurement (2:35 – 2:55)
- **What to Say**:
  > *"Steps 7 and 8 prove data integrity. We issue numbered write streams during disaster events. In both graceful stop and hard kill scenarios, all acknowledged writes are verified on Region B, yielding a measured RPO of exactly 0 missing objects under tested workloads."*
- **What the Audience Sees**:
  - Stream writes executed.
  - `rpo_objects: 0` verified.

---

### Step 9: GitOps Continuous Reconciler Auto-Apply & Auto-Rollback (2:55 – 3:35)
- **What to Say**:
  > *"Step 9 demonstrates our autonomous GitOps continuous reconciler running without Kubernetes. First, a valid commit updating gateway timeout is checked out, syntax-checked via `docker compose config`, applied, and validated via active health checks in under 10 seconds. Next, a faulty commit with an invalid gateway port is deployed. The reconciler detects health gate failure, immediately triggers an autonomous rollback to `last_good` within 19 seconds, restores the healthy configuration, and blacklists the bad commit to prevent restart regression."*
- **What the Audience Sees**:
  - GitOps auto-apply logs HTTP 200 health gate pass.
  - Bad commit applied -> health check fails -> `rollback_start` -> stack restored -> `rolled_back` logged.

---

### Step 10: Final Clean Demonstration State (3:35 – 3:50)
- **What to Say**:
  > *"Step 10 performs final cleanup and reports exit code 0. The entire demonstration completed in approximately 1 minute and 50 seconds."*
- **What the Audience Sees**: Terminal prints: `=== DEMO COMPLETE: ALL CHECKS PASSED === (Exit Code: 0)`.

---

### Outro: Chaos Evidence & Deep Cryptographic Audit (3:50 – 5:00)
- **What to Say**:
  > *"To validate resilience beyond the demo, we built a comprehensive chaos engineering suite (`make chaos`) covering 5 distinct failure scenarios: E1 hard crash, E2 socket freeze via docker pause, E3 WAN latency and bandwidth degradation via Toxiproxy, E4 asymmetric one-way network partition with Last-Write-Wins conflict resolution, and E5 mid-deploy chaos. As documented in `docs/04-test-evidence/m5-chaos.md`, all five hypotheses held. Furthermore, `make audit` performs a byte-for-byte SHA-256 payload audit across all 149 objects in both regions, proving zero silent data corruption (bit rot) across the entire platform lifecycle. Thank you."*
- **Action**: Quickly display `m5-chaos.md` and `m6-deep-audit.md` in the editor or terminal.

