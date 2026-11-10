# Local Multi-Region Highly Available Data Platform
> **Self-healing with proof**: An enterprise-grade, multi-region distributed object storage platform with automated disaster recovery, cryptographic failback gating, chaos-as-code resilience, and autonomous GitOps continuous delivery.

**Course Project**: SETU SWFW_5S_02  
**Author**: Abhishek Kothe ([@Abhishek7439](https://github.com/Abhishek7439))  
**Academic Target**: YCCE Nagpur / Zoho Campus Offline Review (November 2026)  
**Submission Package**: Comprehensive 18-page technical report in [`report/SETU_SWFW_5S_02_Project_Report.pdf`](report/SETU_SWFW_5S_02_Project_Report.pdf)

---

## What Makes This Different?

Most educational distributed systems stop at basic load balancing or passive failover. This platform demonstrates:

1. **Measured RTO & RPO, Not Marketing Claims**: Recovery Time Objective (3.4s–4.7s) and Recovery Point Objective (0 missing objects) are measured empirically under real concurrent client write workloads (30–42 req/s) with surviving disks.
2. **Cryptographic Integrity Failback Gate**: Restoring a failed primary without administrative fencing causes split-brain overwrites. Our DR controller forcibly fences the primary into `MAINT` on HAProxy's admin socket, continuously checking metadata parity (1.2s across 140+ objects) and un-fencing only when byte parity is mathematically confirmed.
3. **Chaos Engineering as Code**: A standalone test harness (`make chaos`) validates 5 distinct, falsifiable failure modes: hard crash (SIGKILL), socket freeze (`docker pause`), WAN latency/bandwidth degradation (Toxiproxy), asymmetric one-way network partition with Last-Write-Wins conflict resolution, and mid-deploy failure.
4. **Autonomous GitOps Without Kubernetes**: Pull-based continuous deployment with pre-flight YAML validation (`docker compose config`), targeted container recreation (stateless gateway only), and an active post-apply health gate with automated rollback to `last_good` in 19.0 seconds.
5. **Zero External Python Packages**: Pure Python 3.10+ standard library (`urllib`, `socket`, `hashlib`, `hmac`). AWS Signature Version 4 HMAC-SHA256 signing is implemented natively—no 100+ MB `boto3` or `botocore` dependencies.
6. **Scientific Honesty & Explicit Limitations**: Stated trade-offs: eventual consistency (LWW), surviving-disk assumption, client timeout impact on RTO, and simulated WAN characteristics.

---

## Headline Empirical Results

Every metric below is extracted directly from runtime execution logs preserved in [`docs/04-test-evidence/`](docs/04-test-evidence/):

| Capability | Scenario / Target | Measured Metric | Status | Primary Evidence File |
|:---|:---|:---:|:---:|:---|
| **Multi-Region Vitality** | AT1: All endpoints HTTP 200 | Region A `:9100`, Region B `:9200`, Gateway `:8080` live | **PASS** | [`docs/04-test-evidence/m0-at1-at2.md`](docs/04-test-evidence/m0-at1-at2.md) |
| **Site Replication** | AT2: Cross-region data sync | Identical SHA-256 (`2cf99d0e...`) across regions | **PASS** | [`docs/04-test-evidence/m0-at1-at2.md`](docs/04-test-evidence/m0-at1-at2.md) |
| **Failover RTO** | AT3: Graceful stop failover | **`3448 ms`** (3s grace window + 443ms write probe) | **PASS** | [`docs/04-test-evidence/m2-controller.md`](docs/04-test-evidence/m2-controller.md) |
| **Integrity Failback** | AT4: Fast metadata gate | Inventory match across 143+ objects in **`1.2s`** (123x speedup) | **PASS** | [`docs/04-test-evidence/m3-failback-rpo.md`](docs/04-test-evidence/m3-failback-rpo.md) |
| **Cryptographic Deep Audit**| Full SHA-256 payload audit | **153 / 153 objects** verified bit-for-bit identical (`sha256_checked: 153`) | **PASS** | [`docs/04-test-evidence/m6-deep-audit.md`](docs/04-test-evidence/m6-deep-audit.md) |
| **RPO (Graceful Stop)** | Sequential write stream | **`0` missing objects** (12/12 acknowledged writes preserved) | **PASS** | [`docs/04-test-evidence/m3-failback-rpo.md`](docs/04-test-evidence/m3-failback-rpo.md) |
| **RPO (SIGKILL Crash)** | Sequential write stream | **`0` missing objects** (12/12 acknowledged writes preserved) | **PASS** | [`docs/04-test-evidence/m3-failback-rpo.md`](docs/04-test-evidence/m3-failback-rpo.md) |
| **GitOps Auto-Apply** | AT5 Phase A: Valid config change | Deployed and verified healthy in **`8.0s – 10.0s`** | **PASS** | [`docs/04-test-evidence/m4-gitops.md`](docs/04-test-evidence/m4-gitops.md) |
| **GitOps Auto-Rollback**| AT5 Phase B: Broken gateway config | Health gate failed; restored to `last_good` in **`19.0s`** | **PASS** | [`docs/04-test-evidence/m4-gitops.md`](docs/04-test-evidence/m4-gitops.md) |
| **Chaos E1 (Crash)** | SIGKILL `minio-a` under 37.2 req/s | Median RTO: **`4732 ms`**; `RPO_failover`: 0; `RPO_after_return`: 0 | **PASS** | [`docs/04-test-evidence/m5-chaos.md`](docs/04-test-evidence/m5-chaos.md) |
| **Chaos E2 (Pause)** | `docker pause` socket freeze | Median RTO: **`7192 ms`** (client timeout + redispatch); RPO: 0 | **PASS** | [`docs/04-test-evidence/m5-chaos.md`](docs/04-test-evidence/m5-chaos.md) |
| **Chaos E3 (WAN Degrade)**| Toxiproxy: 500ms latency, 32KB/s | Replication lag: **`3.05s`** (latency) vs `0.73s` baseline; 0 lost | **PASS** | [`docs/04-test-evidence/m5-chaos.md`](docs/04-test-evidence/m5-chaos.md) |
| **Chaos E4 (Partition)**| Asymmetric timeout toxic A→B | 2.7s cut; catch-up in **`4.91s`**; LWW consistent across sites | **PASS** | [`docs/04-test-evidence/m5-chaos.md`](docs/04-test-evidence/m5-chaos.md) |
| **Chaos E5 (Deploy Chaos)**| Kill gateway mid-health-gate | Autonomous rollback completed in **`16.0s`**; bad commit logged | **PASS** | [`docs/04-test-evidence/m5-chaos.md`](docs/04-test-evidence/m5-chaos.md) |

---

## System Architecture

```mermaid
graph TD
    Client["S3 Client<br/>(AWS SigV4 / Port 8080)"] --> Gateway["HAProxy Ingress Gateway (:8080)<br/>Active Check: /minio/health/live<br/>Admin Socket: 127.0.0.1:9999"]
    
    subgraph Region A ["Region A (setu_region_a)"]
        MinioA["minio-a (:9100 / :9101)<br/>Primary Storage Backend"]
        VolA[("minio_a_data<br/>Docker Volume")]
        MinioA --- VolA
    end

    subgraph Region B ["Region B (setu_region_b)"]
        MinioB["minio-b (:9200 / :9201)<br/>Standby Backup Backend"]
        VolB[("minio_b_data<br/>Docker Volume")]
        MinioB --- VolB
    end

    Gateway -->|Primary Path| MinioA
    Gateway -.->|Standby Backup / Redispatch| MinioB

    subgraph Transit Network ["Transit Network (setu_global)"]
        Toxi["Toxiproxy (:9002 / :8474)<br/>Replication Choke Point & Fault Injection"]
    end

    MinioA <===>|Two-Way Active-Active Replication| Toxi
    Toxi <===> MinioB

    DR["DR Controller (dr_controller.py)<br/>5-State Finite State Machine"] -->|Administrative Fencing (MAINT/READY)| Gateway
    GitOps["GitOps Reconciler (reconciler.py)<br/>Continuous Polling & Health Gate"] -->|Targeted Deploy & Rollback| Gateway
```

*Detailed architectural design and component specs: [`docs/03-architecture.md`](docs/03-architecture.md).*

---

## The Failure Story in 6 Lines

1. **Disaster Strikes**: Region A abruptly terminates (`docker stop` or SIGKILL).
2. **Instant Redispatch**: HAProxy detects connection failure and redispatches in-flight client writes to Region B without dropping requests.
3. **Ingress Fencing**: DR controller transitions to `FAILOVER`, logs RTO (**`3448 ms`**), and fences Region A into `MAINT` on HAProxy's admin socket to prevent split-brain.
4. **Standalone Service**: Region B serves client traffic exclusively while Region A is down.
5. **Quarantined Recovery**: Region A restarts, but is held quarantined in `MAINT` while MinIO site replication syncs objects written to B during the outage.
6. **Cryptographic Failback**: Once `compare_sites` confirms 100% object count and ETag parity (**`match: true`**), the controller un-fences Region A (`READY`) and safely returns to `HEALTHY`.

---

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/Abhishek7439/setu-starter.git
cd setu-starter

# 2. Configure environment (pure stdlib; no pip install)
cp .env.example .env

# 3. Verify system prerequisites and memory limits
make doctor

# 4. Run end-to-end self-healing demonstration (~1m50s, exit code 0)
make demo

# 5. Run full 5-experiment chaos engineering suite (~4m30s)
make chaos

# 6. Run byte-for-byte cryptographic deep audit (all objects SHA-256)
make audit
```

---

## Chaos Engineering Resilience Suite

The platform executes 5 automated resilience experiments via `make chaos` (`chaos/runner.py`), with real outputs recorded in [`docs/04-test-evidence/m5-chaos.md`](docs/04-test-evidence/m5-chaos.md):

| ID | Failure Mode | Injected Turbulence | Hypothesis Evaluation | Empirical Outcome |
|:---:|:---|:---|:---|:---|
| **E1** | Hard Crash | Abrupt SIGKILL on `minio-a` under 37.2 req/s write load | **HELD** | Median RTO: **`4732 ms`**; `RPO_failover`: 0; `RPO_after_return`: 0 |
| **E2** | Gray Failure | Socket freeze (`docker pause`) measuring client timeouts | **HELD** | Median RTO: **`7192 ms`** (3.5s client timeout + HAProxy 2.0s connect); RPO: 0 |
| **E3** | WAN Degradation | 500ms latency & 32KB/s bandwidth via Toxiproxy | **HELD** | Lag: **`3.05s`** vs `0.73s` baseline; 0 lost writes |
| **E4** | One-Way Partition | Asymmetric timeout toxic cutting A&rarr;B replication | **HELD** | 2.7s cut; catch-up in **`4.91s`**; Last-Write-Wins conflict preserved |
| **E5** | Deploy Chaos | Container killed during active GitOps health gate | **HELD** | Health failure detected; auto-rollback to `last_good` in **`16.0s`** |

---

## Mandatory System Limitations

To maintain scientific integrity, the following limitations are explicitly stated:

> **Honest Scope & Architectural Boundaries:**
> 1. **Eventual Consistency & Last-Write-Wins**: MinIO site replication is an active-active, eventually consistent system. Simultaneous dual-primary writes to identical keys resolve strictly by UTC timestamp; the older version is overwritten.
> 2. **RPO Measurement Scope**: Measured RPO of `0` missing objects was validated under ~35–42 writes/sec with small objects and with **surviving disk volumes**. Catastrophic physical disk destruction was not tested.
> 3. **RTO Includes Client Timeouts**: During gray failures (E2 `docker pause`), RTO measurements include the client HTTP request timeout (3.5s) plus HAProxy's 2.0s connect timeout and redispatch window (~7.2s total).
> 4. **E3 Noise**: In Experiment E3, combined latency + bandwidth lag (2.21s) was slightly lower than latency-only (3.05s); these variations reflect run-to-run noise and no causal trend is claimed.
> 5. **E4 One-Way Partition**: Toxiproxy sits specifically on the `minio-a -> minio-b` path (port 9002). E4 tested an asymmetric one-way partition; `minio-b -> minio-a` remained directly connected.
> 6. **Simulated Regions**: Both regions run as Docker containers on a single Linux kernel (Ubuntu on WSL2); WAN latency and bandwidth constraints were injected programmatically.

---

## Repository Layout

```text
.
├── Makefile                     # Standard developer interface (doctor, up, down, demo, chaos, audit, package)
├── docker-compose.yml           # Multi-region infrastructure (minio-a, minio-b, gateway, toxiproxy, monitor)
├── .env.example                 # Safe credential template (actual .env is git-ignored)
├── gateway/
│   ├── haproxy.cfg              # HAProxy layer-7 load balancer with active health checks & socket
│   └── nginx.conf               # Reference configuration from Milestone M1
├── controller/
│   ├── dr_controller.py         # Autonomous 5-state disaster recovery state machine
│   └── proof.py                 # Fast listing integrity gate (compare_sites), RPO & RTO measurement
├── gitops/
│   └── reconciler.py            # Pull-based continuous reconciler with active health gate & rollback
├── chaos/
│   ├── common.py                # Stdlib AWS SigV4 client, concurrent writer, Toxiproxy REST helpers
│   ├── runner.py                # Automated runner for E1–E5 with markdown evidence generator
│   └── experiments/
│       ├── e1_kill.py           # E1: Abrupt SIGKILL crash under concurrent write stream
│       ├── e2_pause.py          # E2: Gray failure (docker pause socket freeze)
│       ├── e3_latency.py        # E3: WAN latency (500ms) and bandwidth (32KB/s) injection
│       ├── e4_partition.py      # E4: Asymmetric one-way partition & LWW conflict resolution
│       └── e5_gitops_chaos.py   # E5: Failure injection during active GitOps continuous deployment
├── scripts/
│   ├── doctor.sh                # System dependency and memory validation check
│   ├── demo.sh                  # One-command 10-step end-to-end self-healing demonstration
│   ├── demo-gitops.sh           # Standalone demonstration of GitOps auto-apply & auto-rollback
│   ├── mc.sh                    # Containerized MinIO client wrapper (zero host install required)
│   └── build_submission.sh      # Automated submission package builder and validator
├── report/
│   ├── report.html              # Comprehensive 18-page technical report with inline outputs
│   └── SETU_SWFW_5S_02_Project_Report.pdf  # Compiled submission PDF document
├── demo/
│   ├── DEMO_SCRIPT.md           # Step-by-step narration script and recording checklist
│   ├── README.md                # Demonstration overview and offline evaluation protocol
│   └── demo-run.log             # Real execution log of make demo concluding with exit code 0
└── docs/
    ├── 00-requirements-checklist.md  # Formal requirements and acceptance criteria traceability
    ├── 01-decisions.md               # Architectural decision records (D1–D12)
    ├── 02-progress-log.md            # Chronological implementation journal
    ├── 03-architecture.md            # Comprehensive system design, diagrams, and limitations
    ├── 04-test-evidence/             # Immutable empirical proof files for all milestones (M0–M6)
    ├── 05-runbook.md                 # Operator guide, troubleshooting, and failure recovery
    ├── 06-reviewer-qa.md             # Reviewer technical Q&A defense document
    ├── GITHUB_SETUP.md               # Instructions for setting up repository metadata on GitHub
    └── images/                       # Terminal output renders and architectural diagrams
```

---

## Documentation & Evidence Index

* **Complete Technical Report (PDF)**: [`report/SETU_SWFW_5S_02_Project_Report.pdf`](report/SETU_SWFW_5S_02_Project_Report.pdf)
* **Architectural Decisions (D1–D12)**: [`docs/01-decisions.md`](docs/01-decisions.md)
* **Operator Runbook & Troubleshooting**: [`docs/05-runbook.md`](docs/05-runbook.md)
* **Reviewer Technical Defense Q&A (15 Questions)**: [`docs/06-reviewer-qa.md`](docs/06-reviewer-qa.md)
* **Real Terminal Output Renders**: [`docs/images/`](docs/images/)
