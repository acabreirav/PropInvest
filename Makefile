.PHONY: setup ingest build score test gates serve report rebuild lint

setup:
	uv sync
	PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0 uv run playwright install chromium

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy --strict src/flujocero/finance

ingest:
	uv run python -m flujocero.cli ingest --all

build:
	uv run python -m flujocero.cli build

score:
	uv run python -m flujocero.cli score

test:
	uv run pytest -q

gates: lint test
	uv run python -m flujocero.cli gates

serve:
	uv run uvicorn flujocero.api.app:app --reload --port 8000

report:
	uv run python -m flujocero.cli report

rebuild:
	uv run python -m flujocero.cli rebuild --from-raw
