.PHONY: help doctor up down restart ps logs health controller rpo audit gitops-demo demo chaos package

SHELL := /bin/bash

help:
	@echo "Available targets:"
	@echo "  make doctor      - Verify system prerequisites and environment"
	@echo "  make up          - Start all containers in background"
	@echo "  make down        - Stop all containers"
	@echo "  make restart     - Restart all containers"
	@echo "  make ps          - List running services and port bindings"
	@echo "  make health      - Check health endpoints of all regions and gateway"
	@echo "  make controller  - Run the DR controller state machine"
	@echo "  make rpo         - Run independent RPO measurement"
	@echo "  make audit       - Run deep periodic integrity audit (all objects SHA-256)"
	@echo "  make gitops-demo - Run standalone GitOps self-healing & auto-rollback demo"
	@echo "  make demo        - Execute full end-to-end self-healing demo (<10 min)"
	@echo "  make chaos       - Run full 5-experiment chaos engineering suite"
	@echo "  make package     - Build verified submission directory and zip archive (<20 MB)"

doctor:
	@chmod +x scripts/doctor.sh
	@./scripts/doctor.sh

up:
	@docker compose up -d

down:
	@docker compose down

restart:
	@docker compose restart

ps:
	@docker compose ps

health:
	@echo -n "Region A (:9100): " && curl -sf -m 2 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9100/minio/health/live || echo "DOWN"
	@echo -n "Region B (:9200): " && curl -sf -m 2 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9200/minio/health/live || echo "DOWN"
	@echo -n "Gateway  (:8080): " && curl -sf -m 2 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/minio/health/live || echo "DOWN"

controller:
	@python3 controller/dr_controller.py

rpo:
	@python3 controller/proof.py

audit:
	@python3 controller/proof.py compare --deep

gitops-demo:
	@chmod +x scripts/demo-gitops.sh
	@./scripts/demo-gitops.sh

demo:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh

chaos:
	@python3 chaos/runner.py

package:
	@chmod +x scripts/build_submission.sh
	@./scripts/build_submission.sh

