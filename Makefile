# On Windows use Git Bash, or run the commands below by hand.
PY ?= python

.PHONY: install up seed dev test lint typecheck check scenarios

install:            ## create the venv and install with dev tools
	$(PY) -m venv .venv && .venv/bin/pip install -e ".[dev]" || .venv/Scripts/pip install -e ".[dev]"

up:                 ## Postgres, Redis and Phoenix
	docker compose up -d

seed:               ## sample films and a week of showtimes
	PYTHONPATH=. python scripts/seed.py --days 7

dev:                ## run with reload
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
