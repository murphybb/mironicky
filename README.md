# Mironicky

This repository packages the current Mironicky product into two runnable parts:

- `frontend/`: Vite frontend
- `backend/`: FastAPI backend

## What You Need

- Python 3.12+
- Node.js 20+
- `uv`
- Docker services for backend dependencies

The backend expects these services to be reachable:

- MongoDB
- Elasticsearch
- Milvus
- Redis

## Backend Quick Start

```bash
cd backend
cp .env.example .env
uv sync
uv run python src/run.py
```

Backend health checks:

```bash
curl http://127.0.0.1:1995/health
curl http://127.0.0.1:1995/docs
```

Notes:

- `.env.example` is safe to commit. Fill real values into `.env`.
- Basic startup works with local infrastructure defaults from `.env.example`.
- LLM, embedding, and rerank features require real provider configuration.
- First startup is not instant. Dependency injection scan and infrastructure initialization can take around 60-90 seconds on a cold run.
- Current MongoDB migration startup is not the main bottleneck in this repo. The migration directory is `backend/src/migrations/mongodb`, and startup logs show no migration scripts are applied there right now.

## Frontend Quick Start

```bash
cd frontend
npm ci
npm run dev
```

Frontend checks:

```bash
curl http://127.0.0.1:4174/health
```

Open the app:

- `http://127.0.0.1:4174`

## Minimum Bring-Up Flow

1. Start Docker dependencies for the backend.
2. Start the backend and wait for `/health` to return `200`.
3. Start the frontend.
4. Open the page and verify the research APIs return `200`.

## Configuration Boundaries

Do not commit these files:

- `backend/.env`
- any API keys or provider secrets
- local logs, sqlite files, caches, or test artifacts

Use `backend/.env.example` as the public template instead.
