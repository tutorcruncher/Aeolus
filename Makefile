.DEFAULT_GOAL := install

.PHONY: install
install:
	uv sync

.PHONY: install-dev
install-dev:
	uv sync --group dev

.PHONY: format
format:
	uv run ruff check --fix .
	uv run ruff format .

.PHONY: lint
lint:
	uv run ruff check .
	uv run ruff format --check .

.PHONY: test
test:
	uv run pytest

.PHONY: clean
clean:
	rm -rf `find . -name __pycache__`
	rm -f `find . -type f -name '*.py[co]'`
	rm -f `find . -type f -name '*~'`
	rm -f `find . -type f -name '.*~'`
	rm -rf .cache
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf htmlcov
	rm -f .coverage
	rm -f .coverage.*

.PHONY: run
run:
	uv run python server.py

.PHONY: run-prod
run-prod:
	gunicorn server:app --config gunicorn.conf.py
