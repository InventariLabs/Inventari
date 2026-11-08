.PHONY: help setup setup-hooks dev-up dev-up-full up down deploy backup-key backup-verify backup-status status logs logs-backend logs-frontend lint check-commit-messages audit lint-frontend check-frontend perf-phone check-audit-fields-fresh lint-architecture typecheck validate-module module-smoke new-module new-community-module format frontend-format test test-backend test-frontend test-e2e e2e-example-module test-e2e-ui test-unit test-integration test-coverage check-diff-coverage mutate-stock test-fast test-profile clean clean-test db-migrate db-upgrade db-reset db-seed db-seed-demo db-seed-clean demo-reset release-db-snapshot shell db-shell scan-dead create-admin off-import off-count generate-api-docs check-openapi-fresh loadtest-seed seed-scale measure-scale

# Default goal
.DEFAULT_GOAL := help

# Docker configuration
DOCKER_COMPOSE := docker compose

# One source of truth for the development admin account. `dev-up`, the isolated
# dev2 stack and the E2E suite all read it, and the password must satisfy the
# same policy the API enforces — an account the CLI can create but the login
# screen refuses is a login that does not work.
DEV_ADMIN_EMAIL ?= admin@example.com
DEV_ADMIN_PASSWORD ?= Admin123
BACKEND_EXEC := $(DOCKER_COMPOSE) exec backend
# pytest-xdist workers for the backend test targets, read from this machine's
# cores and free memory by scripts/test-workers.py — the same script CI and
# the Playwright config ask, so no suite assumes the hardware of another. The
# containers have no CPU limit, so `-n auto` would take every core. Override
# per run: `make test-coverage PYTEST_WORKERS=4`.
PYTEST_WORKERS ?= $(shell python3 scripts/test-workers.py pytest)

