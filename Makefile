# ==========================================================================
# Atlas — operator workflow
# Usage: make <target>   (see `make help`)
# ==========================================================================

.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help setup up down logs ps \
        gateway-check \
        vault-bootstrap vault-sync vault-check \
        convex-key check-commits check-compose

help: ## Show this help message
	@echo "Atlas — operator workflow"
	@echo "Usage: make <target>"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

## ---- Bootstrap ------------------------------------------------------------

setup: ## Preflight, install guard hooks, resolve secrets into .env
	bash scripts/setup.sh

## ---- Core platform (Gitea + Convex + dashboard) --------------------------

up: ## Start the Atlas core: Gitea, self-hosted Convex, Convex dashboard
	docker compose up -d

down: ## Stop the Atlas core (keeps volumes)
	docker compose down

logs: ## Tail logs from the Atlas core
	docker compose logs -f

ps: ## List service status
	docker compose ps

## ---- Profiles -------------------------------------------------------------

gateway-check: ## Verify the shared OmniRoute on Zeus (mesh) is reachable
	@echo "Checking OmniRoute at $$(grep OMNIROUTE_BASE_URL .env | cut -d= -f2)..."
	@curl -sf --max-time 5 "$$(grep OMNIROUTE_BASE_URL .env | cut -d= -f2)/models" >/dev/null \
	  && echo "OmniRoute reachable" || echo "OmniRoute NOT reachable — start Zeus Group 2"

## Chef is retired as a builder (convergence plan §2/§8): the `chef` profile,
## its provisioner, and the `chef-up`/`chef-down` targets are gone. Atlas keeps
## Convex, which stays a deploy target for apps the builder produces; the record
## of the Chef work lives in chef-provisioner/ and docs/chef-auth-fork.md.

## ---- Secrets (Cerulean Vault) ---------------------------------------------

vault-bootstrap: ## Seed this stack's generated secrets in Cerulean Vault (unions; never rotates)
	python3 scripts/vault-bootstrap.py

vault-sync: ## Materialize the .env vault:// references from Cerulean Vault
	python3 scripts/vault-resolve.py --file .env --write

vault-check: ## Verify every .env vault:// reference resolves (writes nothing)
	python3 scripts/vault-resolve.py --file .env --check

## ---- Operations -----------------------------------------------------------

convex-key: ## Generate a fresh Convex admin key from the running backend
	@docker compose exec convex ./generate_admin_key.sh

## ---- Checks ---------------------------------------------------------------

check-commits: ## Reject generated attribution text in reachable commit messages
	bash scripts/check-commit-messages.sh

check-compose: ## Validate the compose file parses
	docker compose config --quiet