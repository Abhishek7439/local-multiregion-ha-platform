# Reviewer Technical Defense & Examination Q&A

**Candidate**: Abhishek Kothe (`Abhishek7439`)  
**Project**: SETU SWFW_5S_02: Local Multi-Region Highly Available Data Platform  
**Target Review**: Zoho Campus Offline Review, November 2026  

---

### Q1: What is the consistency model of this platform?
**Answer**: Active-active eventual consistency. When an object is written to Region A, it is committed locally and acknowledged to the client, then asynchronously replicated across the transit network to Region B. If identical object keys are written simultaneously on both sides, MinIO resolves the conflict via timestamp-based **Last-Write-Wins (LWW)**.

### Q2: How does the system prevent split-brain during a network partition or failover?
**Answer**: Through ingress fencing. The DR controller issues `set server minio_api/minio-a state maint` to HAProxy's admin socket upon failover. This locks Region A out of receiving any incoming client traffic. Even if Region A's process remains partially alive or restarts prematurely, clients can only write to Region B. Region A is never un-fenced until cryptographic parity is verified.

### Q3: How exactly are RTO and RPO defined and measured in this codebase?
**Answer**:
- **RTO (Recovery Time Objective)**: Measured from the first failed health check on primary until the first successful write acknowledged on backup (`minio-b`). Includes the 3-second grace window (configured to prevent flapping) plus the write probe time (~400–600ms).
- **RPO (Recovery Point Objective)**: Measured by issuing numbered write streams (`write-00001.txt` ... `write-00400.txt`) during disaster injection. We count acknowledged writes missing on Region B at failover (`RPO_failover`) and permanently lost after recovery (`RPO_after_return`).

### Q4: Why was HAProxy chosen over Nginx as the ingress gateway?
**Answer**: We tested both in Milestone M1. Nginx failed when restarted while Region A was down (`host not found in upstream "minio-a:9000"`), resulting in total gateway failure. HAProxy survived because it resolves DNS dynamically and provides active layer-7 health checks (`/minio/health/live`). Furthermore, HAProxy provides a live administrative UNIX/TCP socket for instant zero-reload runtime server fencing.

### Q5: Why was Kubernetes not used for this project?
**Answer**: The project constraint specifies a lightweight, deterministic platform running locally on standard Linux (WSL2/Ubuntu) with 16 GB host RAM. Kubernetes introduces significant resource overhead (~2–4 GB just for control plane components), nondeterministic reconciliation timing, and abstracted networking that obscures fundamental distributed systems failure modes. Using Docker Compose with standard POSIX scripting makes every failure mode inspectable and student-explainable.

### Q6: Why did you use Toxiproxy instead of Linux Traffic Control (`tc netem`)?
**Answer**: We tested `tc` in Milestone M5; executing `tc qdisc add` on the host returned `Operation not permitted` because network namespace manipulation requires `CAP_NET_ADMIN` root capabilities. Toxiproxy operates entirely in user-space as an application proxy on port 9002. It allows programmatic REST API control over latency, bandwidth, and timeouts with bidirectional granularity (upstream vs. downstream), without requiring root privileges or host kernel modifications.

### Q7: What happens if both Region A and Region B die simultaneously?
**Answer**: In a total catastrophe, the platform becomes unavailable. HAProxy returns HTTP 503 (`Service Unavailable`), and the DR controller transitions to `DEGRADED` or logs that all backends are unreachable. However, data persistence is maintained: both `minio_a_data` and `minio_b_data` are Docker named volumes backed by the host filesystem, so all previously committed data survives and becomes accessible once containers restart.

### Q8: How does the platform detect silent data corruption (bit rot)?
**Answer**: Through the periodic audit engine (`make audit` or `python3 controller/proof.py compare --deep`). The fast-path failback check inspects object metadata and ETags for speed (1.2s across 140+ objects). However, `make audit` downloads the raw payload of every single object on both sites and computes cryptographic SHA-256 digests, detecting any silent block corruption that metadata checks would miss.

### Q9: How does the DR controller decide that Region A is safe for failback?
**Answer**: When Region A restarts, the controller enters `RECOVERING`. It refuses to fail back until `compare_sites()` returns `match: true`. This ensures all writes accepted by Region B while Region A was dead have completely synchronized back to Region A. Only when object counts and digests match does the controller send `set server minio_api/minio-a state ready` to HAProxy.

### Q10: Why was the RTO during `docker pause` (~7.2s) longer than `SIGKILL` (~4.7s)?
**Answer**: When `SIGKILL` terminates a container, the operating system kernel immediately tears down the socket and issues TCP RST packets, allowing HAProxy to instantly recognize connection termination. In contrast, `docker pause` freezes process execution without closing sockets or sending RST. In-flight client requests must wait for the client timeout (3.5s) and HAProxy's connect timeout (2.0s) + redispatch to fire, resulting in a ~7.2s transition.

### Q11: How does the GitOps continuous reconciler prevent deploying broken code?
**Answer**: Through a two-stage gate. First, pre-flight syntax validation (`docker compose config`) rejects malformed YAML before touching running containers. Second, after applying a targeted change, the reconciler evaluates an active post-apply health gate checking HTTP 200 on all endpoints. If any check fails within 15 seconds, it automatically reverts the worktree to `last_good`, recreates the container, and blacklists the faulty commit in `.gitops_state.json`.

### Q12: Can an asymmetric network partition cause permanent data loss?
**Answer**: For independent object keys, no: writes made to either site during a partition are queued in MinIO's replication log and automatically replicate once the link heals (proven in Experiment E4: 20 partition writes synced in 4.91s). For conflicting writes (identical key modified on both sides during the cut), MinIO applies Last-Write-Wins; the object with the latest UTC timestamp wins, and the older version is superseded.

### Q13: Why did you implement a custom AWS SigV4 client instead of importing `boto3`?
**Answer**: To adhere strictly to the project constraint of **zero third-party dependencies**. `boto3` and `botocore` introduce hundreds of megabytes of external dependencies and transitive wheels. By implementing standard AWS Signature Version 4 HMAC-SHA256 signing using Python's standard `hashlib`, `hmac`, and `urllib`, the entire codebase runs out-of-the-box on any standard Python 3.10+ Linux install.

### Q14: How are secrets and credentials handled in this repository?
**Answer**: Dynamic environment injection. Sensitive values (`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`) are stored in `.env` (ignored by `.gitignore`). All Python modules call `get_credentials()` or `load_env()` to read from `os.environ`. Default fallback values exist only for clean automated testing, and no secrets or private keys exist anywhere in git history.

### Q15: How does this codebase prove it meets SETU SWFW_5S_02 requirements?
**Answer**: Every requirement from the course brief is backed by executable code and immutable test evidence:
- AT1 (Multi-region health): HTTP 200 verified on all endpoints.
- AT2 (Replication): Verified SHA-256 match across regions.
- AT3 (Automated Failover & RTO): Measured under graceful stop and SIGKILL.
- AT4 (Automated Failback & Parity): Gated by cryptographic compare.
- AT5 (GitOps Continuous Delivery): Proven auto-apply and auto-rollback.
- AT6 & AT7 (Chaos Engineering & Resilience): 5 experiments validated in `make chaos`.
- Single command `make demo` runs the full lifecycle in under 2 minutes with exit code 0.