# Colors
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
RED := \033[0;31m
NC := \033[0m # No Color

##@ Bootstrap

dev-up: ## One-command bootstrap (env + build + migrate + seed system data + admin, verified)
	@echo "$(BLUE)[BOOTSTRAP]$(NC) Checking prerequisites..."
	@command -v docker >/dev/null 2>&1 || { echo "$(RED)[ERROR]$(NC) Docker not installed"; exit 1; }
	@# `command -v docker compose` would only test the first word, i.e. docker
	@# again — this asks the plugin itself what the recipes actually invoke.
	@docker compose version >/dev/null 2>&1 || { echo "$(RED)[ERROR]$(NC) Docker Compose plugin not installed"; exit 1; }
	@command -v curl >/dev/null 2>&1 || { echo "$(RED)[ERROR]$(NC) curl not installed - the bootstrap uses it to verify the app answers"; exit 1; }
	@command -v openssl >/dev/null 2>&1 || { echo "$(RED)[ERROR]$(NC) openssl not installed - dev-up generates SECRET_KEY and FERNET_SALT with it; a missing one would silently write empty secrets into .env"; exit 1; }
	@echo "$(BLUE)[BOOTSTRAP]$(NC) Generating .env if missing..."
	@if [ ! -f .env ]; then \
		cp .env.example .env && \
		sed -i.bak "s/change-me-strong-password/dev-password-local-only/" .env && \
		sed -i.bak "s/^SECRET_KEY=change-me-generate-with-openssl-rand-hex-32/SECRET_KEY=$$(openssl rand -hex 32)/" .env && \
		sed -i.bak "s/^FERNET_SALT=change-me-generate-with-openssl-rand-hex-32/FERNET_SALT=$$(openssl rand -hex 32)/" .env && \
		sed -i.bak "s/^ENCRYPTION_KEY=$$/ENCRYPTION_KEY=$$(openssl rand -hex 32)/" .env && \
		sed -i.bak "s/^SMTP_HOST=$$/SMTP_HOST=mailhog/" .env && \
		sed -i.bak "s/^SMTP_PORT=587$$/SMTP_PORT=1025/" .env && \
		sed -i.bak "s/^SMTP_USER=$$/SMTP_USER=dev/" .env && \
		sed -i.bak "s/^SMTP_PASSWORD=$$/SMTP_PASSWORD=dev/" .env && \
		sed -i.bak "s/^DEBUG=false$$/DEBUG=true/" .env && \
		rm -f .env.bak && \
		echo "$(GREEN)[OK]$(NC) .env created with dev defaults"; \
	else \
		echo "$(GREEN)[OK]$(NC) .env already exists, skipping"; \
	fi
	@echo "$(BLUE)[BOOTSTRAP]$(NC) Starting containers..."
	$(DOCKER_COMPOSE) up --build -d
	@echo "$(BLUE)[BOOTSTRAP]$(NC) Waiting for database..."
	@n=0; until $(DOCKER_COMPOSE) exec -T db pg_isready -U inventari_user >/dev/null 2>&1 || [ $$n -ge 30 ]; do n=$$((n+1)); sleep 1; done
	@echo "$(BLUE)[BOOTSTRAP]$(NC) Running migrations (core + modules)..."
	$(BACKEND_EXEC) uv run python manage.py db upgrade
	@echo "$(BLUE)[BOOTSTRAP]$(NC) Seeding system data..."
	$(BACKEND_EXEC) uv run python manage.py db seed
	@echo "$(BLUE)[BOOTSTRAP]$(NC) Creating default admin user..."
	$(BACKEND_EXEC) uv run python manage.py user create-admin --email "$(DEV_ADMIN_EMAIL)" --password "$(DEV_ADMIN_PASSWORD)" --name "Admin"
	@echo "$(BLUE)[BOOTSTRAP]$(NC) Waiting for the app to answer..."
	@fail=0; \
	for probe in "backend 8000 /health" "frontend 5173 /"; do \
		set -- $$probe; \
		addr=$$($(DOCKER_COMPOSE) port $$1 $$2 2>/dev/null | head -1 | sed 's/0\.0\.0\.0/localhost/; s/\[::\]/localhost/'); \
		if [ -z "$$addr" ]; then \
			echo "$(RED)[ERROR]$(NC) $$1 has no published port - it is most likely not running:"; \
			$(DOCKER_COMPOSE) ps $$1 2>&1 | sed "s/^/    /"; \
			$(DOCKER_COMPOSE) logs --tail 20 --no-color $$1 2>&1 | sed "s/^/    /"; \
			fail=1; continue; \
		fi; \
		n=0; \
		until curl -sfo /dev/null "http://$$addr$$3" || [ $$n -ge 60 ]; do n=$$((n+1)); sleep 1; done; \
		if [ $$n -ge 60 ]; then \
			echo "$(RED)[ERROR]$(NC) $$1 never answered on http://$$addr$$3 (60s). Its last lines:"; \
			$(DOCKER_COMPOSE) logs --tail 20 --no-color $$1 2>&1 | sed "s/^/    /"; \
			fail=1; \
		else \
			echo "$(GREEN)[OK]$(NC) $$1 answers on http://$$addr$$3"; \
		fi; \
	done; \
	if [ $$fail -ne 0 ]; then \
		echo "$(RED)[ERROR]$(NC) The containers are up but the application does not answer - not reporting success."; \
		exit 1; \
	fi
	@echo ""
	@app=$$($(DOCKER_COMPOSE) port frontend 5173 2>/dev/null | head -1 | sed 's/0\.0\.0\.0/localhost/; s/\[::\]/localhost/'); \
	api=$$($(DOCKER_COMPOSE) port backend 8000 2>/dev/null | head -1 | sed 's/0\.0\.0\.0/localhost/; s/\[::\]/localhost/'); \
	mail=$$($(DOCKER_COMPOSE) port mailhog 8025 2>/dev/null | head -1 | sed 's/0\.0\.0\.0/localhost/; s/\[::\]/localhost/'); \
	echo "$(GREEN)Inventari is ready!$(NC)"; \
	echo "$(GREEN)  App:     http://$$app$(NC)"; \
	echo "$(GREEN)  API:     http://$$api/docs$(NC)"; \
	if [ -n "$$mail" ]; then echo "$(GREEN)  Mailhog: http://$$mail$(NC)"; fi; \
	echo "$(GREEN)  Login:   $(DEV_ADMIN_EMAIL) / $(DEV_ADMIN_PASSWORD)$(NC)"

dev-up-full: dev-up ## Bootstrap plus the food products database (starts empty: make off-import fills it, see docs/OFF_DATABASE_SETUP.md)
	@echo "$(BLUE)[BOOTSTRAP]$(NC) Starting food module containers..."
	$(DOCKER_COMPOSE) --profile food up -d
	@echo "$(GREEN)[OK]$(NC) Food module containers started. The products database starts empty:"
	@echo "     download the Open Food Facts file (docs/OFF_DATABASE_SETUP.md), then make off-import FILE=/path/to/food.parquet"

##@ Daily use

up: ## Start all containers (dev mode)
	$(DOCKER_COMPOSE) up -d

down: ## Stop all containers
	$(DOCKER_COMPOSE) down

deploy: ## Deploy to production (build + recreate containers)
	@echo "$(BLUE)[INFO]$(NC) Deploying to production..."
	@docker compose -f docker-compose.prod.yml build --parallel
	@docker compose -f docker-compose.prod.yml up -d --force-recreate --no-build
	@echo "$(GREEN)[OK]$(NC) Deployment complete."

backup-key: ## Make the key pair that encrypts prod backups (prints the private key once; keep it off the server)
	@sh scripts/backup-key.sh

backup-verify: ## Prove the newest prod backup restores (encrypted: pipe the private key in on stdin)
	@docker compose -f docker-compose.prod.yml run --rm $$([ -t 0 ] || echo -T) --entrypoint verify.sh db-backup

backup-status: ## Prod backups: encryption on/off, newest backup, when a restore was last proven
	@docker compose -f docker-compose.prod.yml run --rm -T --no-deps --entrypoint status.sh db-backup

status: ## Show container status and recent logs
	@echo "$(BLUE)[INFO]$(NC) Container status:"
	@$(DOCKER_COMPOSE) ps || true
	@echo ""
	@echo "$(BLUE)[INFO]$(NC) Recent logs (last 20 lines):"
	@$(DOCKER_COMPOSE) logs --tail=20

logs: ## Follow all container logs
	$(DOCKER_COMPOSE) logs -f

logs-backend: ## Follow backend logs only
	$(DOCKER_COMPOSE) logs -f backend

logs-frontend: ## Follow frontend logs only
	$(DOCKER_COMPOSE) logs -f frontend

help: ## Display help
	@echo "$(BLUE)Available targets:$(NC)"
	@awk 'BEGIN {FS = ":.*##"} \
		/^##@ / { printf "\n$(YELLOW)%s$(NC)\n", substr($$0, 5); next } \
		/^[a-zA-Z0-9_-]+:.*##/ { printf "  $(GREEN)%-22s$(NC) %s\n", $$1, $$2 }' \
		$(MAKEFILE_LIST)
	@echo ""
	@echo "$(YELLOW)Usage examples:$(NC)"
	@echo "  make lint"
	@echo "  make format"
	@echo "  make test"
	@echo ""

##@ Quality gates

# Notes on two steps of the recipe below, kept here because a comment inside a
# recipe is echoed by make before every run.
# Documentation paths: runs on the host as well as in the container; here the
# checkout is complete without a mount, and in the container the pytest test of
# the same name reads the repository docker-compose.yml mounts for it. See
# check_docs_paths.py.
# Internal ids: scans the whole public tree, tests, migrations, scripts and data
# files included; the roots are computed by public_tree_roots() in
# check_internal_ids.py so this target and the unit test read the same set.
lint: ## Check code style with ruff
	@echo "$(BLUE)[INFO]$(NC) Checking code style with ruff..."
	$(BACKEND_EXEC) uv run ruff check .
	@echo "$(BLUE)[INFO]$(NC) Checking code formatting with ruff..."
	$(BACKEND_EXEC) uv run ruff format --check .
	@echo "$(BLUE)[INFO]$(NC) Checking architecture boundaries..."
	$(BACKEND_EXEC) uv run python manage.py arch lint --quiet
	@echo "$(BLUE)[INFO]$(NC) Checking dead code (vulture, baseline)..."
	$(BACKEND_EXEC) uv run python scripts/check_vulture_baseline.py
	@echo "$(BLUE)[INFO]$(NC) Checking types (mypy, baseline)..."
	$(BACKEND_EXEC) uv run python scripts/check_mypy_baseline.py
	@echo "$(BLUE)[INFO]$(NC) Checking licence report freshness..."
	@python3 backend/scripts/check_licences_fresh.py
	@echo "$(BLUE)[INFO]$(NC) Checking that every import under app/ is a declared dependency..."
	$(BACKEND_EXEC) uv run python scripts/check_declared_imports.py
	@echo "$(BLUE)[INFO]$(NC) Checking module purpose cards..."
	@python3 backend/scripts/check_purpose_cards.py
	@echo "$(BLUE)[INFO]$(NC) Checking the edge forwards /public/* and keeps its security headers..."
	@python3 backend/scripts/check_edge_public_routes.py
	@echo "$(BLUE)[INFO]$(NC) Checking documentation paths..."
	@python3 backend/scripts/check_docs_paths.py
	@echo "$(BLUE)[INFO]$(NC) Checking the test worker budget (CPU and memory limits)..."
	@python3 scripts/test_test_workers.py
	@echo "$(BLUE)[INFO]$(NC) Checking for identifiers that point at private material..."
	@python3 backend/scripts/check_internal_ids.py --public-tree
	@$(MAKE) --no-print-directory audit

# The messages of the commits a push would publish, read by the same rules the
# commit-msg hook applies when each one is made: it catches a commit made where
# the hook was not installed, or with --no-verify. RANGE defaults to what the
# branch adds on top of dev.
RANGE ?= origin/dev..HEAD
check-commit-messages: ## Check the messages of the commits a push would publish (RANGE=origin/dev..HEAD)
	@python3 backend/scripts/check_internal_ids.py --commits "$(RANGE)"

# The local equivalent of ci.yml's "Dependency audit". It used to run only
# there, and it was red on dev — `weasyprint 69.0` carried PYSEC-2026-3940 and
# GHSA-jf6q-chmf-3h3v — so it stood outside `make lint`: a gate wired in while
# red stops every commit without protecting anything. The weasyprint bump to
# 70.0 cleared it and this target joined `make lint` above.
#
# Measured on this branch, one command either way: `make audit` exits 2 with
# `weasyprint>=69.0` in pyproject.toml, and 0 with the bump. It reads
# `uv.lock`, so the gate reports the resolution rather than what a running
# container happens to have installed — a bumped lock is enough here, while
# the application itself needs `docker compose up -d --build backend`
# (README, "Changed backend dependencies?").
audit: ## Audit dependencies for known vulnerabilities (uv audit)
	@echo "$(BLUE)[INFO]$(NC) Auditing dependencies (uv audit)..."
	$(BACKEND_EXEC) uv audit

lint-frontend: ## Check frontend code style with eslint
	@echo "$(BLUE)[INFO]$(NC) Checking frontend code style with eslint..."
	docker compose exec frontend npm run lint

check-frontend: ## Run frontend eslint + prettier, typecheck + production build, and the baseline gates
	@echo "$(BLUE)[INFO]$(NC) Checking frontend code style with eslint (the pre-commit hook's copy)..."
	docker compose exec frontend npm run lint
	@echo "$(BLUE)[INFO]$(NC) Checking frontend formatting with prettier (the pre-commit hook's copy)..."
	docker compose exec frontend npm run format:check
	@echo "$(BLUE)[INFO]$(NC) Running frontend typecheck + production build..."
	docker compose exec frontend npm run build:check
	@echo "$(BLUE)[INFO]$(NC) Checking i18n key usage against catalogs..."
	docker compose exec frontend npm run check:i18n
	@echo "$(BLUE)[INFO]$(NC) Checking orphan i18n keys (unused, baseline)..."
	docker compose exec frontend npm run check:i18n:unused
	@echo "$(BLUE)[INFO]$(NC) Checking every journal field name has a translation (baseline)..."
	docker compose exec frontend npm run check:audit-fields
	@$(MAKE) --no-print-directory check-audit-fields-fresh
	@echo "$(BLUE)[INFO]$(NC) Checking the English catalogs spell it one way..."
	docker compose exec frontend npm run check:en-spelling
	@echo "$(BLUE)[INFO]$(NC) Checking the English catalogs use no retired domain word (baseline)..."
	docker compose exec frontend npm run check:vocabulary
	@echo "$(BLUE)[INFO]$(NC) Checking warehouse and purchase-order texts are sentence case (baseline)..."
	docker compose exec frontend npm run check:title-case
	@echo "$(BLUE)[INFO]$(NC) Checking route reachability (baseline)..."
	docker compose exec frontend npm run check:routes
	@echo "$(BLUE)[INFO]$(NC) Checking focus-mode reachability of core sections (baseline)..."
	docker compose exec frontend npm run check:focus-reachability
	@echo "$(BLUE)[INFO]$(NC) Checking dead code (knip, baseline)..."
	docker compose exec frontend npm run check:dead:baseline
	@echo "$(BLUE)[INFO]$(NC) Checking file reachability from production roots (baseline)..."
	docker compose exec frontend npm run check:reachable
	@echo "$(BLUE)[INFO]$(NC) Checking module boundaries (baseline)..."
	docker compose exec frontend npm run check:boundaries
	@echo "$(BLUE)[INFO]$(NC) Checking the anonymous tree stays out of the app bundle..."
	docker compose exec frontend npm run check:public-bundle
	@echo "$(BLUE)[INFO]$(NC) Checking every dialog has an accessible name and a way out..."
	docker compose exec frontend npm run check:dialogs
	@echo "$(BLUE)[INFO]$(NC) Checking every form control has an accessible name (baseline)..."
	docker compose exec frontend npm run check:field-names
	@echo "$(BLUE)[INFO]$(NC) Checking every location query states its scope (baseline)..."
	docker compose exec frontend npm run check:storage-scope
	@echo "$(BLUE)[INFO]$(NC) Checking every category query states its scope (baseline)..."
	docker compose exec frontend npm run check:category-scope
	@echo "$(BLUE)[INFO]$(NC) Checking no failed load reads as an empty answer (baseline)..."
	docker compose exec frontend npm run check:query-error-read
	@echo "$(BLUE)[INFO]$(NC) Checking every mutateAsync refusal reaches the reader (baseline)..."
	docker compose exec frontend npm run check:mutate-async
	@echo "$(BLUE)[INFO]$(NC) Checking no unit symbol reaches the screen unresolved (baseline)..."
	docker compose exec frontend npm run check:quantity-render
	@echo "$(BLUE)[INFO]$(NC) Checking the form's quantity bounds match the store's constants..."
	docker compose exec frontend npm run check:quantity-bounds
	@echo "$(BLUE)[INFO]$(NC) Checking the type scale and one job per weight..."
	docker compose exec frontend npm run check:type-scale
	@echo "$(BLUE)[INFO]$(NC) Checking every page empty state carries a description..."
	docker compose exec frontend npm run check:empty-state
	@echo "$(BLUE)[INFO]$(NC) Checking every colour class resolves in the theme..."
	docker compose exec frontend npm run check:theme-colors
	@echo "$(BLUE)[INFO]$(NC) Checking primaryTabs stay a fixed set, not a network collection..."
	docker compose exec frontend npm run check:primary-tabs
	@echo "$(BLUE)[INFO]$(NC) Checking E2E specs do not sleep more than they did (baseline)..."
	docker compose exec frontend npm run check:e2e-waits
	@echo "$(BLUE)[INFO]$(NC) Checking no count is pasted next to a translated noun..."
	docker compose exec frontend npm run check:plurals
	@echo "$(BLUE)[INFO]$(NC) Checking every API route has a caller or a recorded reason..."
	docker compose exec frontend npm run check:consumers
	@echo "$(BLUE)[INFO]$(NC) Checking every invalidated key belongs to a real query..."
	docker compose exec frontend npm run check:invalidation
	@echo "$(BLUE)[INFO]$(NC) Checking every onError handler reads the refusal it was handed..."
	docker compose exec frontend npm run check:onerror
	@echo "$(BLUE)[INFO]$(NC) Checking hand-written types that claim to mirror the wire..."
	docker compose exec frontend npm run check:mirrors
	@echo "$(BLUE)[INFO]$(NC) Checking no hand-written copy keeps a backend schema's name (baseline)..."
	docker compose exec frontend npm run check:api-types-mirror
	@echo "$(BLUE)[INFO]$(NC) Checking the backend's unit-label mirror against the screen..."
	docker compose exec frontend npm run check:units-labels
	@echo "$(BLUE)[INFO]$(NC) Checking every suppression has an owner and a live date..."
	docker compose exec frontend npm run check:suppressions
	@echo "$(BLUE)[INFO]$(NC) Checking no baselined function grew past its frozen complexity or length..."
	docker compose exec frontend npm run check:function-baseline
	@echo "$(BLUE)[INFO]$(NC) Checking no accessibility finding was added to a relaxed file (jsx-a11y baseline)..."
	docker compose exec frontend npm run check:a11y-baseline
	@echo "$(BLUE)[INFO]$(NC) Checking module settings snapshot..."
	docker compose exec frontend npm run check:modules
	@echo "$(BLUE)[INFO]$(NC) Checking every backend module reaches the store..."
	docker compose exec frontend npm run check:modules:catalog
	@echo "$(BLUE)[INFO]$(NC) Checking the frontend module contract and the guide's slot table..."
	@node frontend/scripts/check-module-contract.mjs
	@echo "$(BLUE)[INFO]$(NC) Checking hardcoded user-facing strings bypass i18n..."
	docker compose exec frontend npm run lint:i18n
	@echo "$(BLUE)[INFO]$(NC) Checking tests assert what the product renders, not raw keys..."
	docker compose exec frontend npm run lint:tests
	@echo "$(BLUE)[INFO]$(NC) Checking every category emoji has a self-hosted SVG and a manifest entry..."
	docker compose exec frontend npm run check:emoji
	@echo "$(BLUE)[INFO]$(NC) Checking UI conventions..."
	docker compose exec frontend npm run lint:ui
	@$(MAKE) --no-print-directory check-openapi-fresh
	@$(MAKE) --no-print-directory check-api-types
	@$(MAKE) --no-print-directory perf-phone

# ─── frontend/package.json targets NO make target calls ───────────────────
# Measured: 52 scripts, 31 called above/here, the rest are deliberate and
# each of these has a reason to stay out of the automated gates:
#   dev / preview                    — interactive sessions, not gates.
#   test / test:run                  — the Makefile drives vitest inside the
#                                      container directly, with `--coverage`;
#                                      these are the host-side conveniences.
#                                      The `test:coverage` script is that same
#                                      flag, and the thresholds in
#                                      frontend/vite.config.ts apply only under
#                                      it, so the container command carries it:
#                                      the suite used to run without it and
#                                      enforced nothing, which is how the
#                                      63/49/73/63 floor went missing locally.
#   format:check                     — the pre-commit hook checks formatting on commit;
#                                      this is the whole-tree re-check.
#   build                            — `vite build` alone; `build:check` (tsc, the
#                                      build and the bundle budget) is the one
#                                      wired in above.
#   check:dead                       — plain `knip`: it exits 0 on this tree and
#                                      prints only a configuration hint, so its
#                                      exit code says nothing about the
#                                      grandfathered findings; the verdict that
#                                      gates is `check:dead:baseline`, above.
#   sync:emoji                       — NETWORK writer (downloads SVGs); its
#                                      offline guard is check:emoji, above.
#   check:i18n:sync-backend /
#   check:modules:sync-backend /
#   check:modules:catalog:sync-backend /
#   check:i18n:plural-snapshot /
#   check:field-names:baseline /
#   check:storage-scope:baseline /
#   check:category-scope:baseline /
#   check:query-error-read:baseline /
#   check:mutate-async:baseline /
#   check:quantity-render:baseline   — WRITERS that regenerate golden files
#                                      after an intentional change; their
#                                      verdicts run inside the gates above.
#                                      The three baselines shrink as the
#                                      classes are retired — refresh them
#                                      when a gate reports fixed entries,
#                                      never to admit a new finding.
#   sync-audit-fields                — the same, one step further out: the
#                                      backend reads its own snapshot writers
#                                      and the artefact it prints is what
#                                      check:audit-fields reads back.
#   check:i18n:plural-report /
#   scan:ui                          — advisory reports, no verdict to gate
#                                      on (their findings are tracked as
#                                      follow-up work).

lint-architecture: ## Check architecture boundaries for backend modules
	@echo "$(BLUE)[INFO]$(NC) Checking architecture boundaries..."
	$(BACKEND_EXEC) uv run python manage.py arch lint --quiet

scan-dead: ## Full dead-code + duplication report (vulture, knip, i18n orphans, route + file + focus reachability, jscpd) — non-blocking
	@echo "$(BLUE)[INFO]$(NC) Scanning dead code (full reports, non-blocking)..."
	$(BACKEND_EXEC) uv run python scripts/check_vulture_baseline.py --full || true
	docker compose exec frontend node scripts/check-knip-baseline.mjs --full || true
	docker compose exec frontend node scripts/check-i18n-keys.mjs --unused || true
	docker compose exec frontend node scripts/check-route-reachability.mjs || true
	docker compose exec frontend node scripts/check-focus-reachability.mjs || true
	docker compose exec frontend node scripts/check-reachability.mjs || true
	@echo "$(BLUE)[INFO]$(NC) Measuring textual duplication (jscpd, informational)..."
	@$(MAKE) --no-print-directory scan-duplication
	@echo "$(GREEN)[DONE]$(NC) Dead-code scan finished — findings are informational. Fix them in the same PR that creates them."

scan-duplication: ## Textual duplication report (jscpd) — non-blocking, threshold 3% informational
	@echo "$(BLUE)[INFO]$(NC) jscpd over backend/app and frontend/src (tests and generated files excluded)..."
	@npx --yes jscpd@4 backend/app frontend/src --config .jscpd.json || true
	@echo "$(BLUE)[INFO]$(NC) Above 3% is worth a look; the audit that produced this target measured 1.86% backend / 0.50% frontend. Duplication is born in the seams between sibling features, so read the clusters, not only the number."

quality-index: ## Compute Quality Index (track weekly, target >90)
	@echo "$(BLUE)[INFO]$(NC) Computing Quality Index..."
	$(BACKEND_EXEC) uv run python scripts/quality_index.py

typecheck: ## Run mypy type checking on app/core + strict modules
	@echo "$(BLUE)[INFO]$(NC) Running mypy on app/core + strict modules..."
	$(BACKEND_EXEC) uv run mypy app/core app/cli \
		app/modules/api_keys app/modules/printing app/modules/example_widgets \
		app/modules/nutrition app/modules/vision app/modules/webhooks \
		app/modules/shopping_lists \
		app/modules/approvals app/modules/equipment \
		app/modules/recipes app/modules/warehouse \
		app/modules/purchase_orders app/modules/stock_takes app/modules/stats

##@ Modules

validate-module: ## Validate modules for community-safe constraints
	@echo "$(BLUE)[INFO]$(NC) Validating module manifests and import constraints..."
	$(BACKEND_EXEC) uv run python manage.py module validate

module-smoke: ## Run comprehensive smoke test on a single module (usage: make module-smoke name=my_module)
	@if [ -z "$(name)" ]; then \
		echo "$(RED)[ERROR]$(NC) Usage: make module-smoke name=my_module"; exit 1; \
	fi
	$(BACKEND_EXEC) uv run python manage.py module smoke $(name)

# One shell, `set -e`: a step that fails stops the recipe with its exit code
# instead of ending in SUCCESS. A half that already exists is skipped, so after
# a failure a second run picks up at the step that failed.
new-module: ## Create an in-tree module scaffold (backend + frontend) (usage: make new-module NAME=warranty_tracker)
	@set -e; \
	if [ -n "$(NAME)" ]; then \
		name="$(NAME)"; \
	else \
		read -p "Module name (lowercase, underscores only, e.g. warranty_tracker): " name; \
	fi; \
	if [ -z "$$name" ]; then \
		echo "$(RED)[ERROR]$(NC) No name given. Usage: make new-module NAME=warranty_tracker"; exit 1; \
	fi; \
	if ! echo "$$name" | grep -qE '^[a-z][a-z0-9_]+$$'; then \
		echo "$(RED)[ERROR]$(NC) Invalid name '$$name'. Use lowercase letters, digits and underscores only."; exit 1; \
	fi; \
	if [ -d "backend/app/modules/$$name" ]; then \
		echo "$(BLUE)[INFO]$(NC) Backend scaffold for '$$name' already exists — skipped."; \
	else \
		echo "$(BLUE)[INFO]$(NC) Creating backend scaffold for '$$name'..."; \
		$(BACKEND_EXEC) uv run python manage.py module create "$$name"; \
	fi; \
	if [ -d "frontend/src/modules/$$name" ]; then \
		echo "$(BLUE)[INFO]$(NC) Frontend scaffold for '$$name' already exists — skipped."; \
	else \
		echo "$(BLUE)[INFO]$(NC) Creating frontend scaffold for '$$name'..."; \
		docker compose exec frontend node scripts/generate_module.js "$$name"; \
	fi; \
	echo "$(BLUE)[INFO]$(NC) Recording '$$name' in the module catalog snapshot..."; \
	node frontend/scripts/check-module-catalog.mjs --sync-backend; \
	echo "$(BLUE)[INFO]$(NC) Recording its permission labels in the backend key snapshot..."; \
	node frontend/scripts/check-i18n-keys.mjs --sync-backend; \
	$(MAKE) --no-print-directory generate-openapi generate-api-types; \
	echo "$(GREEN)[SUCCESS]$(NC) Module '$$name' created. See MODULE_QUICKSTART.md for next steps."

new-community-module: ## Create a standalone community module package (for distribution) (usage: make new-community-module NAME=warranty_tracker)
	@if [ -n "$(NAME)" ]; then \
		name="$(NAME)"; \
	else \
		read -p "Module name (lowercase, underscores only, e.g. warranty_tracker): " name; \
	fi; \
	if [ -z "$$name" ]; then \
		echo "$(RED)[ERROR]$(NC) No name given. Usage: make new-community-module NAME=warranty_tracker"; exit 1; \
	fi; \
	if ! echo "$$name" | grep -qE '^[a-z][a-z0-9_]+$$'; then \
		echo "$(RED)[ERROR]$(NC) Invalid name '$$name'. Use lowercase letters, digits and underscores only."; exit 1; \
	fi; \
	OUTDIR="./modules-workspace/$$name"; \
	if [ -e "$$OUTDIR" ]; then \
		echo "$(RED)[ERROR]$(NC) '$$OUTDIR' already exists."; exit 1; \
	fi; \
	echo "$(BLUE)[INFO]$(NC) Generating community module package '$$name' in $$OUTDIR/..."; \
	$(BACKEND_EXEC) uv run python manage.py module new-community "$$name" --output /modules-workspace; \
	echo "$(GREEN)[SUCCESS]$(NC) Package ready in $$OUTDIR/. See MODULES_GUIDE.md for the publishing guide."

##@ Formatting and hooks

format: ## Format code
	@echo "$(BLUE)[INFO]$(NC) Formatting backend code with ruff..."
	$(BACKEND_EXEC) uv run ruff format .
	$(BACKEND_EXEC) uv run ruff check . --fix
	@echo "$(BLUE)[INFO]$(NC) Formatting frontend code with prettier..."
	docker compose exec frontend npm run format

frontend-format: ## Format frontend code only
	docker compose exec frontend npm run format

setup-hooks: ## Install pre-commit hooks (run once after clone)
	@echo "$(BLUE)[INFO]$(NC) Installing pre-commit..."
	@command -v pre-commit >/dev/null 2>&1 || { \
		command -v uv >/dev/null 2>&1 && uv tool install pre-commit; \
	} || { \
		command -v pipx >/dev/null 2>&1 && pipx install pre-commit; \
	} || python3 -m pip install --user pre-commit
	@command -v pre-commit >/dev/null 2>&1 || { \
		echo "$(RED)[ERROR]$(NC) pre-commit is installed but not on PATH — add $$HOME/.local/bin (where uv tool and pip --user put it) to PATH and rerun."; \
		exit 1; \
	}
	@pre-commit install
	@echo "$(GREEN)[OK]$(NC) Pre-commit hooks installed: the file checks and the commit-message check run on every git commit."

# Backward-compatible alias
setup: setup-hooks

##@ Tests

# The backend selection lives in backend/pytest.ini (testpaths) — the recipes
# below run pytest without paths of their own, so no tests directory can sit
# outside the gate. backend/tests/unit/test_every_test_file_is_collected_by_a_gate.py
# guards that; listing paths here as well is how app/core/tests and
# app/services/items/tests came to be collected by no gate at all.

test: test-backend test-frontend lint-architecture ## Run all tests (backend, frontend) + architecture lint

test-backend: ## Run only backend tests
	@echo "$(BLUE)[INFO]$(NC) Running backend tests..."
	@$(call GATED_PYTEST,-n $(PYTEST_WORKERS) -v,tail -20)

test-frontend: ## Run only frontend tests
	@echo "$(BLUE)[INFO]$(NC) Running frontend tests..."
	@# `--coverage` is not decoration: the thresholds in frontend/vite.config.ts
	@# apply only when it is on, so a suite run without it reported green while
	@# the 63/49/73/63 floor was never consulted. CI ran `npm run test:coverage`;
	@# this is that command, run where the Makefile drives vitest.
	docker compose exec -T frontend npx vitest run --coverage

test-e2e: ## Run Playwright E2E tests (restarts backend with TESTING=true)
	@echo "$(BLUE)[INFO]$(NC) Running E2E tests..."
	@# A @playwright/test bump leaves ~/.cache/ms-playwright holding the old
	@# browser revisions, and the whole suite then "fails" in ~1ms per test with
	@# `Executable doesn't exist`. That reads as hundreds of regressions and
	@# costs a long time to diagnose, so check it up front. Both browsers:
	@# the `mobile` project uses devices['iPhone 14'], which launches WebKit.
	@cd frontend && npx playwright install chromium webkit >/dev/null 2>&1 || { \
		echo "$(YELLOW)[WARN]$(NC) Could not verify Playwright browsers — continuing"; \
	}
	@# The password-reset spec needs the TESTING-only _dev_token route, which
	@# is only registered when settings.TESTING=true. Run the whole block in
	@# one shell so the EXIT trap restores the original mode after tests.
	@set -e; \
	prev_testing=$$($(DOCKER_COMPOSE) exec -T backend printenv TESTING 2>/dev/null | tr -d '\r' || echo false); \
	prev_testing=$${prev_testing:-false}; \
	if [ "$$prev_testing" != "true" ]; then \
		echo "$(YELLOW)[INFO]$(NC) Restarting backend with TESTING=true..."; \
		TESTING=true TESTING_ACK_UNSAFE=true $(DOCKER_COMPOSE) up -d backend >/dev/null; \
		bcid=$$($(DOCKER_COMPOSE) ps -q backend); \
		n=0; until [ "$$(docker inspect -f '{{.State.Health.Status}}' $$bcid 2>/dev/null)" = "healthy" ] || [ $$n -ge 60 ]; do n=$$((n+1)); sleep 1; done; \
		trap 'echo "$(YELLOW)[INFO]$(NC) Restoring backend to TESTING='"$$prev_testing"'..."; TESTING='"$$prev_testing"' $(DOCKER_COMPOSE) up -d backend >/dev/null' EXIT; \
	fi; \
	cd frontend && npx playwright test --reporter=list

e2e-example-module: ## Install the guide's example module, walk it in the browser, uninstall it (on the stack the wrapper names; VITE_API_URL as for test-e2e)
	@echo "$(BLUE)[INFO]$(NC) Installing examples/lot_certificates the community way..."
	@# The module is not part of the platform, so no other spec expects it and
	@# the default run leaves its spec out. This target puts it in the stack's
	@# module trees (both halves), restarts the backend so startup scans,
	@# migrates and mounts it, runs the one spec, and takes it out again
	@# whatever the spec answered — its data stays, as an uninstall's does.
	@set -e; \
	$(DOCKER_COMPOSE) exec -T backend uv run python manage.py module install /repo/examples/lot_certificates --allow-unsigned >/dev/null; \
	trap 'echo "$(YELLOW)[INFO]$(NC) Uninstalling the example module..."; $(DOCKER_COMPOSE) exec -T backend uv run python manage.py module uninstall lot_certificates --force >/dev/null; $(DOCKER_COMPOSE) restart backend >/dev/null' EXIT; \
	$(DOCKER_COMPOSE) restart backend >/dev/null; \
	bcid=$$($(DOCKER_COMPOSE) ps -q backend); \
	n=0; until [ "$$(docker inspect -f '{{.State.Health.Status}}' $$bcid 2>/dev/null)" = "healthy" ] || [ $$n -ge 90 ]; do n=$$((n+1)); sleep 1; done; \
	cd frontend && E2E_EXAMPLE_MODULE=1 npx playwright test --project=example-module --retries=0 --reporter=list

test-e2e-ui: ## Run Playwright E2E tests with UI
	cd frontend && npx playwright test --ui

perf-phone: ## Measure the core screens on a mid Android over slow 4G and fail past the load-time budget (needs a built dist/ and a running stack; posts the onboarding setup to it)
	@echo "$(BLUE)[INFO]$(NC) Measuring the core screens on the phone profile (CPU 4x, slow 4G)..."
	@api="$${PHONE_BUDGET_API:-http://$$($(DOCKER_COMPOSE) port backend 8000)}"; \
		cd frontend && PHONE_BUDGET_API="$$api" node scripts/measure-phone-budget.mjs

test-e2e-isolated: ## Run Playwright E2E on the secondary dev2 stack (dev DB stays clean)
	@echo "$(BLUE)[INFO]$(NC) Running E2E on the isolated dev2 stack (ports +100)..."
	@# --wait: the backend migrates before it answers its healthcheck, and on
	@# a fresh database the seed below otherwise meets no tables at all.
	@scripts/dev2 docker compose up -d --build --wait --wait-timeout 300 >/dev/null
	@scripts/dev2 make db-seed >/dev/null
	@# dev2 is a throwaway stack, so the known-weak seed password is allowed
	@# even when the environment is production-shaped (.env DEBUG=false) and
	@# the CLI would otherwise refuse it and abort the run.
	@scripts/dev2 make create-admin email="$(DEV_ADMIN_EMAIL)" password="$(DEV_ADMIN_PASSWORD)" name="Administrator" ALLOW_WEAK_PASSWORD=--allow-weak-password >/dev/null
	@VITE_API_URL=http://127.0.0.1:5273 scripts/dev2 make test-e2e

test-unit: ## Run only unit tests
	@echo "$(BLUE)[INFO]$(NC) Running unit tests..."
	@$(call GATED_PYTEST,-n $(PYTEST_WORKERS) tests/unit -v,cat)

test-integration: ## Run only integration tests
	@echo "$(BLUE)[INFO]$(NC) Running integration tests..."
	@$(call GATED_PYTEST,-n $(PYTEST_WORKERS) tests/integration -v,cat)

test-coverage: ## Run tests with coverage, then gate the changed lines (>= 80%) — CI's two backend test steps
	@echo "$(BLUE)[INFO]$(NC) Running tests with code coverage..."
	@$(call GATED_PYTEST,-n $(PYTEST_WORKERS) --cov=app --cov-report=term-missing:skip-covered --cov-report=json --cov-fail-under=70,cat)
	@$(MAKE) --no-print-directory check-diff-coverage

# Mutation testing is not a gate: a full run over the stock posting functions
# is about three hours on one worker, which is why it is on demand. Its test
# selection and scope live in `[tool.mutmut]` of backend/pyproject.toml; the
# committed report (docs/STOCK_MUTATION_REPORT.md) records what this last
# found. `mutmut` keeps its work in backend/mutants/: `mutmut results` lists
# what the last run left, and `mutmut run <name>` re-tests one mutant by name
# while the rest of the campaign stays as it was.
#
# The functions named below are where a generated stock write passes: the draw
# plan, the draw itself, the movement pass, the reservation and a record's own
# posting (its ceiling, its lock, its ledger line and its cost layer). The
# helpers and read paths in the same files are left out; the existing suite
# covers them, but a mutant there says nothing about whether a write is safe.
MUTATE_STOCK_MUTANTS := \
	"app.services._stock_draw.x_plan_draw_async*" \
	"app.services._stock_quant_ops.x_take_from_the_records_async*" \
	"app.services._stock_quant_ops.x_post_movement_async*" \
	"app.services._stock_quant_ops.x__plan_under_the_anchors_async*" \
	"app.services._stock_reservation.x_reserve_for_document_async*" \
	"app.services.items._stock_quant.x_apply_quantity_change_async*" \
	"app.services.items._stock_quant.x__post_the_change_async*"

mutate-stock: ## Mutation-test the stock posting functions (on demand, not in the pre-push gate)
	@echo "$(BLUE)[INFO]$(NC) Running mutmut over the stock posting functions (resumable; see backend/mutants/)..."
	@# One mutant at a time: every worker provisions the same run-scoped test
	@# database (the fork server mints the run id once), and two workers would
	@# drop and rebuild each other's schema mid-test.
	@# Three property examples: a mutant is killed by the first test that
	@# notices it, and the full twenty are the gate's, not this run's.
	$(BACKEND_EXEC) env STOCK_PROPERTY_EXAMPLES=3 \
		uv run --group mutation mutmut run --max-children 1 $(MUTATE_STOCK_MUTANTS)
	@# `mutmut results` lists the whole mutated files, including the functions
	@# this run does not select (they stay "not checked"); the report's scope
	@# table is the full record, and these two are what an executor acts on.
	@echo "$(BLUE)[INFO]$(NC) Survived or timed out (each needs a killing test or a recorded equivalent reason):"
	@$(BACKEND_EXEC) uv run --group mutation mutmut results | grep -E ':( survived| timeout)' || echo "    none"

# The report `check-diff-coverage` reads is written by any run with
# `--cov-report=json`; `test-coverage` above is one, and CI's "Tests
# (coverage)" step was the other.
check-diff-coverage: ## Gate the lines changed vs origin/dev (>= 80% covered); needs backend/coverage.json
	@echo "$(BLUE)[INFO]$(NC) Checking coverage of changed lines..."
	@python3 backend/scripts/check_diff_coverage.py

test-fast: ## Run tests excluding slow-marked tests
	@echo "$(BLUE)[INFO]$(NC) Running fast tests (excluding slow)..."
	@$(call GATED_PYTEST,-n $(PYTEST_WORKERS) -m "not slow" -q,cat)

test-profile: ## Profile the suite: per-phase time, costliest files, and the load it ran under
	@echo "$(BLUE)[INFO]$(NC) Profiling the backend suite (runs the whole suite once)..."
	@# The report carries the host's load and stack count because a number
	@# measured beside sixteen other docker stacks is not the same number.
	@# Two published claims about this suite were off by 4x and 2.2x for
	@# exactly that reason, and neither said what the host was doing.
	@# Narrow it with ARGS, e.g. `make test-profile ARGS="tests/integration"`.
	$(BACKEND_EXEC) uv run python scripts/profile_suite.py \
		--note "stacks=$$($(DOCKER_COMPOSE) ls -q 2>/dev/null | wc -l)" $(ARGS)

##@ Cleanup and database

clean: ## Remove test artifacts
	@echo "$(BLUE)[INFO]$(NC) Removing test artifacts..."
	$(BACKEND_EXEC) find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	$(BACKEND_EXEC) find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	$(BACKEND_EXEC) find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	$(BACKEND_EXEC) find . -type d -name ".tox" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)[SUCCESS]$(NC) Test artifacts removed"

clean-test: clean ## Remove test and coverage artifacts
	@echo "$(BLUE)[INFO]$(NC) Removing test and coverage artifacts..."
	$(BACKEND_EXEC) find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	$(BACKEND_EXEC) find . -type f -name ".coverage" -exec rm -f {} + 2>/dev/null || true
	@echo "$(GREEN)[SUCCESS]$(NC) Test and coverage artifacts removed"

# Database commands
db-migrate: ## Generate new migration (usage: make db-migrate m="migration_name")
	@echo "$(BLUE)[INFO]$(NC) Generating new migration..."
	$(BACKEND_EXEC) uv run python manage.py db migrate "$(m)"

db-upgrade: ## Apply migrations to database
	@echo "$(BLUE)[INFO]$(NC) Applying migrations (core + modules)..."
	$(BACKEND_EXEC) uv run python manage.py db upgrade

db-seed: ## Initialize system data (storage types, categories)
	@echo "$(BLUE)[INFO]$(NC) Seeding database..."
	$(BACKEND_EXEC) uv run python manage.py db seed

loadtest-seed: ## Create k6 users + load_tests/users.csv and seed items (needs K6_PASSWORD; see load_tests/README.md)
	./load_tests/prepare.sh

seed-scale: ## Seed the admin's empty organization at warehouse scale (usage: make seed-scale PRODUCTS=100000 [SHELVES=2000]; see load_tests/README.md)
	$(BACKEND_EXEC) uv run python seed_scale_data.py --products $(PRODUCTS) $(if $(SHELVES),--shelves $(SHELVES))

measure-scale: ## Time every daily screen and report on a scale-seeded stack (usage: make measure-scale TIER=100k; needs a built frontend/dist)
	@api="$${SCALE_API:-http://$$($(DOCKER_COMPOSE) port backend 8000)}"; \
		python3 load_tests/scale/measure.py --api "$$api" --tier "$(TIER)" --out "load_tests/scale/results/$(TIER).json"

db-seed-demo: ## Seed demo data (500 items by default, suppliers, warehouse hierarchy)
	@echo "$(BLUE)[INFO]$(NC) Seeding demo data..."
	$(BACKEND_EXEC) uv run python seed_demo_data.py
	@echo "$(GREEN)[OK]$(NC) Demo data seeded. Login: admin@example.com"

demo-reset: ## Wipe this database and rebuild it as the public demo (destructive; dev or demo installs, production refuses)
	@echo "$(RED)[WARNING]$(NC) Wiping this database and rebuilding it as the demo..."
	$(BACKEND_EXEC) env INVENTARI_DEMO=true uv run python manage.py demo reset

release-db-snapshot: ## Freeze the database this release leaves on disk as the upgrade-test fixture (run on the release commit, before the tag; VERSION= overrides pyproject)
	@bash scripts/release-db-snapshot.sh

db-seed-clean: ## Reset and seed clean (system data only, no items)
	@echo "$(RED)[WARNING]$(NC) Resetting database..."
	$(BACKEND_EXEC) uv run python manage.py db reset --yes-i-am-sure
	$(BACKEND_EXEC) uv run python manage.py db upgrade
	$(BACKEND_EXEC) uv run python manage.py db seed
	@echo "$(GREEN)[OK]$(NC) Clean database ready. It has no account: make dev-up creates the development admin again."

db-reset: ## Reset database (warning: removes all data!)
	@echo "$(RED)[WARNING]$(NC) Resetting database..."
	$(BACKEND_EXEC) uv run python manage.py db reset --yes-i-am-sure
	$(BACKEND_EXEC) uv run python manage.py db upgrade
	@echo "$(GREEN)[OK]$(NC) Empty database at the latest schema. It has no account: make dev-up creates the development admin again."

shell: ## Run interactive python shell with database session
	@echo "$(BLUE)[INFO]$(NC) Starting interactive shell..."
	$(BACKEND_EXEC) uv run python manage.py shell

db-shell: ## Run interactive PostgreSQL shell
	@echo "$(BLUE)[INFO]$(NC) Connecting to database..."
	$(DOCKER_COMPOSE) exec db psql -U inventari_user -d inventari_db




##@ Tools

print-dev-admin: ## Print the development admin credentials (email then password)
	@echo "$(DEV_ADMIN_EMAIL) $(DEV_ADMIN_PASSWORD)"

create-admin: ## Create admin user (usage: make create-admin email="admin@example.com" password="securepassword" [ALLOW_WEAK_PASSWORD=--allow-weak-password])
	@echo "$(BLUE)[INFO]$(NC) Creating admin user..."
	$(BACKEND_EXEC) uv run python manage.py user create-admin --email "$(email)" --password "$(password)" --name "$(name)" $(ALLOW_WEAK_PASSWORD)

# A one-off container of its own, not `exec` into the running backend: the
# import holds about 1 GB for the whole run, and in the backend's container an
# out-of-memory kill would take an application worker with it. The file is
# mounted read-only rather than copied in, so it takes its disk once.
off-import: ## Import OFF Parquet into products_db (usage: make off-import FILE=/path/to/food.parquet)
	@if [ -z "$(FILE)" ]; then echo "$(RED)[ERROR]$(NC) Usage: make off-import FILE=/path/to/food.parquet"; exit 1; fi
	@echo "$(BLUE)[INFO]$(NC) Starting OFF import in a one-off container (4.8 million rows, about 10 minutes)..."
	$(DOCKER_COMPOSE) run --rm --no-deps -v "$(abspath $(FILE)):/data/food.parquet:ro" backend uv run python -m app.modules.nutrition.import_parquet /data/food.parquet $(BATCH)
	@echo "$(GREEN)[SUCCESS]$(NC) OFF import complete. Verify with: make off-count"

off-count: ## Show number of products imported into products_db
	@if ! $(DOCKER_COMPOSE) ps --status running --services 2>/dev/null | grep -qx products-db; then \
		echo "$(RED)[ERROR]$(NC) The products database is not running - start it with make dev-up-full."; \
		exit 1; \
	fi
	@psql="$(DOCKER_COMPOSE) exec -T products-db psql -U $${PRODUCTS_DB_USER:-products_user} -d $${PRODUCTS_DB_NAME:-products_db} -tA"; \
	count=0; \
	if [ "$$($$psql -c "SELECT to_regclass('off_products_local') IS NOT NULL")" = "t" ]; then \
		count=$$($$psql -c "SELECT COUNT(*) FROM off_products_local"); \
	fi; \
	if [ "$$count" = "0" ]; then \
		echo "0 products: nothing has been imported yet. Download the Open Food Facts file (docs/OFF_DATABASE_SETUP.md), then make off-import FILE=/path/to/food.parquet"; \
	else \
		echo "$$count products imported"; \
	fi

generate-api-docs: ## Regenerate docs/subsystems/CORE_API.md from source
	@echo "$(BLUE)[INFO]$(NC) Regenerating CoreAPI reference docs..."
	@docker compose exec -T backend python scripts/generate_core_api_reference.py \
		> $(CORE_API_DOC_TMP) \
		|| (rm -f $(CORE_API_DOC_TMP); echo "$(RED)[ERROR]$(NC) the backend did not answer — is the stack up? (make status; make up). docs/subsystems/CORE_API.md is unchanged." >&2; exit 1)
	@mv $(CORE_API_DOC_TMP) docs/subsystems/CORE_API.md
	@echo "$(GREEN)[SUCCESS]$(NC) docs/subsystems/CORE_API.md updated"

# The dev and production apps serve no /openapi.json (main.py gates it on
# DEBUG), so the generator cannot fetch the schema over HTTP where it is most
# needed. Route registration happens at import time, so a plain import inside
# the container produces the same schema a served one would — no server, no
# lifespan, no database.
# Importing the app logs ~60 startup lines to stderr. They are worth seeing
# when the dump fails and pure noise when it works, so they are held back and
# replayed only on failure.
# Per-invocation path: the stack's name (two trees on two stacks must not
# share it) plus the PID of the subshell `$(shell)` forks (two invocations
# in the same tree must not either — not make's own PID, but fresh per make
# run, which is what the uniqueness needs). A fixed name made two concurrent
# check-frontend runs steal the file from each other, and the loser reported
# a JSON syntax error that looked exactly like contract drift.
OPENAPI_JSON := /tmp/inventari-openapi.$(if $(COMPOSE_PROJECT_NAME),$(COMPOSE_PROJECT_NAME),core).$(shell echo $$$$).json
# Same reasoning as OPENAPI_JSON: two check-frontend runs must not hand each
# other the file, or the loser reports a difference that is not there.
AUDIT_KEYS_JSON := /tmp/inventari-audit-keys.$(if $(COMPOSE_PROJECT_NAME),$(COMPOSE_PROJECT_NAME),core).$(shell echo $$$$).json
# The backend suite's log lands here so the recipe can read the exit code and
# the summary line after the fact — a pipe hands the caller tee's exit code,
# which is how a run carrying errors was ever pushed as green.
PYTEST_LOG := /tmp/inventari-pytest.$(if $(COMPOSE_PROJECT_NAME),$(COMPOSE_PROJECT_NAME),core).$(shell echo $$$$).log

# One backend pytest run, gated: $(1) are pytest's arguments, $(2) shows the
# log. The run goes to a file so the recipe can read the exit code and the
# summary line after the fact — a pipe hands the caller tee's exit code, which
# is how a run carrying errors was ever pushed as green. The log is removed
# whatever the verdict; the checker is addressed from $(CURDIR) so the recipe
# survives `make -C`.
define GATED_PYTEST
$(BACKEND_EXEC) uv run pytest $(1) > $(PYTEST_LOG) 2>&1; \
rc=$$?; \
$(2) $(PYTEST_LOG); \
python3 $(CURDIR)/backend/scripts/check_pytest_summary_errors.py $(PYTEST_LOG); \
summary=$$?; \
rm -f $(PYTEST_LOG); \
if [ $$summary -ne 0 ]; then exit 1; fi; \
exit $$rc
endef
# The three targets below write a TRACKED artefact, and that is the shape they
# all follow: the command writes a scratch file and the tree is touched only
# by a move that happens after it succeeded. A plain redirection truncates its
# target before the command runs — so `make sync-audit-fields` against a stack
# that is not up left frontend/scripts/audit-snapshot-keys.json at zero bytes,
# and the gate reading it reported a JSON syntax error instead of the backend
# nobody had started. The scratch file is per stack and per invocation for the
# same reason OPENAPI_JSON is.
#
# Enumerated, and this is the whole list (measured by grepping the recipes for
# a redirection into the tree):
#   sync-audit-fields   -> frontend/scripts/audit-snapshot-keys.json
#   generate-openapi    -> docs/api/openapi.json
#   generate-api-docs   -> docs/subsystems/CORE_API.md
# `generate-api-types` writes its artefact (frontend/src/types/api-generated.ts)
# from npm, inside the frontend container, through the same scratch file.
CORE_API_DOC_TMP := /tmp/inventari-core-api.$(if $(COMPOSE_PROJECT_NAME),$(COMPOSE_PROJECT_NAME),core).$(shell echo $$$$).md
define dump_openapi
	@docker compose exec -T backend python -c \
		"import json; from app.main import app; print(json.dumps(app.openapi()))" \
		> $(OPENAPI_JSON) 2>$(OPENAPI_JSON).err \
		|| (cat $(OPENAPI_JSON).err >&2; rm -f $(OPENAPI_JSON) $(OPENAPI_JSON).err; exit 1)
	@rm -f $(OPENAPI_JSON).err
endef

generate-api-types: ## Generate TypeScript types from backend OpenAPI schema (requires running backend)
	@echo "$(BLUE)[INFO]$(NC) Generating TypeScript types from OpenAPI schema..."
	$(dump_openapi)
	cd frontend && OPENAPI_FILE=$(OPENAPI_JSON) npm run generate:api-types
	@rm -f $(OPENAPI_JSON)
	@echo "$(GREEN)[SUCCESS]$(NC) frontend/src/types/api-generated.ts updated"

check-api-types: ## Check that generated TypeScript types match the backend schema
	@echo "$(BLUE)[INFO]$(NC) Checking API type freshness (contract drift)..."
	$(dump_openapi)
	@cd frontend && OPENAPI_FILE=$(OPENAPI_JSON) npm run generate:api-types:check \
		|| (rm -f $(OPENAPI_JSON); exit 1)
	@rm -f $(OPENAPI_JSON)
	@echo "$(GREEN)[SUCCESS]$(NC) API types are up-to-date"

# What docs/api/openapi.json IS (the decision this target and the check below
# record): a maintained artifact — the canonical REST-schema export for readers
# who explore the API without running the backend (Postman/Insomnia/Bruno;
# production serves no /openapi.json, so the committed file is the only
# export there is). check-openapi-fresh is its freshness gate, wired into
# check-frontend next to check-api-types: after changing endpoints or response
# models, `make generate-openapi` is not a courtesy but what the gate expects.
# The dump is canonicalised (paths and components.schemas sorted) so the
# artifact is a function of the API alone — see scripts/dump_openapi.py.
generate-openapi: ## Export OpenAPI schema to docs/api/openapi.json (works without DEBUG)
	@echo "$(BLUE)[INFO]$(NC) Exporting OpenAPI schema..."
	@mkdir -p docs/api
	@docker compose exec -T backend python -m scripts.dump_openapi \
		> $(OPENAPI_JSON) 2>$(OPENAPI_JSON).err \
		|| (cat $(OPENAPI_JSON).err >&2; rm -f $(OPENAPI_JSON) $(OPENAPI_JSON).err; echo "$(RED)[ERROR]$(NC) the backend did not answer — is the stack up? (make status; make up). docs/api/openapi.json is unchanged." >&2; exit 1)
	@rm -f $(OPENAPI_JSON).err
	@mv $(OPENAPI_JSON) docs/api/openapi.json
	@echo "$(GREEN)[SUCCESS]$(NC) docs/api/openapi.json updated"

check-openapi-fresh: ## Fail when docs/api/openapi.json drifted from the live schema
	@echo "$(BLUE)[INFO]$(NC) Checking docs/api/openapi.json freshness..."
	@docker compose exec -T backend python -m scripts.dump_openapi \
		> $(OPENAPI_JSON) 2>$(OPENAPI_JSON).err \
		|| (cat $(OPENAPI_JSON).err >&2; rm -f $(OPENAPI_JSON) $(OPENAPI_JSON).err; echo "$(RED)[ERROR]$(NC) the backend did not answer — is the stack up? (make status; make up)." >&2; exit 1)
	@rm -f $(OPENAPI_JSON).err
	@if diff -q $(OPENAPI_JSON) docs/api/openapi.json > /dev/null 2>&1; then \
		rm -f $(OPENAPI_JSON); \
		echo "$(GREEN)[SUCCESS]$(NC) docs/api/openapi.json is up-to-date"; \
	else \
		rm -f $(OPENAPI_JSON); \
		echo "$(RED)[ERROR]$(NC) docs/api/openapi.json is stale — regenerate with: make generate-openapi, then review git diff docs/api/openapi.json" >&2; \
		exit 1; \
	fi

sync-audit-fields: ## Refresh the audit snapshot field list from the backend writers
	@echo "$(BLUE)[INFO]$(NC) Reading the backend's audit snapshot writers..."
	@docker compose exec -T backend python scripts/export_audit_snapshot_keys.py \
		> $(AUDIT_KEYS_JSON) \
		|| (rm -f $(AUDIT_KEYS_JSON); echo "$(RED)[ERROR]$(NC) the backend did not answer — is the stack up? (make status; make up). frontend/scripts/audit-snapshot-keys.json is unchanged." >&2; exit 1)
	@mv $(AUDIT_KEYS_JSON) frontend/scripts/audit-snapshot-keys.json
	@echo "$(GREEN)[SUCCESS]$(NC) frontend/scripts/audit-snapshot-keys.json updated — run make check-frontend"

check-audit-fields-fresh: ## Check the saved audit snapshot keys against what the backend declares now
	@echo "$(BLUE)[INFO]$(NC) Checking the audit snapshot key artefact is fresh..."
	@docker compose exec -T backend python scripts/export_audit_snapshot_keys.py \
		> $(AUDIT_KEYS_JSON) \
		|| (rm -f $(AUDIT_KEYS_JSON); exit 1)
	@cd frontend && AUDIT_KEYS_FRESH=$(AUDIT_KEYS_JSON) npm run check:audit-fields:fresh \
		|| (rm -f $(AUDIT_KEYS_JSON); exit 1)
	@rm -f $(AUDIT_KEYS_JSON)
	@echo "$(GREEN)[SUCCESS]$(NC) Audit snapshot keys are up-to-date"
