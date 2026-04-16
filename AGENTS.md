# TheCee — Agent & AI Coding Guide

This document is the authoritative reference for any AI agent (Claude, Codex, etc.)
working on the TheCee simulation engine backend.

---

## What this repo is

TheCee is a **Python FastAPI backend** that simulates how 10 000 AI consumers
respond to a startup idea. It is **not** a Next.js project. Ignore any
references to Next.js conventions.

The frontend (Next.js 16) lives in `src/` but is deployed separately on Vercel.
Do not modify `src/` unless the task explicitly involves the frontend.

---

## Running the project

```bash
# API (also runs DB migrations)
python migrate_and_start.py

# Celery worker (separate terminal)
./start_worker.sh

# Tests
pytest tests/ -v

# Interactive API docs
open http://localhost:8000/docs
```

---

## Key mental models

### 1. The simulation pipeline

```
ProjectDescription
  → ClaudeExtracts(Assumptions)
  → ScoreAssumptions()          # signal quality: 0.0 – 1.0
  → AgentProfileGenerator       # samples 10 000 agents from 52 clusters
  → Conductor.run()             # calls all 21 architects per cluster
  → Markov funnel               # ARRIVE → BROWSE → CONSIDER → DECIDE → PURCHASE
  → ResultsAggregator
  → AccountabilityEngine        # ranked DomainFindings
  → Simulation.results_json     # persisted to PostgreSQL
```

### 2. Clusters (`app/simulation/clusters/`)

52 consumer archetypes. Each is a `ClusterDefinition` dataclass with:
- **8 trait floats** in `[0.0, 1.0]`: `income_level`, `digital_literacy`,
  `motivation`, `trust`, `price_sensitivity`, `risk_aversion`,
  `patience_score`, `social_orientation`
- `population_weight` (all 52 sum to 1.0)
- `product_affinities`, `known_failure_modes`, `demographic_profile`

The canonical IDs are in `migrate_and_start._CLUSTER_IDS`. Every cluster ID
must exist in the `cluster_parameters` PostgreSQL table.

### 3. Architects (`app/simulation/architects/`)

21 domain-specialist modules. Each subclasses `BaseArchitect` and must
implement:
- `name: str` — unique string used as DB key
- `product_types: list[str]` — which product categories this activates for
  (empty = all)
- `compute(cluster, agent_profile, assumptions, env_params) → ArchitectOutput`
- `generate_report(outputs) → DomainReport`

Architects may optionally override `transition_overrides()` to shift Markov
state-transition probabilities.

**Never modify `base.py` unless you are changing the architect interface.**
All 21 subclasses depend on it.

### 4. The Conductor (`app/simulation/conductor.py`)

Orchestrates architects across all 52 clusters. For each (architect, cluster)
pair it calls `compute()`, collects `ArchitectOutput`s, applies
`transition_overrides()` to the Markov matrix, then runs the Markov funnel.

Do not call `compute()` directly in tests — use `Conductor.run()` with a
minimal `agents`, `env_params`, and `assumptions` payload.

### 5. Celery tasks (`app/tasks/`)

Long-running work (simulations, stress tests) runs in Celery workers.
The API enqueues with `.delay()`, returns a task ID, and the frontend polls
`/simulations/{id}/progress` or listens on the WebSocket.

**Important:** `sync_broadcast()` in `app/core/websocket.py` can only push
WebSocket messages to clients connected to the *same process*. In production
the API and worker are separate processes, so `sync_broadcast` from a Celery
task is a no-op. Polling is the reliable path.

### 6. Migrations (`migrate_and_start.py`)

