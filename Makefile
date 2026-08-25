# Local mirror of .github/workflows/ci.yml.
#
# The point of this file is that `make check` fails for exactly the reasons CI
# fails. Keep the recipes below identical to the workflow's `run:` lines — if you
# change one, change the other.
#
# Use the pinned tools from the dev extra, not whatever is on PATH: a newer ruff
# reports rules this codebase was never checked against, which reads as 48 errors
# that CI does not see.

PYTHON ?= python3
# Keep in step with the --cov-fail-under in .github/workflows/ci.yml.
COVERAGE_FLOOR ?= 70
VENV   := backend/.venv
BIN    := $(VENV)/bin

.DEFAULT_GOAL := help
.PHONY: help setup check lint types test docs frontend repo integration integration-full coverage clean

help: ## Show the available targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Create the virtualenv and install backend + frontend dependencies
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	@# `renderer` matters even without a browser: mypy follows the playwright imports.
	$(BIN)/pip install --quiet --disable-pip-version-check -e './backend[dev,renderer]'
	cd frontend && npm ci

check: lint types test docs frontend repo ## Everything CI runs, except the Showdown integration jobs
	@echo "\nAll CI checks passed."

lint: ## ruff check backend scripts
	$(BIN)/ruff check backend scripts

types: ## mypy --strict over the backend package
	$(BIN)/mypy backend/koalabattle

test: ## Backend unit tests
	$(BIN)/pytest -q backend/tests/unit

coverage: ## Backend unit tests with the coverage gate CI enforces
	$(BIN)/pytest -q backend/tests/unit --cov=koalabattle --cov-fail-under=$(COVERAGE_FLOOR)

docs: ## Documentation consistency check
	$(PYTHON) scripts/check_docs.py

frontend: ## Frontend tests, svelte-check and production build
	cd frontend && npm test && npm run check && npm run build

repo: ## Compose file and third-party asset tooling
	docker compose config --quiet
	$(PYTHON) scripts/setup_assets.py status
	$(PYTHON) scripts/setup_sfx.py status
	$(PYTHON) scripts/setup_move_effects.py status

# These bring the pinned engine up and deliberately leave it running. `docker
# compose down` would also stop a backend and frontend you had open — CI tears its
# own runner down, a laptop should not lose its running app to a test command.
integration: ## Campaign team validation against the pinned team validator
	docker compose up -d --build --wait team-validator
	KOALABATTLE_RUN_SHOWDOWN_TEST=1 \
		$(BIN)/pytest -q backend/tests/integration/test_challenge_content.py

integration-full: ## Every Showdown integration test, including real battles (slow)
	docker compose up -d --build --wait showdown team-validator
	@# Edge speech stays out: it calls an unofficial online service with no
	@# availability guarantee, behind its own KOALABATTLE_RUN_EDGE_TTS_TEST flag.
	KOALABATTLE_RUN_SHOWDOWN_TEST=1 \
		$(BIN)/pytest -q backend/tests/integration \
			--ignore=backend/tests/integration/test_edge_speech.py

clean: ## Remove caches and build output
	rm -rf $(VENV) frontend/node_modules frontend/.svelte-kit frontend/build
	find . -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
