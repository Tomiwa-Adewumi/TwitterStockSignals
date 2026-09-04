PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: install-dev format lint typecheck test coverage check run docker-build

install-dev:
	$(PYTHON) -m pip install -r requirements-dev.txt

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check . --fix

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest -q

coverage:
	$(PYTHON) -m pytest --cov=api --cov=analyzer --cov=database --cov=emailer \
		--cov=main --cov=pipeline --cov=researcher --cov=scraper --cov=worker \
		--cov-report=term-missing --cov-fail-under=80

check: lint typecheck coverage

run:
	$(PYTHON) -m uvicorn api:app --reload

docker-build:
	docker build -t twitter-stock-signals .
