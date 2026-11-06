# Design decisions (be ready to explain every one at the review)

## D1 - Object storage image
Options: official minio/minio (withdrawn), build from source, RustFS, SeaweedFS, Chainguard.
Choice: cgr.dev/chainguard/minio, pinned by digest (not a floating tag).
Reason: Chainguard still publishes a free image. Dated tags are not public, so the pin is the digest pulled on 2026-11-03: sha256:3c60a2a8c4d33409a9bc7a623a7fcbfb4605adc3d89422d2f53b3f673a6e5597. `minio --version` reported RELEASE.2026-10-23T20-06-51Z. Site replication with `mc admin replicate add` succeeded on this build.

## D2 - Region isolation
Each region has its own Docker network and volume; only the "global" network
connects them (this is where I can inject latency/partitions later).

## D3 - Gateway: nginx or HAProxy
Options: nginx 1.27 (passive `max_fails` plus `proxy_next_upstream`) and HAProxy 3.4.7 (active `GET /minio/health/live`).
Choice: HAProxy, image digest sha256:2caaf8b1a1ef67f3f1ea9b721f2821675d3ba4500fb518e23884fecb93e8dbaa. Config is gateway/haproxy.cfg. Region B is a `backup` server.
Reason: On 2026-11-03, with nginx already running, stopping Region A still allowed the first PUT (1218 ms after the stop) and a GET. Restarting nginx while A was stopped did not. The log was `host not found in upstream "minio-a:9000"`, and both PUT and GET got connection refused. HAProxy passed the same stop test: first PUT succeeded, 2447 ms from stop completion to write completion, and the GET returned `m1-haproxy-proof 1` from Region B. After a gateway restart with A still down, HAProxy reached HTTP 200 and the next PUT succeeded. Docs: https://www.haproxy.com/documentation/haproxy-configuration-tutorials/reliability/health-checks/ and https://hub.docker.com/_/haproxy/

## D4 - Project directory
Options: OneDrive path on Windows, /mnt/c inside WSL, Linux home.
Choice: /home/cloud_automator/setu-starter.
Reason: Docker bind mounts and shell scripts are reliable on the Linux filesystem. The brief forbids keeping the project under /mnt/c.

## D5 - Cross-region latency tool
Options: tc netem, Toxiproxy.
Choice: not chosen in M0. Do not install Toxiproxy yet.
Reason: `tc` is installed. As user cloud_automator, `tc qdisc add dev lo root netem delay 1ms` returned `RTNETLINK answers: Operation not permitted`. `sudo -n` asked for a password, so root was not tested. The latency experiment (M5) must re-check with sudo before we pick Toxiproxy.

## D6 - Container memory limits
Options: no limits, or caps sized to the WSL VM.
Choice: MinIO 512 MiB each, gateway 128 MiB, monitor 64 MiB.
Reason: The PC has 16 GB, but this WSL VM only exposes about 7.6 GiB to Docker. Caps stop two MinIO processes from taking the whole VM. `docker inspect` showed Memory=536870912 for each MinIO.

## D7 - DR controller, integrity-based failback, and RPO measurement
Options: keep curl monitor only, add MinIO Python SDK, or use Python's standard library plus existing `scripts/mc.sh`.
Choice: `controller/dr_controller.py` on the Ubuntu host using standard library (`urllib`, `socket`, `hashlib`, `subprocess`). No new packages. States: HEALTHY -> DEGRADED (3 second grace) -> FAILOVER -> RECOVERING -> FAILBACK -> HEALTHY.
Reason: The controller manages automated failover and failback without human intervention. During RECOVERING, it computes integrity checks across both sites via `compare_sites()`. It strictly refuses to transition to FAILBACK until every object matches (`match: true`), ensuring zero silent divergence before traffic returns to primary.

RPO measurement: rpo_objects 0 for graceful stop and SIGKILL, measured with sequential writes ~400 ms apart. NOT measured under burst/concurrent load; async replication lag under load is untested and RPO must not be assumed 0.

Resolved items (fixed in M4):
1. **Controller restart during outage (Fixed in Step 6)**:
   On startup, `dr_controller.py` connects to the HAProxy admin socket (`127.0.0.1:9999`) and reads `show stat`. If `minio-a` is reported in `MAINT`, the controller starts directly in `RECOVERING` (initiating the checksum gate) rather than `HEALTHY`. If the socket is unreachable (e.g. gateway down), it logs `startup_haproxy_check_failed`, initializes in `HEALTHY`, and handles subsequent admin commands with fail-safe `fence_failed` logging.
2. **Permanent divergence deadline (Fixed in Step 6)**:
   Added configurable `--recovering-deadline <seconds>` (default 180s, overridable by `RECOVERING_DEADLINE_SECONDS`). If recovery cannot complete within the deadline due to persistent divergence, it logs `{"event": "recovering_overdue", "elapsed_seconds": ..., "deadline_seconds": ..., "reason": "recovery exceeded deadline without checksum match"}` without paging or premature un-fencing.
