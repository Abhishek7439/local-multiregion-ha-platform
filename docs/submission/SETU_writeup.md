# SETU Course Submission Write-up
## Course Project: SWFW_5S_02 — Local Multi-Region Highly Available Data Platform with Automated Disaster Recovery, Chaos Engineering, and GitOps
**Student Name**: Abhishek Kothe  
**GitHub Account**: `Abhishek7439`  
**Evaluation Review**: Zoho Campus Offline Review (November 2026)  
**Repository**: `https://github.com/Abhishek7439/setu-starter.git`  

---

### [SETU_SECTION_HEADING_PLACEHOLDER_1: Problem Statement & Context]
Modern cloud-native architectures require high availability (HA) and disaster recovery (DR) guarantees across geographically distinct failure domains. However, practicing and demonstrating distributed systems failure modes—such as failover, network partitions, gray failures, and split-brain scenarios—often incurs substantial cloud infrastructure costs and nondeterministic network conditions. 

The objective of course project **SETU SWFW_5S_02** is to design, construct, and empirically validate an enterprise-grade multi-region data platform running entirely locally on a single developer workstation (16 GB RAM, Ubuntu Linux / WSL2). The system must provide active-active object storage replication, automated failover with measurable Recovery Time Objective (RTO) and Recovery Point Objective (RPO), cryptographic integrity-checked failback, autonomous GitOps continuous delivery with self-healing rollback, and structured chaos engineering experiments without relying on third-party orchestration frameworks or Python packages.

---

### [SETU_SECTION_HEADING_PLACEHOLDER_2: Architectural Approach & Engineering Choices]
Rather than deploying heavyweight container orchestrators (such as Kubernetes or Nomad) that consume substantial memory and abstract away socket-level networking, we designed a deterministic architecture composed of focused, decoupled primitives:

1. **Physical Isolation via Docker Networks**: Two independent failure domains (`setu_region_a` and `setu_region_b`) are instantiated with private named volumes (`minio_a_data`, `minio_b_data`). Cross-region traffic is strictly isolated to a single bridge transit network (`setu_global`), establishing a controlled choke point for fault injection.
2. **Layer-7 Ingress & Active Health Checking**: HAProxy 3.4.7 serves as the unified ingress gateway (`:8080`). Unlike Nginx (which fails to resolve upstreams when a backend is down during restart), HAProxy evaluates active HTTP health checks (`/minio/health/live`) and exposes an administrative socket on `127.0.0.1:9999` enabling instantaneous runtime server fencing without configuration reloads.
3. **Deterministic DR State Machine**: The DR agent (`controller/dr_controller.py`) is implemented as a 5-state deterministic finite state machine (`HEALTHY`, `DEGRADED`, `FAILOVER`, `RECOVERING`, `FAILBACK`). It incorporates a 3-second grace window to suppress false failovers during transient blips, and strictly fences dead backends into maintenance mode (`MAINT`).
4. **Metadata-Gated Failback Engine**: Rather than performing costly $O(N)$ full payload downloads, `controller/proof.py` implements a fast-path listing comparison (`mc ls --recursive --json`) that verifies object key and ETag parity across both sites in **1.2 seconds** (a 123x speedup over sequential downloads), falling back to SHA-256 streaming only when ETags differ due to multipart chunking boundaries.
5. **Autonomous GitOps Reconciler**: Implemented in `gitops/reconciler.py`, the reconciler polls a bare git repository inside an isolated worktree (`/tmp/setu-gitops-wt`). It performs targeted container recreation based on `git diff` and gates all candidate deployments behind a post-apply active health gate. Failed deployments trigger automatic rollback to `last_good` within 20 seconds.
6. **Zero-Dependency Constraint**: Every custom module (DR controller, GitOps reconciler, SigV4 client, concurrent burst writer, chaos runner) is authored exclusively in Python standard library (`hashlib`, `hmac`, `urllib`, `socket`, `subprocess`), guaranteeing portability on any Linux distribution without `pip install`.

---

### [SETU_SECTION_HEADING_PLACEHOLDER_3: What Was Built]
The delivered codebase contains the following fully operational components:
- `docker-compose.yml`: Multi-container topology defining `minio-a` (port 9100), `minio-b` (port 9200), `gateway` (port 8080), `toxiproxy` (ports 8474, 9002), and `monitor`.
- `gateway/haproxy.cfg`: High-performance proxy configuration injecting `X-Backend-Server` response headers and exposing the admin socket.
- `controller/dr_controller.py`: Autonomous disaster recovery engine managing failover, fencing, RTO probing, and safe failback.
- `controller/proof.py`: Cryptographic verification engine implementing `compare_sites` and sequential/burst RPO validation.
- `gitops/reconciler.py`: Autonomous continuous deployment reconciler supporting syntax pre-flight checks, targeted recreation, and auto-rollback.
- `chaos/`: Full chaos engineering suite including AWS SigV4 signer, multi-threaded concurrent burst writer (~35–45 req/s), Toxiproxy REST client, and 5 automated experiment modules.
- `scripts/`: Shell automation providing `make doctor`, `make demo` (reproducible end-to-end self-healing), `make gitops-demo`, and `mc.sh` (containerized MinIO client).

---

### [SETU_SECTION_HEADING_PLACEHOLDER_4: Empirical Results & Verification]
All metrics cited below represent actual runtime data recorded in the immutable test evidence logs in `docs/04-test-evidence/`:

