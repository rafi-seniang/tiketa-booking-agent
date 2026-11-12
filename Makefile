# On Windows use Git Bash, or run the commands below by hand.
PY ?= python

.PHONY: install up database migrate dev test lint typecheck check scenarios

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
