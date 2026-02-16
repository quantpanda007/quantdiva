.PHONY: help install test lint serve streamlit clean docker-build docker-up

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install package with dev dependencies
	pip install -e ".[all]"
	pre-commit install

test:  ## Run all tests
	pytest tests/ -v --tb=short

test-unit:  ## Run unit tests only
	pytest tests/unit/ -v

test-regression:  ## Run regression tests
	pytest tests/regression/ -v -m regression

test-cov:  ## Run tests with coverage
	pytest tests/ --cov=. --cov-report=html --cov-report=term-missing

lint:  ## Run linter
	ruff check .
	mypy core/ instruments/ engines/ models/ services/

format:  ## Format code
	ruff format .
	black .

serve:  ## Start FastAPI server
	uvicorn api.fastapi.app:app --host 0.0.0.0 --port 8000 --reload

serve-prod:  ## Start FastAPI in production mode
	uvicorn api.fastapi.app:app --host 0.0.0.0 --port 8000 --workers 4

streamlit:  ## Launch Streamlit dashboard
	streamlit run frontend/streamlit/app.py --server.port 8501

notebook:  ## Start Jupyter notebook
	jupyter notebook notebooks/

clean:  ## Clean build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov dist build *.egg-info

docker-build:  ## Build Docker image
	docker build -t quantlib-pricing:latest -f docker/Dockerfile .

docker-up:  ## Start all services with docker-compose
	docker-compose up -d

docker-down:  ## Stop all services
	docker-compose down

market-build:  ## Build market data for today
	python -m scripts.build_market --env dev --date today

price-batch:  ## Run batch pricing
	python -m scripts.batch_price --env dev --portfolio default