1. **Recovery Time Objective (RTO)**:
   - Primary crash under graceful stop: **`3448 ms`** (`docs/04-test-evidence/m2-controller.md`).
   - Abrupt crash (`SIGKILL`) under concurrent write load (~35–42 req/s): Median RTO of **`4732 ms`** across 3 iterations (`docs/04-test-evidence/m5-chaos.md`).
   - Gray failure (`docker pause` socket freeze): Median RTO of **`7192 ms`** across 3 iterations (`docs/04-test-evidence/m5-chaos.md`).
2. **Recovery Point Objective (RPO)**:
   - Sequential numbered write streams during graceful stop and SIGKILL: **`0` missing objects** across 12 acknowledged writes (`docs/04-test-evidence/m3-failback-rpo.md`).
   - Concurrent burst writes (~35–42 req/s, ~400 total requests per iteration): `RPO_failover = 0` and `RPO_after_return = 0` across all 3 iterations (`docs/04-test-evidence/m5-chaos.md`).
3. **Automated Failback Parity**:
   - Primary recovery verified with 143+ objects: fast-path metadata listing comparison verified parity in **`1.2s`** with zero divergence (`docs/04-test-evidence/m4-gitops.md`).
4. **GitOps Continuous Deployment (AT5)**:
   - Benign valid change: automatically detected, applied, and verified healthy in **`10.0s`** (`docs/04-test-evidence/m4-gitops.md`).
   - Broken gateway configuration: detected by active health gate; automatically rolled back to `last_good` in **`19.0s`**; stack restored to HTTP 200 (`docs/04-test-evidence/m4-gitops.md`).
5. **Chaos Resilience Suite (`make chaos`)**:
   - `E1` (SIGKILL): 3 iterations passed; max RTO 4787ms (well below 10s SLA); RPO 0.
   - `E2` (docker pause): 3 iterations passed; max RTO 7214ms; RPO 0.
   - `E3` (WAN degradation): 500ms latency increased replication lag to **`3.05s`** (vs 0.73s baseline); 32KB/s bandwidth cap increased lag to **`2.39s`**; 100% of objects replicated with zero data loss.
   - `E4` (Asymmetric network partition): 2.7s replication link severed; 10 writes to A, 10 writes to B, 3 conflict keys; full catch-up achieved in **`4.91s`**; Last-Write-Wins consistency confirmed across both sites.
   - `E5` (Deploy chaos): Injected container kill during health gate; autonomous rollback completed in **`16.0s`**.
6. **Demo Execution Speed**:
   - `make demo` runs the full 10-step platform demonstration in **`1m 50s`** with exit code 0.

---

### [SETU_SECTION_HEADING_PLACEHOLDER_5: Key Engineering Learnings]
1. **Socket Semantics in Crash vs. Gray Failures**: Abrupt container termination (`SIGKILL`) causes the host kernel to immediately emit TCP RST packets, enabling reverse proxies to detect failure instantly. In contrast, gray failures (`docker pause`) freeze sockets without emitting RST or FIN. Client request timeouts and gateway connection timeouts directly dictate RTO during gray failures.
2. **Asynchronous Replication and RPO Bounds**: Under active-active eventual consistency, RPO of 0 missing objects is achievable only when write rates do not overwhelm replication queue throughput and persistent disk volumes survive.
3. **The Necessity of Ingress Fencing**: Restoring a failed primary without administrative fencing creates severe split-brain risks. If primary restarts before replication resync finishes, clients writing to both sites can overwrite data. Fencing primary in HAProxy until cryptographic parity (`match: true`) is proven is critical for distributed consistency.
4. **Targeted Deployment vs. Infrastructure Destruction**: In GitOps pipelines managing persistent state, blanket `--force-recreate` must never be used. Computing diffs to recreate only modified stateless containers (e.g. gateway) prevents unnecessary storage outages.
5. **User-Space Fault Injection**: Programmatic TCP proxying (via Toxiproxy) provides far greater portability and safety than host kernel manipulation (`tc netem`), avoiding root requirements and privilege leaks.

---

### [SETU_SECTION_HEADING_PLACEHOLDER_6: Mandatory System Limitations]

To maintain rigorous scientific and engineering integrity, the following limitations are explicitly stated:

1. **Eventual Consistency and Last-Write-Wins (LWW)**: MinIO site replication is an active-active, eventually consistent distributed storage engine. In scenarios where both regions are written to concurrently on identical object keys during a partition, MinIO resolves the conflict via object timestamp (Last-Write-Wins). The older version is overwritten; application-level semantic conflict merging is not supported.
2. **RPO Measurement Boundary**: The measured RPO of `0` missing objects was empirically validated under workloads of approximately 35–42 writes/sec with small objects (4 KB – 20 KB) and with **surviving disk volumes**. This is an empirical demonstration of replication performance under test conditions, not a mathematical zero-data-loss guarantee. Physical disk loss (catastrophic hardware wipe or block destruction) was not tested.
3. **RTO Includes Client Timeouts**: During gray failures (such as `docker pause` in E2), measured RTO includes the client HTTP request timeout (3.5 seconds) in addition to HAProxy's 2-second connection timeout and redispatch window, resulting in measured RTO clustering around ~7.2 seconds.
4. **Network Chaos Scope (Toxiproxy Placement)**: Toxiproxy sits specifically on the `minio-a` -> `minio-b` replication path (port 9002). In experiment E4 (asymmetric partition), timeout toxics explicitly cut traffic between `site-a` and `site-b`; client-to-gateway and client-to-direct-port paths remained unaffected. In experiment E3, replication lag variations between isolated and combined scenarios reflect connection pooling and measurement granularity; no artificial trend is claimed.
5. **Single-Machine Simulation**: Both "regions" execute as Docker containers on a single host Linux kernel. Inter-region WAN characteristics (propagation delay, packet loss, bandwidth caps) were simulated programmatically via Toxiproxy rather than traversing actual cross-continental fiber.
