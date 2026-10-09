# Synapse: everyday commands. Run `make` (or `make help`) to list them.

.DEFAULT_GOAL := help
SHELL := /bin/bash

# Service for logs/restart, e.g. `make logs s=worker`; extra arguments, e.g. `make ingest args=--dry-run`
s ?=
args ?=

# Give KEY a value in .env unless it already has one: fill an empty `KEY=` line, or append it.
define set_secret
grep -qE '^$(1)=.+' .env || { \
	if grep -qE '^$(1)=$$' .env; then sed -i "s|^$(1)=$$|$(1)=$(2)|" .env; else echo "$(1)=$(2)" >> .env; fi; \
	echo "Added $(1) to .env"; }
endef

##@ Run locally (no Docker)

run: ## Start the web UI and agent service (http://localhost:3000)
	scripts/run_local.sh

run-ingest: ## Index ./data into the shared library, then start
	scripts/run_local.sh --ingest

run-streamlit: ## Start, plus the legacy Streamlit app on :8501
	scripts/run_local.sh --streamlit

db: env ## Start only PostgreSQL in Docker, for `make run` with DATABASE_TYPE=postgres
	docker compose up -d --wait postgres

worker: ## Start a background indexing worker (needs REDIS_URL and QDRANT_URL in .env)
	cd src && uv run celery -A worker worker -Q ingestion

##@ Docker

up: env ## Build and start everything in Docker (http://localhost:3000)
	docker compose up -d --build --wait
	@echo "Synapse is running: http://localhost:3000"

down: ## Stop the Docker setup (data is kept)
	docker compose down

restart: ## Restart everything, or one service: make restart s=worker
	docker compose restart $(s)

logs: ## Follow logs of everything, or one service: make logs s=worker
	docker compose logs -f --tail=100 $(s)

ps: ## Show the status of each service
	docker compose ps

build: ## Rebuild the Docker images
	docker compose build $(s)

watch: env ## Development mode: rebuild or sync services when code changes
	docker compose watch

reset: ## Delete ALL Docker data (chats, accounts, documents); asks first
	@read -r -p "This deletes all Docker data: Postgres, Qdrant, Redis and uploads. Type 'delete' to continue: " answer; \
	if [ "$$answer" = delete ]; then docker compose down -v; else echo "Cancelled."; fi

##@ Setup

env: ## Create .env from .env.example and add the secrets Docker needs, if missing
	@test -f .env || { cp .env.example .env && echo "Created .env from .env.example; add a model API key to it."; }
	@$(call set_secret,AUTH_SECRET,$$(openssl rand -hex 32))
	@$(call set_secret,POSTGRES_PASSWORD,$$(openssl rand -hex 24))

install: ## Install Python and web UI dependencies
	uv sync --frozen
	cd frontend && npm ci

##@ Development

test: ## Run the Python and web UI tests
	uv run pytest -q
	cd frontend && npm test

lint: ## Lint and type-check Python and the web UI
	uv run ruff check src tests scripts
	uv run ruff format --check src tests scripts
	uv run pyrefly check
	cd frontend && npm run lint && npx tsc --noEmit

format: ## Format Python and web UI code
	uv run ruff format src tests scripts
	cd frontend && npm run format

##@ Documents

ingest: ## Index ./data into the shared library (make ingest args=--dry-run)
	uv run python scripts/ingest.py $(args)

migrate-chroma: ## Copy documents from an old Chroma store into Qdrant (no re-embedding)
	uv run python scripts/migrate_chroma_to_qdrant.py $(args)

##@ Help

help: ## Show this list
	@awk 'BEGIN { FS = ":.*## "; print "Usage: make <command>" } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } \
		/^[a-zA-Z_-]+:.*## / { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

.PHONY: run run-ingest run-streamlit db worker up down restart logs ps build watch reset env install \
	test lint format ingest migrate-chroma help
