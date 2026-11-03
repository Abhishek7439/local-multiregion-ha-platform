# SWFW_5S_02 - Local Multi-Region HA Data Platform

Two simulated regions (Docker), replicated object storage, a failover gateway,
a health monitor. GitOps + chaos come next (see docs/00-requirements-checklist.md).

## Prerequisites
Ubuntu 22.04/24.04 (or WSL2 / Ubuntu VM), Docker Engine + Compose v2, git.

## Run
    cp .env.example .env
    docker compose up -d
    docker compose ps
    ./scripts/01-setup-replication.sh
    ./scripts/02-demo-failover.sh
    docker compose logs -f monitor

## Endpoints
- Gateway (use this): http://localhost:8080
- Region A console: http://localhost:9101   API: 9100
- Region B console: http://localhost:9201   API: 9200

## Note
This scaffold has not been run on your machine yet. If a container exits:
`docker compose logs <service>` and fix/ask. First run is the real test.
