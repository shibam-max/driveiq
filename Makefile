.PHONY: up down test migrate seed evals logs clean

up:
	docker compose up --build -d
	@echo "\nDriveIQ running:"
	@echo "  Frontend:     http://localhost:3000"
	@echo "  Backend API:  http://localhost:8080"
	@echo "  Orchestrator: http://localhost:8000/docs"

down:
	docker compose down

migrate:
	docker compose exec orchestrator python -m alembic upgrade head

seed:
	docker compose exec orchestrator python scripts/seed_market_data.py

evals:
	docker compose exec orchestrator python -m evals.run_evals
	@echo "Evals done. Exit code 0 = deploy gate open."

test:
	@echo "--- Java tests ---"
	cd apps/backend && mvn test -B
	@echo "--- Python tests ---"
	cd apps/orchestrator && pytest tests/ -v
	@echo "--- TypeScript tests ---"
	cd apps/frontend && npm test
	@echo "--- Agent evals ---"
	cd apps/orchestrator && python -m evals.run_evals

logs:
	docker compose logs -f

clean:
	cd apps/backend && mvn clean
	find apps/orchestrator -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	cd apps/frontend && rm -rf .next node_modules
