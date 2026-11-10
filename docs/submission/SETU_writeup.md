# SETU Project Summary Write-up
## Course Project: SWFW_5S_02 — Local Multi-Region Highly Available Data Platform with Automated Disaster Recovery, Chaos Engineering, and GitOps
**Student Name**: Abhishek Kothe  
**GitHub Account**: `Abhishek7439`  
**Academic Term**: 5th Semester (November 2026)  
**Repository**: `https://github.com/Abhishek7439/setu-starter.git`  

---

### [SETU_HEADING_1: Problem Statement & Objectives]
High availability (HA) and disaster recovery (DR) across isolated failure domains are fundamental requirements for production data platforms. Validating failure modes—including failover, network partitions, gray failures, and split-brain scenarios—is typically expensive and non-deterministic on public cloud infrastructure.

The goal of course project **SETU SWFW_5S_02** is to build and empirically validate a multi-region object storage platform entirely on a single Linux workstation (16 GB RAM, Ubuntu / WSL2). The system must provide active-active object storage replication, automated failover with measurable Recovery Time Objective (RTO) and Recovery Point Objective (RPO), an automated integrity-checked failback gate, autonomous GitOps continuous deployment with health checking and rollback, and a reproducible chaos engineering test suite—without relying on Kubernetes or third-party Python packages.

---

### [SETU_HEADING_2: System Architecture & Implementation]
The platform is built from focused, decoupled infrastructure and software primitives:

1. **Regional Isolation**: Two independent regions (`setu_region_a` and `setu_region_b`) run as Docker containers with private named volumes (`minio_a_data`, `minio_b_data`). Cross-region traffic travels exclusively over a shared bridge transit network (`setu_global`), establishing a controlled path for network failure injection.
2. **Ingress Gateway**: HAProxy 3.4.7 serves as the single entry point (`:8080`). It runs active layer-7 health checks (`/minio/health/live`) against Region A (primary) and Region B (backup), injects `X-Backend-Server` response headers, and exposes an administrative TCP socket (`127.0.0.1:9999`) for zero-reload runtime server fencing.
3. **Disaster Recovery State Machine**: An autonomous daemon (`controller/dr_controller.py`) implements a 5-state deterministic FSM (`HEALTHY`, `DEGRADED`, `FAILOVER`, `RECOVERING`, `FAILBACK`). It uses a 3-second grace window to suppress flapping, fences dead primaries to `MAINT` in HAProxy, and gates failback on cryptographic site parity.
4. **Metadata Failback Gate**: The routine failback gate (`controller/proof.py` in fast mode) compares object listings, sizes, and ETags across both sites via `mc ls --recursive --json`. On clean data, it verifies parity in **1.2 seconds** across 140+ objects (123x faster than sequential downloads, `sha256_checked: 0`), falling back to SHA-256 only on multipart ETag mismatches. A full deep byte-for-byte SHA-256 verification is provided via `make audit` (`--deep`).
5. **GitOps Reconciler**: Implemented in `gitops/reconciler.py`, an autonomous daemon polls a bare git repository in a dedicated worktree (`/tmp/setu-gitops-wt`). It performs targeted container recreation based on `git diff` and gates deployments behind a post-apply health gate. Broken changes trigger automatic rollback to `last_good` within 20 seconds.
6. **Zero External Python Packages**: Every module (DR controller, GitOps reconciler, SigV4 client, concurrent burst writer, chaos runner) is written strictly in Python standard library (`hashlib`, `hmac`, `urllib`, `socket`, `subprocess`).

---

### [SETU_HEADING_3: Key Empirical Results]
All metrics below are drawn directly from execution logs in `docs/04-test-evidence/`:

1. **RTO (Recovery Time Objective)**:
   - Primary graceful stop: **`3448 ms`** (`m2-controller.md`).
   - Abrupt crash (`SIGKILL`) under concurrent load (~35–42 req/s): Median RTO of **`4732 ms`** across 3 iterations (`m5-chaos.md`).
   - Gray failure (`docker pause` socket freeze): Median RTO of **`7192 ms`** across 3 iterations (`m5-chaos.md`).
2. **RPO (Recovery Point Objective)**:
   - Sequential write stream: **`0` missing objects** across 12 acknowledged writes (`m3-failback-rpo.md`).
   - Concurrent burst writes (~35–42 req/s, ~400 requests/iteration): `RPO_failover = 0` and `RPO_after_return = 0` across all 3 iterations (`m5-chaos.md`).
