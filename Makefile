PYTHON ?= python3.12
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: install run test lint fmt migrate samples clean

install:  ## Create the virtualenv and install the app with dev tools
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

run:  ## Start the API with auto-reload on http://localhost:8000
	$(BIN)/uvicorn certgen.main:create_app --factory --reload --host 0.0.0.0 --port 8000

test:  ## Run the test suite (temp SQLite + inline dispatcher)
	$(BIN)/pytest

lint:  ## Static checks
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

fmt:  ## Auto-format and auto-fix
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

migrate:  ## Apply database migrations to DATABASE_URL
	$(BIN)/alembic upgrade head

samples:  ## Render samples/ (PDFs, PNG previews, seal images)
	$(BIN)/python scripts/render_samples.py

clean:
	rm -rf storage certgen.db certgen.db-* .pytest_cache .ruff_cache
