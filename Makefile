.PHONY: setup dev test lint typecheck security eval build up production down

setup:
	python3.12 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
	cd frontend && npm ci
dev:
	@echo "Run backend: cd backend && uvicorn app.api.main:app --reload; frontend: cd frontend && npm run dev"
test:
	cd backend && pytest
	cd frontend && npm test -- --run
lint:
	cd backend && ruff check .
	cd frontend && npm run lint
typecheck:
	cd backend && mypy app
	cd frontend && npm run typecheck
security:
	cd backend && bandit -q -r app
eval:
	cd backend && python -m app.evals.run
build:
	docker compose build
up:
	docker compose up --build -d
production:
	docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml up --build -d
down:
	docker compose down