3. **Site Integrity Proof**:
   - Routine failback gate: Fast listing/size/ETag comparison matches in **`1.2s`** (`m4-gitops.md`).
   - Full deep audit (`make audit`): Every stored object payload streamed and SHA-256 hashed across both sites; **`149/149` objects matched** with `sha256_checked: 149` (`m6-deep-audit.md`).
4. **GitOps Continuous Deployment (AT5)**:
   - Valid configuration change: automatically deployed in **`10.0s`** (`m4-gitops.md`).
   - Broken gateway configuration: detected by active health gate; automatically rolled back to `last_good` in **`19.0s`** (`m4-gitops.md`).
5. **Chaos Resilience Suite (`make chaos`)**:
   - `E1` (SIGKILL): 3 iterations passed; max RTO 4787ms (under 10s SLA); RPO 0.
   - `E2` (docker pause): 3 iterations passed; max RTO 7214ms; RPO 0.
   - `E3` (WAN degradation): 500ms latency increased replication lag to **`3.05s`** (vs 0.73s baseline); 32KB/s bandwidth cap increased lag to **`2.39s`**; 100% of objects replicated with zero data loss.
   - `E4` (One-way partition): 2.7s cut on A->B link; 10 writes to A, 10 writes to B, 3 conflict keys; catch-up achieved in **`4.91s`**; Last-Write-Wins consistency confirmed across both sites.
   - `E5` (Deploy chaos): Injected container kill during health gate; autonomous rollback in **`16.0s`**.
6. **End-to-End Demo**:
   - `make demo` runs the full 10-step platform demonstration in **`1m 50s – 1m 55s`** with exit code 0.

---

### [SETU_HEADING_4: Key Engineering Learnings]
1. **Crash vs. Gray Failure Semantics**: SIGKILL causes the OS kernel to emit TCP RST immediately, allowing HAProxy to detect socket failure quickly. `docker pause` freezes execution without closing sockets, forcing clients to wait out client and gateway connect timeouts (~7.2s).
2. **Ingress Fencing Prevents Split-Brain**: Restoring a failed primary without administrative fencing creates split-brain risk. Fencing primary in HAProxy (`MAINT`) until cryptographic listing parity (`match: true`) is confirmed is essential.
3. **Targeted Container Re-creation**: Computing git diffs to recreate only modified stateless services (e.g. gateway) prevents unnecessary restarts of stateful storage containers.
4. **User-Space Fault Injection**: Programmatic TCP proxying (via Toxiproxy) avoids host kernel manipulation (`tc netem`) and `CAP_NET_ADMIN` root privileges.

---

### [SETU_HEADING_5: Mandatory System Limitations]

The following limitations are explicitly documented:

1. **Eventual Consistency and Last-Write-Wins (LWW)**: MinIO site replication is an active-active, eventually consistent distributed storage engine. If both regions are written to concurrently on identical object keys during a partition, MinIO resolves the conflict strictly by object timestamp (Last-Write-Wins). The older version is overwritten; application-level semantic conflict merging is not supported.
2. **RPO Measurement Boundary**: The measured RPO of `0` missing objects was empirically validated under workloads of approximately 35–42 writes/sec with small objects (4 KB – 20 KB) and with **surviving disk volumes**. This is an empirical demonstration of replication performance under test conditions, not a mathematical zero-data-loss guarantee. Physical disk loss (catastrophic hardware wipe or block destruction) was not tested.
3. **RTO Includes Client Timeouts**: During gray failures (such as `docker pause` in E2), measured RTO includes the client HTTP request timeout (3.5 seconds) in addition to HAProxy's 2-second connection timeout and redispatch window, resulting in measured RTO clustering around ~7.2 seconds.
4. **E3 Lag Differences**: In Experiment E3, the combined latency + bandwidth replication lag (2.21s) was lower than the latency-only scenario (3.05s). These differences were within run-to-run noise, and the specific underlying cause was not investigated.
5. **E4 One-Way Partition**: Toxiproxy sits specifically on the `site-a` -> `site-b` replication path (port 9002). In Experiment E4, timeout toxics severed traffic from `site-a` to `site-b` only. `site-b`'s replication endpoint to `site-a` was direct (`http://minio-a:9000`), meaning writes to `site-b` continued to reach `site-a` during the cut. This was a **one-way (asymmetric) partition**, not a complete bidirectional severance.
6. **Single-Machine Simulation**: Both "regions" execute as Docker containers on a single host Linux kernel. Inter-region WAN characteristics (propagation delay, bandwidth caps) were simulated programmatically via Toxiproxy rather than traversing actual cross-continental fiber.
