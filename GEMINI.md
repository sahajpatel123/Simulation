# TheCee — Project Context & Instructions for Gemini

> **CRITICAL MANDATE**: DO NOT analyze, read, or modify files that are listed in `.claudeignore`. Files listed in `.claudeignore` (such as build outputs, virtual environments, cache directories, node_modules, and lock files) are just token and time wasters.

## 1. What This Project Is

**TheCee** is a pre-launch behavioral simulation engine designed to predict how 10,000 AI consumers will respond to a startup idea. It evaluates consumer decision-making through a Markov funnel, calibrated by 52 consumer clusters and 21 domain architects.

## 2. Architecture Overview

- **Frontend**: Next.js 15 (React, TypeScript), located under `src/` and `app/` (for page routing in the frontend).
- **Backend**: FastAPI (Python), located under `backend/app/`. (Note: Historically there was an `app/` directory at root; prefer `backend/app/` for the modern structure utilizing NVIDIA NIMs).
- **Worker/Task Queue**: Celery (Python) for asynchronous simulation tasks.
- **Database**: PostgreSQL (using SQLAlchemy ORM).
- **Cache/Broker**: Redis.
- **LLM Provider**: NVIDIA NIMs (OpenAI-compatible) and Anthropic (Legacy). The backend has been shifting towards using NVIDIA NIMs (`NVIDIA_API_KEY`) via `backend/app/core/claude_client.py`.

## 3. Key Components

### 3.1 Consumer Clusters (`backend/app/simulation/clusters/registry.py`)
- 52 distinct consumer archetypes (e.g., `metro_power_professional`, `tier3_first_time_app_user`).
- Each cluster possesses 8 normalized traits (income, literacy, motivation, trust, price sensitivity, risk aversion, patience, social orientation).

### 3.2 Domain Architects (`backend/app/simulation/architects/`)
- 20 specialists that evaluate domains like pricing, onboarding, trust, market timing, etc., for all clusters.
- Architects output adjustments to Markov transition matrices and identify failure modes.

### 3.3 Markov Funnel (`backend/app/simulation/markov.py`)
- 7-state behavioral model: `ARRIVE` → `BROWSE` → `CONSIDER` → `DECIDE` → `PURCHASE` or `ABANDON`.
- Funnel probabilities are manipulated based on Architect evaluations and startup assumptions.

### 3.4 Conductor (`backend/app/simulation/conductor.py`)
- The main orchestrator. It processes project inputs, determines product types, builds the agent profiles, routes through architects, runs the funnel, and aggregates results.

## 4. Workflows & Rules

### Backend Workflows
- **Database Migrations**: Add column definitions to `migrate_and_start.py`. Do NOT use `ALTER TABLE` inside route handlers.
- **Sessions**: Use `Depends(get_db)` in FastAPI routers and `SimulationTask.db` in Celery tasks. Do not call `db.commit()` inside loops.
- **Pydantic**: Use `model_config = {"from_attributes": True}` for ORM validation.

### API & LLM Patterns
- The system heavily relies on structured JSON responses from LLMs. Fallback mechanisms in `claude_client.py` (`claude_call_with_fallback`) handle timeouts.
- Be careful with `max_tokens` when hitting NVIDIA NIM models, keeping requests within model capabilities (e.g., 4096 or 8192, not 24000).

## 5. Directory Structure
```
thecee/
├── backend/app/          # Primary Python FastAPI backend
├── src/                  # Next.js Frontend application
├── tests/                # Pytest test suite
├── migrate_and_start.py  # Server startup and DB schema auto-migration
├── start_worker.sh       # Celery worker startup script
├── pyproject.toml        # Python configurations
├── requirements.txt      # Python dependencies
├── package.json          # Node.js dependencies
└── .claudeignore         # Files to ignore during AI analysis
```

## 6. Real-time Logic & Workarounds
- Use standard polling (e.g., `/simulations/{id}/progress`) or WebSocket for real-time frontend updates. Note that `sync_broadcast` only reaches clients in the same process, so polling is often the safer fallback.

*Note: This file is dynamically generated and maintained by Gemini as an internal memory structure for the project context.*