# Local Multi-Region Highly Available Data Platform
## With Automated Disaster Recovery, Chaos Engineering, and GitOps
**Course Project**: SETU SWFW_5S_02 | **Student Review**: November 2026

---

### 10-Line Summary
1. Simulates two geographically separated regions (`region_a` and `region_b`) entirely locally using isolated Docker networks and named volumes.
2. Cross-region communication traverses only a shared `global` bridge network, allowing surgical network failure injection without affecting host networking.
3. Storage is powered by active-active MinIO site replication, providing eventual consistency and timestamp-based Last-Write-Wins (LWW) resolution.
4. Clients access the platform through a single HAProxy ingress gateway (`:8080`) configured with active layer-7 health checks and runtime admin controls.
5. An autonomous Python DR controller monitors region vitality, executing sub-5-second failover and fencing `minio-a` into maintenance mode (`MAINT`).
6. Failback to primary is gated by an automated cryptographic consistency check (`compare_sites`), ensuring zero silent divergence before un-fencing.
7. Recovery Point Objective (RPO) is empirically validated to be 0 missing objects under sequential and burst workloads (~35–42 req/s) with surviving disks.
8. An autonomous GitOps reconciler continuously polls a deployment branch, applies targeted container recreation, and triggers automatic rollback on health gate failure.
9. An integrated chaos engineering suite (`make chaos`) validates 5 distinct failure scenarios (crash, socket freeze, WAN latency, partition, deploy failure).
10. The entire platform runs with zero third-party Python packages (stdlib only) and provides reproducible one-command verification via `make demo`.

---

### Quick Start

```bash
# 1. Clone repository
git clone https://github.com/Abhishek7439/setu-starter.git
cd setu-starter

# 2. Configure environment
cp .env.example .env

# 3. Verify system dependencies
make doctor

# 4. Run full end-to-end self-healing & GitOps demonstration (< 2 min)
make demo

# 5. Run full 5-experiment chaos engineering suite (~ 5 min)
make chaos
```

---

### Key Empirical Results

Every metric below is extracted directly from runtime execution logs preserved in `docs/04-test-evidence/`:

| Capability | Target / Scenario | Measured Result | Status | Primary Evidence File |
|:---|:---|:---:|:---:|:---|
| **Multi-Region Health** | AT1: All endpoints HTTP 200 | Region A `:9100`, Region B `:9200`, Gateway `:8080` live | **PASS** | `docs/04-test-evidence/m0-at1-at2.md` |
| **Site Replication** | AT2: Cross-region data sync | Identical SHA-256 (`2cf99d0e...`) across regions | **PASS** | `docs/04-test-evidence/m0-at1-at2.md` |
| **Failover RTO** | AT3: Graceful stop failover | **`3448 ms`** (3s grace window + 443ms write probe) | **PASS** | `docs/04-test-evidence/m2-controller.md` |
| **Integrity Failback** | AT4: Cryptographic gate | Metadata fast-path matches 143 objects in **`1.2s`** (123x speedup) | **PASS** | `docs/04-test-evidence/m3-failback-rpo.md` |
| **Deep Audit** | Full SHA-256 payload audit | 149/149 objects verified bit-for-bit identical (`sha256_checked: 149`) | **PASS** | `docs/04-test-evidence/m6-deep-audit.md` |
| **RPO (Graceful Stop)** | Sequential write stream | **`0` missing objects** (12/12 acknowledged writes preserved) | **PASS** | `docs/04-test-evidence/m3-failback-rpo.md` |
| **RPO (SIGKILL)** | Sequential write stream | **`0` missing objects** (12/12 acknowledged writes preserved) | **PASS** | `docs/04-test-evidence/m3-failback-rpo.md` |
| **GitOps Auto-Apply** | AT5 Phase A: Valid config change | Applied and verified healthy in **`8.0s – 10.0s`** | **PASS** | `docs/04-test-evidence/m4-gitops.md` |
| **GitOps Auto-Rollback**| AT5 Phase B: Broken gateway config | Health gate failed; restored to `last_good` in **`19.0s`** | **PASS** | `docs/04-test-evidence/m4-gitops.md` |
| **Chaos E1 (Crash)** | SIGKILL `minio-a` under 35–42 req/s | Median RTO: **`4732 ms`**; `RPO_failover`: 0; `RPO_after_return`: 0 | **PASS** | `docs/04-test-evidence/m5-chaos.md` |
| **Chaos E2 (Pause)** | `docker pause` socket freeze | Median RTO: **`7192 ms`** (client timeout + redispatch); RPO: 0 | **PASS** | `docs/04-test-evidence/m5-chaos.md` |
| **Chaos E3 (WAN Degrade)**| Toxiproxy: 500ms latency, 32KB/s | Replication lag: **`3.05s`** (latency) vs `0.73s` baseline; 0 lost | **PASS** | `docs/04-test-evidence/m5-chaos.md` |
| **Chaos E4 (Partition)**| Asymmetric timeout toxic A→B | 2.7s cut; catch-up in **`4.91s`**; LWW consistent across sites | **PASS** | `docs/04-test-evidence/m5-chaos.md` |
| **Chaos E5 (Deploy Chaos)**| Kill gateway mid-health-gate | Autonomous rollback completed in **`16.0s`**; bad commit logged | **PASS** | `docs/04-test-evidence/m5-chaos.md` |

---

### Repository Layout

```
.
├── Makefile                     # Standard developer interface (doctor, up, down, demo, chaos, audit)
├── docker-compose.yml           # Multi-region infrastructure (minio-a, minio-b, gateway, toxiproxy, monitor)
├── .env.example                 # Template for credentials and project configuration
├── gateway/
│   └── haproxy.cfg              # HAProxy layer-7 load balancer with active health checks & socket
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
│   └── mc.sh                    # Containerized MinIO client wrapper (zero host install required)
└── docs/
    ├── 00-requirements-checklist.md  # Formal requirements and acceptance criteria traceability
    ├── 01-decisions.md               # Architectural decision records (D1–D12)
    ├── 02-progress-log.md            # Chronological implementation journal
    ├── 03-architecture.md            # Comprehensive system design, diagrams, and limitations
    ├── 04-test-evidence/             # Immutable empirical proof files for all milestones (M0–M6)
    ├── 05-runbook.md                 # Operator guide, troubleshooting, and failure recovery
    ├── 06-reviewer-qa.md             # Reviewer technical Q&A defense document
    └── submission/
        └── SETU_writeup.md           # Formal course submission paper
```
