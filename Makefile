.PHONY: help setup db-up db-down migrate revision seed symbols dev-backend dev-frontend test lint build

help:
	@echo "setup         백엔드 venv + 프론트엔드 의존성 설치"
	@echo "db-up         PostgreSQL 컨테이너 기동"
	@echo "db-down       PostgreSQL 컨테이너 중지"
	@echo "migrate       DB 마이그레이션 적용"
	@echo "revision      모델 변경으로부터 마이그레이션 생성 (m=\"메시지\")"
	@echo "seed          개발용 초기 데이터 생성 (관리자1 + 스터디원9 + 예시 마켓)"
	@echo "symbols       종목 마스터 CSV 임포트 (f=\"symbols.csv\")"
	@echo "dev-backend   백엔드 개발 서버 (http://localhost:8000/docs)"
	@echo "dev-frontend  프론트엔드 개발 서버 (http://localhost:5173)"
	@echo "test          백엔드 테스트"
	@echo "lint          ruff + tsc"

setup:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
	cd frontend && npm install
	@test -f .env || cp .env.example .env
	@echo "완료. .env 를 채운 뒤 'make db-up && make migrate && make seed' 를 실행하세요."

db-up:
	docker compose up -d db

db-down:
	docker compose stop db

migrate:
	cd backend && .venv/bin/alembic upgrade head

revision:
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(m)"

seed:
	cd backend && .venv/bin/python -m scripts.seed

symbols:
	cd backend && .venv/bin/python -m scripts.import_symbols $(f)

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/python -m pytest -q

lint:
	cd backend && .venv/bin/ruff check app tests scripts
	cd frontend && npx tsc --noEmit

build:
	cd frontend && npm run build
