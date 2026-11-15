# On Windows use Git Bash, or run the commands below by hand.
PY ?= python

.PHONY: install up database migrate dev test lint typecheck check scenarios evals-install evals
EVALS_BIN := $(if $(wildcard .venv-evals/Scripts),.venv-evals/Scripts,.venv-evals/bin)

install:            ## create the venv and install with dev tools
	$(PY) -m venv .venv && .venv/bin/pip install -e ".[dev]" || .venv/Scripts/pip install -e ".[dev]"

up:                 ## Postgres, Redis and Phoenix
	docker compose up -d

database:           ## once, on a Postgres volume from before the split: add the agent's own database
	docker exec tiketa-postgres createdb -U tiketa tiketa_agent

migrate:            ## bring the database schema up to date (the service refuses an older one)
	alembic upgrade head

dev:                ## run with reload (the booking service, tiketa-app, must be up)
	python main.py

test:
	pytest -q

lint:
	ruff check . && ruff format --check .

typecheck:
	mypy

check: lint typecheck test   ## what CI runs

scenarios:          ## play evals/scenarios.json against the running service and grade it (calls the LLM)
	PYTHONPATH=. python scripts/run_scenarios.py

evals-install:      ## DeepEval in its own environment, apart from the service's (evals/requirements.txt says why)
	$(PY) -m venv .venv-evals
	.venv-evals/bin/pip install -r evals/requirements.txt || .venv-evals/Scripts/pip install -r evals/requirements.txt

evals:              ## grade the newest transcript of `make scenarios` with DeepEval (calls the judge model)
	DEEPEVAL_TELEMETRY_OPT_OUT=1 PYTHONUTF8=1 $(EVALS_BIN)/deepeval test run evals/test_conversations.py
	mkdir -p evals/results/deepeval
	cp .deepeval/.latest_test_run.json evals/results/deepeval/latest.json
