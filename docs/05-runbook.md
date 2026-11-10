# Platform Operations Runbook

## 1. System Prerequisites

The platform is designed to execute on any standard Linux environment (Ubuntu 22.04 LTS or 24.04 LTS recommended) with the following tools installed:

| Tool | Minimum Version | Required? | Purpose |
|:---|:---|:---:|:---|
| **Docker Engine** | 24.0+ | Yes | Runs isolated region containers, gateway, and networks |
| **Docker Compose** | v2.20+ | Yes | Multi-container lifecycle orchestration |
| **Python** | 3.10+ | Yes | Executes DR controller, GitOps reconciler, and chaos suite |
| **GNU Make** | 4.0+ | Yes | Standard developer interface (`make doctor`, `make demo`, etc.) |
| **Curl** | 7.80+ | Yes | Used in scripts and health verification probes |
| **Git** | 2.34+ | Yes | Version control and GitOps worktree operations |
| **Socat** | Any | Optional | Administrative CLI for HAProxy socket (fallback via Python socket) |

### Tested Environments
- **Primary Tested Environment**: Ubuntu 24.04 LTS running on Windows Subsystem for Linux (WSL2), Linux Kernel 5.15.167.4-microsoft-standard-WSL2, Docker Engine 29.9.2, Docker Compose v2.32.4.
- **Clean-Machine Rehearsal**: Executed locally in throwaway projects (`COMPOSE_PROJECT_NAME=setu-fresh-test`) with fresh volumes. True bare-metal / clean-machine independent evaluation is pending student/evaluator execution.

---

## 2. Standard Operational Lifecycle

### 2.1 Initialization & Environment Configuration
```bash
# 1. Clone repository
git clone https://github.com/Abhishek7439/setu-starter.git
cd setu-starter

# 2. Initialize environment file from example
cp .env.example .env

# 3. Validate system prerequisites
make doctor
```

### 2.2 Starting and Stopping the Platform
```bash
# Start all containers in background
make up

# Check service health and port mappings
make ps
make health

# Gracefully stop containers (preserves all data volumes)
make down

# Restart running containers
make restart
```

> [!CAUTION]
> Never execute `docker compose down -v` on the main project. The `-v` flag permanently destroys the `minio_a_data` and `minio_b_data` storage volumes!

---

## 3. Core Operational Workflows

### 3.1 One-Command Demonstration (`make demo`)
Executes the full 10-step self-healing and continuous delivery validation:
```bash
make demo
```
**Sequence Executed**:
1. Verifies HTTP 200 on all endpoints (`:9100`, `:9200`, `:8080`).
2. Confirms active replication across regions with identical SHA-256 hashes.
3. Spawns background DR controller (`PID`).
4. Injects disaster by stopping `minio-a`.
5. Verifies failover to `minio-b`, measures RTO, and verifies `minio-a` is fenced (`MAINT`).
6. Restarts `minio-a`, observes checksum gating in `RECOVERING`, and verifies automatic failback to `UP`.
7. Stops controller and executes independent numbered RPO measurement stream under graceful stop and SIGKILL.
8. Cleans ephemeral test buckets.
9. Executes standalone GitOps demonstration: auto-deploys valid configuration; pushes broken configuration, detects health gate failure, and automatically rolls back stack to `last_good`.

### 3.2 Running the Chaos Engineering Suite (`make chaos`)
```bash
make chaos
```
Executes all 5 resilience experiments sequentially and saves the empirical report to `docs/04-test-evidence/m5-chaos.md`:
- `E1`: Abrupt crash (SIGKILL `minio-a`) under concurrent write load (~35–45 req/s).
- `E2`: Gray failure (`docker pause minio-a`) socket freeze measuring client timeout impact.
- `E3`: WAN latency (500ms) and bandwidth (32KB/s) injection via Toxiproxy.
- `E4`: Asymmetric one-way network partition (A->B cut via Toxiproxy :9002, B->A direct) with concurrent writes and Last-Write-Wins conflict resolution.
- `E5`: Active gateway container termination during GitOps continuous deployment health gate.

