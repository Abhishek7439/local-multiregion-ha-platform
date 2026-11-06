# Requirements checklist (from the problem statement)

Statement: simulate two independent regions in Docker on one Linux machine;
provide high availability, automated disaster recovery, continuous deployment
(+ chaos engineering and GitOps per the title).

| # | Requirement | How I will show it | Status |
|---|-------------|--------------------|--------|
| 1 | Two independent regions | Separate networks, volumes, containers | [x] |
| 2 | Data replication A <-> B | MinIO site replication, verified | [x] |
| 3 | High availability | Gateway serves from B when A is down | [x] |
| 4 | Automated DR | Monitor detects failure, acts without me; RTO/RPO measured | [x] |
| 5 | GitOps / continuous deployment | Continuous pull reconciler, active health gate, auto-rollback on bad change, drift report-only (AT5 proven) | [x] |
| 6 | Chaos engineering | Scripted experiments: hypothesis, injection, result | [ ] |
| 7 | Production-style | Logs, runbook, tests, clean repo | [ ] |
| 8 | Documentation | Architecture, decisions, test evidence | [ ] |
