PG_DSN ?= postgresql://recall:recall_dev_only@localhost:5433/recall
export PG_DSN

# The tests read PG_DSN directly, but recall.config uses env_prefix="RECALL_" and so
# reads RECALL_PG_DSN. Without this line `make migrate` ignored PG_DSN entirely and
# always targeted the default database - so it could not be pointed at the podman-hosted
# instance on the HPC box (an M0 acceptance criterion), and anyone overriding PG_DSN to
# target another instance would have silently migrated the wrong one. One variable now
# drives both; RECALL_PG_DSN still wins if set explicitly.
RECALL_PG_DSN ?= $(PG_DSN)
export RECALL_PG_DSN

.PHONY: db-up db-down db-reset migrate test lint local-dirs check-clean window-a-rehearsal window-b-rehearsal window-d-rehearsal guard-install guard-test

local-dirs:
	mkdir -p local/artifacts local/fixtures local/quarantine
	chmod 700 local/quarantine

db-up:
	docker compose -f infra/postgres/compose.yml up -d --build --wait

db-down:
	docker compose -f infra/postgres/compose.yml down

db-reset:
	docker compose -f infra/postgres/compose.yml down -v
	$(MAKE) db-up migrate

migrate:
	uv run python -m recall.db.migrate

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

check-clean:
	@if [ -n "$$(find local/quarantine -mindepth 1 -print -quit 2>/dev/null)" ]; then \
	  echo "FAIL: local/quarantine is not empty. The workstation must never hold"; \
	  echo "      real or derived corpus data. Inspect it yourself, shred it, and"; \
	  echo "      do not read it with an AI tool."; \
	  find local/quarantine -mindepth 1 -type f -printf '  %p (%s bytes)\n'; \
	  exit 1; \
	fi
	@echo "local/quarantine is empty - workstation clean"

window-a-rehearsal:
	./infra/profiler/rehearse-window-a.sh

window-b-rehearsal:
	./infra/profiler/rehearse-window-b.sh

window-d-rehearsal:
	./infra/profiler/rehearse-window-d.sh

guard-install:
	git config core.hooksPath .githooks

# Needs the project venv (uv run): the tests import the `recall` package, not just stdlib.
guard-test:
	uv run pytest tests/guard