### 3.3 Integrity Audit (`make audit`)
```bash
make audit
```
Executes a deep cryptographic checksum audit (`compare_sites --deep`). Unlike the fast-path listing comparison, `--deep` streams the raw bytes of every stored object from both sites and computes full SHA-256 digests to detect silent disk corruption (bit rot).

---

## 4. Real Troubleshooting & Field Issues Encountered

During the development and testing of Milestones M0 through M5, several subtle real-world failure modes were encountered and resolved. These are documented below for operators:

### Issue 1: Unprivileged `tc` Network Emulation Fails (`Operation not permitted`)
- **Symptom**: Running `tc qdisc add dev eth0 root netem delay 50ms` on the host fails with `RTNETLINK answers: Operation not permitted`.
- **Root Cause**: Linux network namespace manipulation requires the `CAP_NET_ADMIN` kernel capability. Non-root users inside WSL2 or standard containers cannot modify host traffic control queues.
- **Fix / Resolution**: Adopted **Toxiproxy v2.9.0** running as a dedicated service on the `setu_global` bridge network. Toxiproxy operates entirely in user-space, manipulating TCP streams via standard socket I/O without requiring root permissions or kernel capabilities.

### Issue 2: Stale Bind-Mount Cache After Multi-Project Execution
- **Symptom**: After running a throwaway project on the same Docker daemon, restarting the main stack's gateway failed with `OCI runtime create failed: ... no such file or directory: ./gateway/haproxy.cfg`.
- **Root Cause**: Docker daemon cached the bind-mount inode from the temporary directory, pointing to an unlinked file descriptor.
- **Fix**: Use targeted force-recreation to refresh container bind-mounts:
  ```bash
  docker compose up -d --force-recreate gateway
  ```

### Issue 3: MinIO Client (`mc`) TTY Hang During Automated Scripting
- **Symptom**: Commands such as `mc admin replicate resync status` failed with `Unable to get resync status: could not open a new TTY: open /dev/tty: no such device or address`.
- **Root Cause**: `mc` attempts to open an interactive pager by default when standard output is not attached to a terminal.
- **Fix**: Pass the `--json` flag or `--disable-pager` to all headless `mc` calls (e.g. `mc --json admin replicate ...`).

### Issue 4: RPO Measurement Silently Returning Empty Inventory
- **Symptom**: Early chaos runs reported massive false data loss (`RPO_after_return: 420 objects lost`) even though both MinIO instances were completely healthy.
- **Root Cause**: In `chaos/common.py`, `import json` was omitted from the top of the file. Inside `get_bucket_inventory()`, `json.loads()` threw a `NameError`, which was caught by a blanket `except Exception:` block, causing the function to silently return an empty dictionary `{}`.
- **Fix**: Added explicit `import json` and structured error logging.

### Issue 5: Compose Project Name Collision During Rehearsal
- **Symptom**: Starting a trial project in `/tmp/setu-trial` stopped or interfered with containers running in `~/setu-starter`.
- **Root Cause**: Both directories had `name: setu-multiregion` specified in `docker-compose.yml`. Docker Compose v2 prioritizes the top-level `name:` key over directory names.
- **Fix**: Override the project name explicitly via `name: ${COMPOSE_PROJECT_NAME:-setu-multiregion}` and export `COMPOSE_PROJECT_NAME=setu-fresh-test` during rehearsals.

### Issue 6: E2 Gray Failure RTO Variance
- **Symptom**: RTO during `docker pause` clustered bimodally around either ~3.6s or ~7.2s.
- **Root Cause**: Paused sockets do not return TCP RST. Client worker threads with a 2.0s timeout timed out before HAProxy's 2-second connect timeout and redispatch completed.
- **Fix**: Tuned client request timeout to **3.5 seconds** in `e2_pause.py` (allowing HAProxy 2.0s connect timeout + redispatch to complete gracefully).

