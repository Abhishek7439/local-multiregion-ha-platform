<div align="center">

# 🏗️ Local Multi-Region Highly Available Data Platform

### Automated Disaster Recovery · Chaos Engineering · GitOps

<br>

[![Platform](https://img.shields.io/badge/Platform-Docker_Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](docker-compose.yml)
[![Language](https://img.shields.io/badge/Python-3.10+_stdlib_only-3776AB?style=for-the-badge&logo=python&logoColor=white)](controller/)
[![Gateway](https://img.shields.io/badge/Gateway-HAProxy_3.4-005C97?style=for-the-badge&logo=haproxy&logoColor=white)](gateway/haproxy.cfg)
[![Storage](https://img.shields.io/badge/Storage-MinIO_S3-C72E49?style=for-the-badge&logo=minio&logoColor=white)](docker-compose.yml)
[![Chaos](https://img.shields.io/badge/Chaos-Toxiproxy-FF6B35?style=for-the-badge)](chaos/)
[![Report](https://img.shields.io/badge/📄_Report-18_Pages-success?style=for-the-badge)](report/SETU_SWFW_5S_02_Project_Report.pdf)

<br>

> **Self-healing with proof** — not a marketing claim but a measured, reproducible,
> cryptographically verified platform that detects failure, fences the dead node,
> redirects traffic, verifies data integrity, and restores service —
> all autonomously in under 5 seconds, with zero data loss.

<br>

| 🎯 Metric | 📊 Measured Value | 📋 Evidence |
|:---|:---:|:---|
| **Failover RTO** | **3.4 s** | [`m2-controller.md`](docs/04-test-evidence/m2-controller.md) |
| **Data Loss (RPO)** | **0 objects** | [`m3-failback-rpo.md`](docs/04-test-evidence/m3-failback-rpo.md) |
| **Failback Integrity Gate** | **1.2 s** across 143+ objects | [`m3-failback-rpo.md`](docs/04-test-evidence/m3-failback-rpo.md) |
| **Deep SHA-256 Audit** | **153/153** objects verified | [`m6-deep-audit.md`](docs/04-test-evidence/m6-deep-audit.md) |
| **GitOps Auto-Rollback** | **19.0 s** from bad commit to healthy | [`m4-gitops.md`](docs/04-test-evidence/m4-gitops.md) |
| **Chaos Experiments** | **5/5 PASS** | [`m5-chaos.md`](docs/04-test-evidence/m5-chaos.md) |
| **External Dependencies** | **0** Python packages | Pure stdlib |

<br>

**Course Project**: SETU SWFW_5S_02 &nbsp;·&nbsp;
**Author**: [Abhishek Kothe (@Abhishek7439)](https://github.com/Abhishek7439) &nbsp;·&nbsp;
**Institution**: YCCE Nagpur &nbsp;·&nbsp;
**Term**: 5th Semester, November 2026

📄 **[Download 18-Page Technical Report (PDF)](report/SETU_SWFW_5S_02_Project_Report.pdf)**

</div>

---

## 🏛️ System Architecture

<p align="center">
  <img src="docs/images/11_diagram_architecture.png" alt="Architecture Diagram" width="900"/>
</p>

```mermaid
flowchart TD
    Client["🖥️ Client / Workload\n(AWS SigV4 S3 API)"] -->|":8080"| Gateway["⚡ HAProxy Gateway\nLayer-7 Health Checks\nSocket Admin (:9999)"]
    
    subgraph RegionA["🟢 Region A — Primary (172.28.10.0/24)"]
        MinioA["MinIO Region A\n(:9000) · minio_a_data"]
    end

    subgraph RegionB["🔵 Region B — Backup (172.28.20.0/24)"]
        MinioB["MinIO Region B\n(:9000) · minio_b_data"]
    end

    subgraph Transit["🌐 WAN Transit (172.28.30.0/24)"]
        Toxi["☠️ Toxiproxy\nLatency · Jitter · Bandwidth · Partitions"]
    end

    Gateway -->|"Primary Path"| MinioA
    Gateway -.->|"Backup Path"| MinioB
    
    MinioA <===>|"Active-Active Replication"| Toxi
    Toxi <===> MinioB

    DR["🛡️ DR Controller\n5-State FSM"] -->|"Socket Fencing"| Gateway
    DR -->|"Health Probing"| MinioA
    DR -->|"Health Probing"| MinioB

    GitOps["🔄 GitOps Reconciler\nPull-Based"] -->|"Reconcile"| Docker["🐳 Docker"]
```

### Core Components

| Component | Technology | Purpose |
|:---|:---|:---|
| **Ingress Gateway** | HAProxy 3.4.7 | Layer-7 health checks, active/backup routing, runtime socket fencing |
| **Object Storage** | MinIO (Chainguard) × 2 | Isolated regions with active-active site replication |
| **WAN Simulator** | Toxiproxy | Unprivileged network fault injection (latency, partitions, bandwidth) |
| **DR Controller** | Python stdlib | 5-state FSM: HEALTHY → DEGRADED → FAILOVER → RECOVERING → FAILBACK |
| **GitOps Engine** | Python stdlib | Pull-based reconciler with syntax validation, health gate, auto-rollback |
| **Proof Engine** | Python stdlib | Fast metadata gate (1.2s) + deep SHA-256 byte-for-byte audit |

---

---

## 🖥️ Live Container Topology & Object Store Dashboards

In addition to programmatic command-line verification, the platform provides live native dashboards confirming multi-region container orchestration, active-active cross-region replication, and object integrity:

<p align="center">
  <img src="docs/images/real/01_docker_topology.png" alt="Docker Container Topology" width="880"/>
  <br>
  <em>Live verification: Multi-region container topology in Docker (minio-a, minio-b, gateway, toxiproxy, and monitor all running and healthy).</em>
</p>

<p align="center">
  <img src="docs/images/real/02_minio_bucket_browser.png" alt="MinIO Object Browser" width="880"/>
  <br>
  <em>Live verification: MinIO Web Console Object Browser showing active-active replicated demo bucket (168 synchronized objects across regions).</em>
</p>

<p align="center">
  <img src="docs/images/real/03_minio_object_metadata.png" alt="MinIO Object Details" width="880"/>
  <br>
  <em>Live verification: MinIO Web Console Object Detail Panel displaying cryptographic ETag, single versioning, and payload integrity.</em>
</p>

---

## 🔥 What Makes This Different?

<table>
<tr>
<td width="50%">

### 🎯 Measured, Not Claimed
Every RTO and RPO number comes from a real execution log, not a design target. The evidence files are immutable and committed.

### 🔐 Cryptographic Failback Gate
No blind failback. The controller fences the dead primary in `MAINT`, continuously checks metadata parity, and un-fences **only** after mathematical proof of data integrity.

### 🧪 Chaos as Code
5 reproducible experiments — crash, freeze, WAN degradation, network partition, deployment failure — each with a hypothesis, measurement, and verdict.

</td>
<td width="50%">

### 🔄 GitOps Without Kubernetes
Pull-based continuous deployment with pre-flight YAML validation, targeted container recreation, active post-apply health gate, and automated rollback to `last_good` in 19 seconds.

### 📦 Zero External Dependencies
Pure Python 3.10+ standard library. AWS SigV4 signing is implemented natively. No `boto3`, no `requests`, no pip install.

### 📝 Scientific Honesty
Every limitation is explicitly stated: eventual consistency, LWW conflicts, surviving-disk assumption, client timeout impact on RTO, simulated WAN.

</td>
</tr>
</table>

---

## 🚨 The Self-Healing Story (End-to-End)

<p align="center">
  <img src="docs/images/12_diagram_dr_state_machine.png" alt="DR State Machine" width="750"/>
  <br>
  <em>Disaster Recovery Finite State Machine — 5 states, deterministic transitions</em>
</p>

```
1. HEALTHY     ▶ Region A serves 100% of writes; replication syncs to Region B
2. DISASTER    ▶ Region A crashes (SIGKILL / docker stop)
3. FAILOVER    ▶ HAProxy detects failure → Controller fences A into MAINT → B serves traffic
                 ⏱️ RTO: 3.4 seconds | 📊 RPO: 0 objects lost
4. ISOLATED    ▶ Region B handles all writes while A is completely fenced out
5. RECOVERING  ▶ Region A restarts but STAYS FENCED — replication must catch up first
6. FAILBACK    ▶ Metadata gate verifies parity in 1.2s → Region A un-fenced → HEALTHY
```

<p align="center">
  <img src="docs/images/03_demo_failover.png" alt="Failover Terminal" width="860"/>
  <br>
  <em>Real terminal output: Automated failover detection, MAINT fencing, and state transition. Rendered from demo/demo-run.log.</em>
</p>

<p align="center">
  <img src="docs/images/04_demo_failback_gate.png" alt="Failback Gate" width="860"/>
  <br>
  <em>Real terminal output: Integrity gate confirming site parity across 143 objects before un-fencing. Rendered from demo/demo-run.log.</em>
</p>

---

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/Abhishek7439/local-multiregion-ha-platform.git
cd local-multiregion-ha-platform

# Pre-flight checks (Docker, Python, memory, ports)
make doctor

# Boot the multi-region platform
make up

# Run the 10-step self-healing demonstration (~1m50s)
make demo          # Exit code 0 = all tests pass

# Run all 5 chaos experiments
make chaos

# Deep cryptographic audit (SHA-256 every object on both sites)
make audit
```

<p align="center">
  <img src="docs/images/01_doctor.png" alt="make doctor" width="860"/>
  <br>
  <em>make doctor — Pre-flight validation: Docker, Python, memory, port availability.</em>
</p>

<p align="center">
  <img src="docs/images/02_compose_ps.png" alt="docker compose ps" width="860"/>
  <br>
  <em>docker compose ps — Healthy multi-region topology (minio-a, minio-b, gateway, toxiproxy, monitor).</em>
</p>

<p align="center">
  <img src="docs/images/05_demo_banner_exit0.png" alt="Demo Exit 0" width="860"/>
  <br>
  <em>make demo — All 10 self-healing stages completed successfully. Exit Code 0.</em>
</p>

---

## 🧪 Chaos Engineering Suite (E1–E5)

```bash
make chaos    # Runs all 5 experiments with automated evidence collection
```

| # | Experiment | Fault Injected | Result | Status |
|:---:|:---|:---|:---|:---:|
| **E1** | **Hard Crash** | `SIGKILL` on primary under 37 req/s | RTO: **3.8–4.7s**, RPO: **0** | ✅ |
| **E2** | **Gray Failure** | `docker pause` (socket freeze) | RTO: **7.2s** (incl. timeout), RPO: **0** | ✅ |
| **E3** | **WAN Degradation** | 500ms latency + 32KB/s bandwidth | Zero dropped writes, lag < **3.5s** | ✅ |
| **E4** | **Network Partition** | Asymmetric one-way A→B split | LWW conflict resolution verified | ✅ |
| **E5** | **Deploy Chaos** | SIGKILL during GitOps apply | Auto-healed in **12.1s** | ✅ |

<p align="center">
  <img src="docs/images/13_chart_rto_e1_e2.png" alt="RTO Chart" width="860"/>
  <br>
  <em>Empirical RTO comparison: Hard crash (E1) vs socket freeze (E2) across 3 sequential runs.</em>
</p>

<details>
<summary><strong>📊 Detailed Chaos Results (click to expand)</strong></summary>
<br>

<p align="center">
  <img src="docs/images/06_chaos_summary_table.png" alt="Chaos Summary" width="860"/>
</p>

<p align="center">
  <img src="docs/images/07_e1_e2_rto_stats.png" alt="E1 E2 RTO Stats" width="860"/>
</p>

<p align="center">
  <img src="docs/images/08_e4_partition_lww.png" alt="E4 Partition" width="860"/>
</p>

</details>

---

## 🔄 GitOps Continuous Delivery

The autonomous reconciler (`gitops/reconciler.py`) implements pull-based continuous deployment:

```
Commit valid config → Reconciler detects → docker compose config validates
→ Targeted container recreated → Health gate probes 3× → ✅ Deployed

Commit broken config → Reconciler detects → docker compose config validates
→ Container recreated → Health gate FAILS → 🔄 Auto-rollback to last_good (19.0s)
```

<p align="center">
  <img src="docs/images/10_gitops_rollback.png" alt="GitOps Rollback" width="860"/>
  <br>
  <em>Autonomous rollback: Broken HAProxy config detected, health gate failed, reverted to last_good.</em>
</p>

---

## 🔐 Cryptographic Deep Audit

```bash
make audit    # SHA-256 every object on both regions
```

Two verification modes:
- **Fast Gate** (routine failback): Metadata + ETag parity in **1.2s** across 143+ objects
- **Deep Audit** (`make audit`): Byte-for-byte SHA-256 — **153/153 objects verified identical**

<p align="center">
  <img src="docs/images/09_deep_audit_json.png" alt="Deep Audit" width="860"/>
  <br>
  <em>make audit — 153 objects verified bit-for-bit identical across both regions (match: true).</em>
</p>

---

## ⚠️ Honest Limitations

> **This project prioritizes intellectual honesty over impressive-sounding claims.**

1. **Eventual consistency (LWW)** — Simultaneous writes to the same key during partition resolve by timestamp; no vector clocks.
2. **Surviving-disk assumption** — RPO 0 was measured with surviving disks at 35–42 writes/s. Disk destruction was not tested.
3. **RTO includes client timeouts** — Gray failure RTO (7.2s) includes the 3.5s HTTP timeout + HAProxy redispatch window.
4. **Asymmetric partition only** — Toxiproxy sits on the A→B path; B→A remained directly connected in E4.
5. **Simulated regions** — Both regions are Docker containers on one Linux kernel. WAN characteristics are injected.
6. **E3 noise** — Combined lag was slightly lower than latency-only; run-to-run variance, no causal claim.

---

## 📁 Repository Map

```
.
├── Makefile                     # make doctor / up / demo / chaos / audit / package
├── docker-compose.yml           # Multi-region infrastructure definition
├── .env.example                 # Credential template (actual .env is gitignored)
│
├── gateway/
│   ├── haproxy.cfg              # Layer-7 LB with health checks & admin socket
│   └── nginx.conf               # Reference M1 config
│
├── controller/
│   ├── dr_controller.py         # 5-state DR finite state machine
│   └── proof.py                 # Integrity gate (fast + deep SHA-256)
│
├── gitops/
│   └── reconciler.py            # Pull-based reconciler with health gate & rollback
│
├── chaos/
│   ├── common.py                # SigV4 client, concurrent writer, Toxiproxy helpers
│   ├── runner.py                # E1–E5 runner with evidence generation
│   └── experiments/             # e1_kill, e2_pause, e3_latency, e4_partition, e5_gitops
│
├── scripts/                     # doctor.sh, demo.sh, mc.sh, build tools
├── report/                      # 18-page PDF report + source HTML
├── demo/                        # DEMO_SCRIPT.md, demo-run.log, README
└── docs/
    ├── 01-decisions.md           # Architectural decisions D1–D12
    ├── 04-test-evidence/         # Immutable proof files (M0–M6)
    ├── 05-runbook.md             # Operator guide & troubleshooting
    ├── 06-reviewer-qa.md         # 15-question technical defense
    └── images/                   # 13 terminal renders & diagrams
```

---

## 📚 Documentation Index

| Document | Contents |
|:---|:---|
| 📄 **[Technical Report (PDF)](report/SETU_SWFW_5S_02_Project_Report.pdf)** | 18-page comprehensive defense document with inline evidence |
| 🏗️ **[Architecture](docs/03-architecture.md)** | System design, network topology, component interactions |
| 📋 **[Decisions (D1–D12)](docs/01-decisions.md)** | Why Docker Compose, HAProxy, Chainguard MinIO, Toxiproxy, stdlib |
| 🔧 **[Runbook](docs/05-runbook.md)** | Operator guide, troubleshooting, real errors encountered |
| 🎤 **[Reviewer Q&A](docs/06-reviewer-qa.md)** | 15 technical defense questions and answers |
| 📊 **[Test Evidence](docs/04-test-evidence/)** | Immutable runtime logs for every milestone (M0–M6) |
| 🎬 **[Demo Script](demo/DEMO_SCRIPT.md)** | Step-by-step narration guide for live demonstration |

---

<div align="center">

**Built with determination, tested with chaos, verified with cryptography.**

*Every number in this README is backed by an evidence file. No invented figures. No hype.*

</div>