Runs on every Railway deploy before uvicorn starts. It:
1. Creates the pgvector extension
2. Calls `Base.metadata.create_all()` (all SQLAlchemy models)
3. Runs `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for all additive schema
   changes (idempotent)
4. Creates raw SQL tables (cluster_parameters, founder_outcomes, etc.)
5. Seeds `cluster_parameters` with 416 rows (52 clusters × 8 traits)

**Add new schema changes here, not inline in route handlers.**

---

## Coding rules

### Python
- Type all function arguments and return types.
- Use `from __future__ import annotations` in files with forward references.
- All DB operations use SQLAlchemy ORM or `text()` with named params — never
  f-string SQL.
- Session lifecycle: use `Depends(get_db)` in API routes. In Celery tasks use
  the `SimulationTask.db` property (it auto-closes on task completion).
- Never call `db.commit()` inside a loop — batch, then commit once.

### FastAPI routes
- Put imports at the module top, never inside function bodies.
- Use `HTTPException` with meaningful `detail` strings.
- Return Pydantic response models — never return raw ORM objects.
- Route function names must be descriptive verbs: `create_project`,
  `get_simulation_results`, not `project` or `sim`.

### Pydantic schemas
- Input schemas live in `app/schemas/`. One file per domain.
- Use `model_config = {"from_attributes": True}` on output schemas that
  are built from ORM objects via `model_validate()`.
- Validate enums at the schema level, not in route handlers.

### Celery tasks
- Decorate with `@celery_app.task(bind=True, base=SimulationTask, …)`.
- Always persist a `FAILED` status on exception — never let a task fail silently.
- Use `self.update_state(state="PROGRESS", meta={…})` to report progress.
- `max_retries=2`, `acks_late=True`, `reject_on_worker_lost=True`.

### Architects
- One file per architect in `app/simulation/architects/`.
- `compute()` must be pure and fast (no I/O, no DB calls).
- Use `_apply_correction()` at the end of `compute()` to apply learned
  calibration scalars from the DB.
- `generate_report()` must handle an empty `outputs` list gracefully.

---

## Database tables (quick reference)

| Table | Notes |
|-------|-------|
| `users` | JWT auth; `tier` field for future gating |
| `projects` | Core entity; JSONB columns for premortem, stress_test, interventions, competitive |
| `assumptions` | Extracted by Claude; scored by `scored_assumption.py` |
| `environments` | Simulation environment (scenario preset or manual params) |
| `simulations` | Status, results_json (JSONB), signal_quality, task_id |
| `decisions` | Decision tracking per project |
| `outcomes` | Outcome logging (actual vs predicted) |
| `outcome_tracker` | Per-project conversion tracking over time |
| `prototypes` | HTML + funnel_graph_json generated by Claude |
| `cluster_run_summaries` | Per-cluster summary for each simulation run |
| `consumer_agents` | Sampled agent profiles (optional persistence) |
| `cluster_parameters` | 416 rows (52 × 8); calibrated trait base values |
| `architect_corrections` | Per-architect, per-cluster correction scalars |
| `founder_outcomes` | Real conversion rates submitted by founders |
| `user_claim_accuracy_profiles` | Per-user accuracy tracking per architect |
| `user_market_blindspots` | Recurring blind spots surfaced to users |
| `user_simulation_accuracy_history` | Predicted vs actual per run |

---

## What NOT to do

- ❌ Do not add `pip install` inside Dockerfile — put new deps in `requirements.txt`.
- ❌ Do not add `ALTER TABLE` inside route handlers — put it in `migrate_and_start.py`.
- ❌ Do not import inside function bodies.
- ❌ Do not use `allow_origins=["*"]` — CORS is already restricted to `FRONTEND_URL`.
- ❌ Do not hardcode cluster IDs in new code — use `ClusterRegistry().all_clusters()`.
- ❌ Do not modify the `" 2.*"` files — they are iCloud duplicates, already gitignored.
- ❌ Do not commit `.env`, `.env.local`, or `.env.production`.
- ❌ Do not call `BaseMetadata.create_all()` anywhere except `migrate_and_start.py`.
- ❌ Do not break the `OutcomeTracker.back_populates="outcome_trackers"` ↔
  `Project.outcome_trackers` pairing.

---

## Adding a new architect

1. Create `app/simulation/architects/my_domain.py`
2. Subclass `BaseArchitect`, implement `name`, `product_types`, `compute()`,
   `generate_report()`
3. Register it in `app/simulation/conductor.py` (add to the architects list)
4. The architect name is automatically tracked in `architect_corrections`

## Adding a new API endpoint

1. Choose the right router file in `app/api/v1/`
2. Write the Pydantic schema in `app/schemas/`
3. Add any new DB columns to `migrate_and_start.py`
4. Register the schema model in the router's `response_model=`
5. Write a test in `tests/`

## Adding a new cluster

1. Add a `ClusterDefinition` to `app/simulation/clusters/registry.py`
2. Add the cluster ID to `_CLUSTER_IDS` in `migrate_and_start.py`
3. The next deploy will seed 8 new rows in `cluster_parameters`

---

## Environment variables required to run

See `.env.example` for the full list. Minimum for local dev:

```
DATABASE_URL=postgresql://...
SECRET_KEY=<32+ random chars>
ANTHROPIC_API_KEY=sk-ant-...
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
FRONTEND_URL=http://localhost:3000
```
