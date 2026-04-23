# Makefile — uv-driven task runner for stays

TARGETS := stays/ tests/ scripts/

.DEFAULT_GOAL := help

.PHONY: help install install-dev mcp mcp-http lint lint-fix \
        format test test-live test-browser test-all build clean docker docker-run \
        coverage

help:
	@echo "Available targets:"
	@echo "  install       Install runtime deps with uv (CLI + MCP included)"
	@echo "  install-dev   Install runtime + dev tooling (ruff, pytest, etc.)"
	@echo "  mcp           Run the MCP stdio server"
	@echo "  mcp-http      Run the MCP streamable HTTP server"
	@echo "  lint          Run ruff check"
	@echo "  lint-fix      Run ruff check --fix"
	@echo "  format        Run ruff format"
	@echo "  test          Run unit + offline tests (live + browser auto-skipped)"
	@echo "  test-live     Run live-marked tests only (hits google.com)"
	@echo "  test-browser  Run browser-verify tests only (requires agent-browser or Playwright)"
	@echo "  test-all      Run unit + live + browser-verify"
	@echo "  coverage      Run offline tests with branch coverage (terminal + HTML at htmlcov/)"
	@echo "  build         Build sdist + wheel"
	@echo "  clean         Remove build artifacts"
	@echo "  docker        Build Docker image"
	@echo "  docker-run    Build + run Docker image on 127.0.0.1:8000"

install:
	uv sync

install-dev:
	uv sync --extra dev

mcp:
	uv run stays mcp

mcp-http:
	uv run stays mcp-http

lint:
	uv run --extra dev ruff check $(TARGETS)

lint-fix:
	uv run --extra dev ruff check --fix $(TARGETS)

format:
	uv run --extra dev ruff format $(TARGETS)

test:
	uv run --extra dev pytest -v

test-live:
	uv run --extra dev pytest -v --live -m live

test-browser:
	uv run --extra dev pytest -v --browser-verify -m browser_verify

test-all:
	uv run --extra dev pytest -v --live --browser-verify

coverage:
	uv run --extra dev pytest --cov --cov-report=term-missing --cov-report=html

build:
	uv build

clean:
	rm -rf dist/ build/ *.egg-info/ .pytest_cache/ .ruff_cache/ .mypy_cache/ htmlcov/ .coverage junit.xml

docker:
	docker build -t stays:dev .

docker-run: docker
	docker run --rm -p 8000:8000 stays:dev