3. **Execution Scaling of `compare_sites()` (Fixed in Step 7)**:
   - **Before**: Sequential per-object `mc cat` spawned two Docker containers per object ($O(N)$ container invocations). At 110 objects per site (220 total), each pass took **145.7 seconds**, causing controller event loop blocking and slow failbacks.
   - **After**: Replaced with fast metadata listing comparison (`mc ls --recursive --json`), taking **1.2 seconds** (**123x speedup**, 0 SHA-256 checks on clean data).
   - **ETag Trust Assumption & Mechanics**:
     In S3/MinIO:
     - Single-part uploads produce a plain hex MD5 with no suffix.
     - A `-N` suffix indicates a multipart upload where $N$ is the number of parts (e.g. `-1` indicates a 1-part multipart upload). Because `mc pipe` streams without knowing total length upfront, it uploads via the S3 multipart API, producing an ETag with a `-1` suffix (the MD5 of the part MD5s followed by `-1`).
     - **Strong evidence, not absolute proof**: Matching size + ETag is strong evidence of identical content, but not mathematical proof.
     - **Different part sizes**: Uploading the identical byte stream with different part sizes (or single-part vs multipart) produces different ETags for identical payloads. `compare_sites()` handles this via SHA-256 fallback on differing ETags: if SHA-256 matches, it confirms identical content and proceeds without blocking.
     - **Silent Data Corruption**: The fast path checks metadata only and does **NOT** detect silent corruption (bit rot) of stored data if disk blocks flip while metadata remains unchanged.
     - **Periodic Audit (`make audit` / `--deep`)**: Full SHA-256 verification across every object (`make audit`) reads the raw payload from storage to detect silent data corruption.

Known limits:
1. **Delete marker during outage**: A delete during an outage can hold failback. If an object is deleted on the active site while replication is disconnected, a delete marker is placed on only one site. compare_sites() detects this asymmetry (listing counts differ or an object appears only on one site) and holds failback until replication syncs the delete marker across sites or until manual resolution.
2. **RPO under burst load (scheduled for M5 chaos)**: Untested under concurrent high-throughput write streams; asynchronous replication lag will be stressed during network latency and partition chaos tests.

## D8 - Fencing mechanism and admin socket security
Options: rely purely on HAProxy health checks for traffic routing, or active controller fencing via HAProxy admin socket (`disable server` / `enable server`).
Choice: Active fencing over HAProxy admin stats socket on TCP port 9999.
Reason: Relying only on passive/active health checks allows flapping primaries to immediately receive traffic upon container restart, before replication has completed. The controller fences `minio-a` into `MAINT` during `FAILOVER` and only sends `enable server` after checksum verification passes.
Security: Inside the container HAProxy listens on `ipv4@0.0.0.0:9999 level admin`, but `docker-compose.yml` publishes it strictly to `127.0.0.1:9999:9999` (loopback only). It is never exposed to the external network or LAN.

## D9 - GitOps continuous reconciler, active health gate, rollback, and drift policy
Options: external GitOps agent (ArgoCD/Flux - heavyweight for local Docker), manual compose up, or custom autonomous pull reconciler.
Choice: `gitops/reconciler.py` running continuous polling loop against remote repository.

Design decisions:
1. **Targeted Apply & Volume Safety**:
   The reconciler determines changed services via `git diff --name-only <last_good> <candidate>`. It executes targeted service recreation (e.g. `docker compose up -d --no-deps --force-recreate gateway` when only `gateway/haproxy.cfg` changed). It strictly avoids blanket `--force-recreate` to ensure MinIO storage containers (`minio-a`, `minio-b`) are never restarted or interrupted unless their own Compose definition changes.
2. **Active Health Gate & Rollback**:
   Every candidate commit undergoes two-stage validation:
   - Stage 1 (Pre-flight): `docker compose config` syntax and schema check. Invalid YAML is rejected before touching the stack.
   - Stage 2 (Post-apply active health gate): HTTP probing of `/minio/health/live` on gateway (`:8080`) and backends (`:9100`, `:9200`), plus HAProxy socket verification.
   If the health gate fails within the timeout, the reconciler immediately rolls back the working tree to `last_good`, recreates affected containers, restores HAProxy to operational state, records the failed commit in `bad_commits`, and logs `ROLLBACK`.
3. **State Persistence**:
   `.gitops_state.json` tracks `deployed` (last good commit), `last_processed`, and `bad_commits`. When the reconciler restarts, it loads this state and skips known bad commits immediately (`skip_bad_commit`), preventing restart regression loops.
4. **Drift Policy (Report-Only)**:
   Options: auto-heal (restart out-of-band stopped containers) vs report-only.
   Choice: **Report-Only**.
   Reason: In a disaster recovery platform, containers are stopped intentionally during outages and chaos drills (e.g. DR controller managing failover or chaos engineering in M5). If the GitOps reconciler automatically restarted stopped containers, it would fight the DR controller and chaos tests. The reconciler logs `drift_detected` with `policy: report_only` and leaves container management to the DR controller.
5. **DR Deferral & Socket Unreachable Recovery**:
   - If Region A is fenced in `MAINT` or undergoing recovery, the reconciler logs `deferred` and waits until backends are healthy before deploying changes.
   - If the gateway socket is down but direct storage endpoints (`:9100`, `:9200`) are healthy, the reconciler does not defer indefinitely; it recognizes storage is UP and applies incoming fixes to restore gateway availability.
6. **Worktree & Bind-Mount Isolation**:
   The reconciler executes in a dedicated git worktree (`/tmp/setu-gitops-wt`) so that polling, checking out candidate commits, and rollbacks never modify the developer's working directory (`~/setu-starter` remains clean on `main`).
   Docker Desktop bind mounts retain inode bindings to the worktree path; worktree resets must use `git clean -fd` / `git reset --hard` rather than directory deletion while containers are running.
