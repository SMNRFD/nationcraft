.PHONY: help install dev test lint typecheck format migrate run-api run-bot run-worker up down clean docs

PYTHON := python
PKG    := nationcraft

help:
        @echo "NationCraft — available targets:"
        @grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install package in editable mode
        $(PYTHON) -m pip install -e ".[dev]"

dev: install ## Install dev dependencies
        $(PYTHON) -m pip install -e ".[dev]"

lint: ## Run ruff
        ruff check src tests

typecheck: ## Run mypy
        mypy src/$(PKG)

format: ## Format code with ruff
        ruff format src tests
        ruff check --fix src tests

test: ## Run tests
        pytest

migrate: ## Run alembic migrations to head
        alembic upgrade head

run-api: ## Run FastAPI server
        $(PYTHON) -m $(PKG).cli api

run-bot: ## Run Telegram bot
        $(PYTHON) -m $(PKG).cli bot

run-worker: ## Run tick worker
        $(PYTHON) -m $(PKG).cli worker

run: ## Run all components (API + worker + bot) in one process
        $(PYTHON) main.py --log-format console

run-api-main: ## Run only API via main.py
        $(PYTHON) main.py --only api --log-format console

up: ## Start full stack via docker-compose
        docker-compose up -d --build

down: ## Stop full stack
        docker-compose down

clean: ## Remove build artifacts
        rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache coverage.xml htmlcov

docs: ## Build documentation
        @echo "See docs/ for Markdown documentation."
