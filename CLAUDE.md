# TheCee — AI Coding Context & Architecture Guide

> **For AI Models**: This file is your complete orientation to TheCee. Read this first. Everything you need to know is here.

---

## 1. What This Project Is

**TheCee is a behavioral simulation engine that predicts how 10,000 AI consumers will respond to a startup idea.**

It is **NOT** a web frontend. The Next.js frontend in `src/` is deployed separately and should be ignored unless explicitly working on UI generation.

**Core Purpose**: Simulate consumer decision-making through a Markov funnel, calibrated by 52 consumer clusters × 21 domain architects, to predict conversion rates, identify failure modes, and generate actionable business recommendations.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TheCee Simulation Pipeline                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. Project Input (description, assumptions, product type)                  │
│  2. Assumption Extraction & Scoring (Claude Sonnet 4.5)                     │
│  3. Agent Generation (52 clusters × traits → 10,000 profiles)               │
│  4. Conductor.run() — orchestrates all architects per cluster               │
│  5. Each Architect.compute() — evaluates domain for each cluster            │
│  6. Markov Funnel — ARRIVE→BROWSE→CONSIDER→DECIDE→PURCHASE/ABANDON         │
│  7. ResultsAggregator — combines cluster results                            │
│  8. AccountabilityEngine — identifies top failure domains                   │
│  9. JSONB output stored in PostgreSQL                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Quick Start Commands

```bash
# Start the API (runs migrations first)
python migrate_and_start.py

# Start Celery worker (separate terminal)
./start_worker.sh

# Run tests
pytest tests/ -v

# Check database schema
python -c "
from app.core.database import engine
from sqlalchemy import inspect
for t in inspect(engine).get_table_names():
    print(t)
"

# Test imports work
python -c "from app.main import app; print('OK')"

# Interactive API docs
open http://localhost:8000/docs
```

---

## 3. The Simulation Pipeline (Must Know)

### 3.1 Cluster System — 52 Consumer Archetypes

**Location**: `app/simulation/clusters/registry.py`

- **52 consumer clusters** representing realistic Indian consumer segments
- Each cluster has 8 traits in `[0.0, 1.0]`:
  - `income_level`, `digital_literacy`, `motivation`, `trust`
  - `price_sensitivity`, `risk_aversion`, `patience_score`, `social_orientation`
- Population weights sum to exactly `1.0`
- Cluster definitions stored in `cluster_parameters` table (416 rows = 52 clusters × 8 traits)

**Key clusters by segment**:
- **Metro professionals**: `metro_power_professional`, `senior_enterprise_decision_maker`
- **Students**: `high_literacy_student_freemium_ceiling`, `low_literacy_student_passive`
- **Tier-2/3**: `tier3_first_time_app_user`, `tier2_price_sensitive_pragmatist`
- **Hardware-specific**: `health_hardware_enthusiast`, `smart_home_early_adopter`
- **Behavioral**: `anxiety_driven_researcher`, `impulsive_trend_follower`

**Important**: Never hardcode cluster IDs. Use:
```python
from app.simulation.clusters.registry import ClusterRegistry
registry = ClusterRegistry()
all_clusters = registry.all_clusters()  # Returns list of 52 ClusterDefinition
cluster = registry.get_cluster("metro_power_professional")
```

### 3.2 Architect System — 20 Domain Specialists

**Location**: `app/simulation/architects/`

Each architect evaluates one business domain for all 52 clusters:

| Architect | Domain | Product Type Restrictions |
|-----------|--------|---------------------------|
| `MarketTimingArchitect` | Market need, timing, competition | All |
| `CompetitiveDynamicsArchitect` | Incumbent response, switching friction | All |
| `TrustArchitect` | Brand trust, credibility signals | All |
| `PricingArchitect` | Price point, value perception | All |
| `OnboardingArchitect` | First-usage experience | All |
| `FeatureAdoptionArchitect` | Feature usage depth | SAAS, developer_tool |
| `RetentionArchitect` | Long-term engagement | All |
| `SupportFrictionArchitect` | Support accessibility | All |
| `ViralityArchitect` | Word-of-mouth potential | All |
| `MacroeconomicArchitect` | Economic headwinds/tailwinds | All |
| `DemographicInteractionArchitect` | Demographic matching | All |
| `AssumptionCascadeArchitect` | Assumption validation | All |
| **Hardware-specific** | | |
| `PurchaseDecisionArchitect` | Hardware purchase journey | Hardware types |
| `PhysicalSensoryArchitect` | Touch/feel factors | Hardware |
| `PerformanceThresholdArchitect` | Minimum acceptable performance | Hardware |
| `SetupFirstUseArchitect` | Out-of-box experience | Hardware |
| `EcosystemCompatibilityArchitect` | Ecosystem lock-in | Hardware |
| `DistributionChannelArchitect` | Availability channels | Hardware |
| `AftersalesLifecycleArchitect` | Post-purchase experience | Hardware |
| `HealthSafetyHardwareArchitect` | Health/safety concerns | Health hardware |

**Important**: All architects subclass `BaseArchitect` in `base.py`. **Never modify `base.py`** unless changing the architect interface — all 21 subclasses depend on it.

**Key architect methods**:
```python
def compute(cluster, agent_profile, assumptions, env_params) -> ArchitectOutput:
    # Returns metrics dict, flags, narrative_findings, severity

def generate_report(outputs) -> DomainReport:
    # Aggregates outputs across all clusters into one finding

def transition_overrides(output) -> dict[tuple[str, str], float]:
    # Optional: returns Markov transition matrix adjustments
```

### 3.3 Conductor — The Orchestrator

**Location**: `app/simulation/conductor.py`

The `Conductor.run()` method:
1. Detects product type from description/assumptions
2. Computes cluster reweighting based on product type/target segment
3. Runs all architects for each cluster (respecting `product_types` filters)
4. Applies `transition_overrides()` from architect outputs
5. Runs Markov funnel to convert cluster metrics to predictions
6. Computes accountability metrics (which architects flagged critical issues)
7. Writes `cluster_run_summaries` to DB if `db` and `simulation_id` provided

**Dependency map** (architects can use others' outputs):
```python
DEPENDENCY_MAP = {
    "RetentionArchitect": {
        "feature_depth_score": ("FeatureAdoptionArchitect", "feature_depth_score"),
        "onboarding_completion_rate": ("OnboardingArchitect", "onboarding_completion_rate"),
    },
    "ViralityArchitect": {
        "day30_survival": ("RetentionArchitect", "day30_survival"),
    },
    # ... etc
}
```

### 3.4 Markov Funnel — State Transition Model

**Location**: `app/simulation/markov.py`

**7-state behavioral model** (ordered by flow):
```
ARRIVE → BROWSE → CONSIDER → DECIDE → PURCHASE (terminal)
                ↘ CONSIDER → ABANDON (terminal)
                ↘ ABANDON → RETURN → BROWSE/CONSIDER (re-entry)
```

**Transition matrix** (row = from, col = to):
| From/To | ARRIVE | BROWSE | CONSIDER | DECIDE | PURCHASE | ABANDON | RETURN |
|---------|--------|--------|----------|--------|----------|---------|--------|
| ARRIVE | 0 | 0.87 | 0 | 0 | 0 | 0.13 | 0 |
| BROWSE | 0 | 0 | 0.62 | 0 | 0 | 0.38 | 0 |
| CONSIDER | 0 | 0.16 | 0 | 0.46 | 0 | 0.38 | 0 |
| DECIDE | 0 | 0 | 0.14 | 0 | 0.31 | 0.55 | 0 |
| PURCHASE | 0 | 0 | 0 | 0 | 0 | 0.72 | 0.28 |
| ABANDON | 0.81 | 0 | 0 | 0 | 0 | 0 | 0.19 |
| RETURN | 0 | 0.58 | 0.22 | 0 | 0 | 0.20 | 0 |

**Assumption adjustments**: Keywords in assumptions modify transition probabilities:
- `pric`, `cost`, `fee`, `expensive` → reduces DECIDE→PURCHASE
- `trust`, `review`, `testimonial` → reduces BROWSE→CONSIDER
- `retention`, `return`, `loyal` → increases PURCHASE→RETURN
- `ux`, `ui`, `confus`, `friction` → reduces BROWSE→CONSIDER

### 3.5 Agent Generation

**Location**: `app/simulation/sampling.py`, `app/simulation/profiles.py`

- 10,000 agents sampled from 52 clusters weighted by `population_weight`
- Each agent has trait variance applied for realism (not all agents in a cluster are identical)
- Agents have `to_dict()` method for Markov simulation

---

## 4. Database Schema (PostgreSQL)

**Location**: `migrate_and_start.py` (add columns here)

### Core Tables

| Table | Purpose |
|-------|---------|
| `users` | JWT auth, tier, subscription, Razorpay IDs |
| `projects` | Idea descriptions, JSONB columns for premortem, stress_test, interventions, competitive |
| `environments` | Simulation parameters (AOV, growth rate, price sensitivity) |
| `simulations` | Status, results_json (JSONB), signal_quality, task_id, error_message |
| `assumptions` | Claude-extracted assumptions with scores |
| `decisions` | AI-generated business decisions with results |
| `outcomes` | Actual vs predicted conversion, MRR, variance |
| `outcome_tracker` | Per-project conversion tracking over time |
| `cluster_run_summaries` | Per-cluster breakdown per simulation (agents_assigned, architect_scores, primary_drop_trigger) |
| `cluster_parameters` | 416 rows (52 × 8 traits) — base/calibrated values |
| `architect_corrections` | Per-architect correction scalars from learning system |
| `founder_outcomes` | Real-world conversion data for calibration |
| `user_claim_accuracy_profiles` | Per-user accuracy per architect (EMA-based) |
| `user_market_blindspots` | Recurring prediction errors surfaced to users |
| `user_simulation_accuracy_history` | Predicted vs actual per run with trend |
| `generated_uis` | HTML prototypes + funnel graphs from Claude |
| `ui_simulation_sessions` | Agent behavior in UI simulation |
| `hardware_products`, `hardware_3d_models`, `hardware_test_configs`, `hardware_test_results`, `hardware_manufacturing_estimates` | Hardware product database |

### Important DB Notes

1. **pgvector extension** must be enabled: `CREATE EXTENSION IF NOT EXISTS vector;`
2. **Never add ALTER TABLE in route handlers** — always add to `migrate_and_start.py`
3. All migrations are additive (idempotent)
4. **Session management**: Use `Depends(get_db)` in API routes; use `SimulationTask.db` in Celery tasks

---

## 5. Claude API Integration

### Model Configuration

**Location**: `app/core/claude_client.py`, `app/api/v1/projects.py`

| Task | Model | Purpose |
|------|-------|---------|
| Assumption extraction | `claude-sonnet-4-20250514` | Extract assumptions from idea |
| UI/prototype generation | `claude-haiku-4-5-20251001` | Generate HTML landing page |
| Premortem analysis | `claude-haiku-4-5-20251001` | Identify potential failures |
| Intervention generation | `claude-haiku-4-5-20251001` | Suggest fixes for issues |
| Competitive analysis | `claude-haiku-4-5-20251001` | Analyze competitors |

### Response Parsing Pattern

**Always use this pattern** (found in `projects.py`):
```python
# 1. Strip markdown fences
content = response.content.strip()
if content.startswith("```json"):
    content = content[7:]
if content.endswith("```"):
    content = content[:-3]
content = content.strip()

# 2. Use regex fallback for JSON
import re
raw_json = re.search(r"\{.*\}", content, re.DOTALL)
if raw_json:
    data = json.loads(raw_json.group())

# 3. Raise on failure, never crash silently
if not data:
    raise HTTPException(status_code=500, detail="Failed to parse Claude response")
```

---

## 6. Celery Architecture

### Task Structure

**Location**: `app/tasks/`

| Task File | Purpose |
|-----------|---------|
| `simulation_tasks.py` | Main simulation orchestration |
| `ui_simulation_tasks.py` | UI generation + agent simulation |
| `calibration_tasks.py` | Learning system recalibration |
| `stress_test_tasks.py` | Load testing simulations |
| `decision_tasks.py` | Business decision generation |
| `hardware_tasks.py` | Hardware product simulations |
| `retention_email_tasks.py` | User engagement emails |

### Celery Best Practices

1. **Always persist FAILED status on exception**:
```python
@celery_app.task(bind=True, base=SimulationTask)
def my_task(self, project_id):
    try:
        # ... work ...
    except Exception as e:
        self.db.execute(text("UPDATE simulations SET status='FAILED', error_message=%s WHERE id=%s"), (str(e), simulation_id))
        raise
```

2. **Report progress**:
```python
self.update_state(state="PROGRESS", meta={"current": i, "total": n})
```

3. **Retry config**:
```python
max_retries=2, acks_late=True, reject_on_worker_lost=True
```

### Important: WebSocket Broadcasting

**CRITICAL**: `sync_broadcast()` in `app/core/websocket.py` only pushes to clients in the *same process*.

In production, the API and Celery worker run as separate processes. A `sync_broadcast()` called from a Celery task **will not reach any frontend clients**.

**Solution**: Frontend must poll `/simulations/{id}/progress` for reliable status updates.

---

## 7. Coding Rules (Strict)

### Python

- **Type everything**: All function arguments and return types must be typed
- **Import at module top**: Never import inside function bodies
- **Use `from __future__ import annotations`** for files with forward references
- **SQLAlchemy**: Use ORM for CRUD, `text()` with named params for complex queries
- **Session lifecycle**: Use `Depends(get_db)` in API routes; use `SimulationTask.db` in Celery tasks
- **Never call `db.commit()` inside a loop** — batch and commit once

### FastAPI Routes

- Route function names: **descriptive verbs** (`create_project`, `get_simulation_results`) — not `project` or `sim`
- Return Pydantic response models only — never raw ORM objects
- Use `HTTPException` with meaningful `detail` strings
- Pydantic schemas validate enums at schema level, not in handlers

### Pydantic Schemas

- Input schemas in `app/schemas/` — one file per domain
- Output schemas: use `model_config = {"from_attributes": True}` when building from ORM via `model_validate()`

### Architects

- One file per architect in `app/simulation/architects/`
- `compute()` must be pure and fast — no I/O, no DB calls
- Use `_apply_correction()` at end of `compute()` to apply learned calibration scalars from DB
- `generate_report()` must handle empty `outputs` list gracefully

---

## 8. Adding New Features

### Adding a New Architect

1. Create `app/simulation/architects/my_domain.py`
2. Subclass `BaseArchitect`, implement `name`, `product_types`, `compute()`, `generate_report()`
3. Register in `app/simulation/conductor.py` → `_build_architect_registry()`
4. Add to `ARCHITECT_STACKS[product_type]` if product-type specific
5. Register in `DEPENDENCY_MAP` if consuming other architects' outputs
6. Add DB column to `migrate_and_start.py` if storing architect corrections

### Adding a New Cluster

1. Create `ClusterDefinition` in `app/simulation/clusters/registry.py`
2. Add cluster ID to `_CLUSTER_IDS` in `migrate_and_start.py`
3. Next deploy seeds 8 new rows in `cluster_parameters`

### Adding a New API Endpoint

1. Choose router in `app/api/v1/` (projects, simulations, users, etc.)
2. Create schema in `app/schemas/`
3. Add DB columns to `migrate_and_start.py`
4. Register schema in router's `response_model=`
5. Write test in `tests/`

### Adding Database Columns

**NEVER do this in route handlers**:
```python
# WRONG — will run on every request
db.execute(text("ALTER TABLE projects ADD COLUMN new_field TEXT"))
```

**DO this instead**:
```python
# migrate_and_start.py
for table, column, col_type in [
    ("projects", "new_field", "TEXT"),
]:
    try:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"))
        conn.commit()
    except Exception:
        conn.rollback()
```

---

## 9. Common Pitfalls (Don't Do These)

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| Importing inside function | Slow, errors in tests | Put imports at module top |
| Adding ALTER TABLE in route | Runs on every request, DB lock | Add to `migrate_and_start.py` |
| Using `model.dict()` | Deprecated in Pydantic v2 | Use `model.model_dump()` |
| Using `Session` without `Depends(get_db)` | Session lifecycle issues | Use dependency injection |
| Hardcoding cluster IDs | Breaks when clusters change | Use `ClusterRegistry().all_clusters()` |
| Assuming WebSocket reaches Celery | No-op in separate process | Use polling `/simulations/{id}/progress` |
| Breaking `back_populates="outcome_trackers"` | SQLAlchemy relationship broken | Keep consistent with `Project.outcome_trackers` |
| Touching `" 2.*"` files | Modifying duplicate iCloud artifact | Ignore — already `.gitignore`d |

---

## 10. File Structure Reference

The FastAPI package lives in **`backend/app/`**. The `backend/` wrapper keeps Python code out of the Next.js `src/` tree and ensures imports resolve correctly as `from app…` when `PYTHONPATH` includes `backend` (Docker, `start_worker.sh`, `pytest` via `pyproject.toml`) or when running **`migrate_and_start.py`**, which prepends `backend` to `sys.path`. Do not create a root-level `app/` directory — it is gitignored and has no role in the runtime.

```
thecee/
├── backend/app/            # Python package layout matches the tree below as app/
│   ├── api/v1/              # API route handlers
│   │   ├── projects.py      # Main project CRUD, Claude integrations
│   │   ├── simulations.py   # Simulation status/results
│   │   ├── users.py         # User management
│   │   ├── decisions.py     # AI-generated decisions
│   │   ├── outcomes.py      # Actual vs predicted outcomes
│   │   ├── calibration.py   # Learning system endpoints
│   │   ├── hardware.py      # Hardware product endpoints
│   │   ├── ui_generation.py # HTML/prototype generation
│   │   ├── reports.py       # Export/report endpoints
│   │   ├── analytics.py     # Admin analytics (admin-only)
│   │   ├── billing.py       # Razorpay payment handling
│   │   ├── websocket.py     # WebSocket broadcast helpers
│   │   └── __init__.py      # Router registration
│   │
│   ├── core/                # Shared utilities
│   │   ├── config.py        # Settings (Pydantic BaseSettings)
│   │   ├── database.py      # Engine, SessionLocal, get_db
│   │   ├── redis_client.py  # Redis client singleton
│   │   ├── claude_client.py # Claude API wrapper
│   │   ├── websocket.py     # sync_broadcast() helper
│   │   ├── auth.py          # JWT helpers
│   │   ├── security.py      # CORS, headers, sanitization
│   │   └── ...
│   │
│   ├── simulation/          # Core simulation engine
│   │   ├── architects/      # 21 domain architects
│   │   │   ├── base.py      # BaseArchitect (DO NOT MODIFY)
│   │   │   ├── market_timing.py
│   │   │   ├── pricing.py
│   │   │   └── ...
│   │   ├── clusters/        # 52 consumer clusters
│   │   │   ├── registry.py  # ClusterRegistry (main entry)
│   │   │   ├── definitions.py
│   │   │   └── ...
│   │   ├── markov.py        # Markov funnel model
│   │   ├── funnel.py        # FunnelExecutionEngine
│   │   ├── sampling.py      # AgentProfileGenerator
│   │   ├── profiles.py      # AgentProfile dataclass
│   │   ├── conductor.py     # Orchestrator (main entry)
│   │   ├── aggregation.py   # Results aggregation
│   │   ├── accountability.py # Failure identification
│   │   ├── calibration.py   # Learning system
│   │   ├── blindspot_detector.py
│   │   └── ...
│   │
│   ├── models/              # SQLAlchemy ORM
│   │   ├── base.py          # Base class
│   │   ├── user.py
│   │   ├── project.py
│   │   ├── simulation.py
│   │   ├── assumption.py
│   │   ├── environment.py
│   │   ├── decision.py
│   │   ├── outcome.py
│   │   ├── outcome_tracker.py
│   │   ├── cluster_run_summary.py
│   │   ├── generated_ui.py
│   │   └── ...
│   │
│   ├── schemas/             # Pydantic models
│   │   ├── projects.py
│   │   ├── simulations.py
│   │   └── ...
│   │
│   ├── tasks/               # Celery tasks
│   │   ├── simulation_tasks.py
│   │   ├── ui_simulation_tasks.py
│   │   ├── calibration_tasks.py
│   │   └── ...
│   │
│   ├── hardware/            # Hardware-specific logic
│   │   ├── model_generator.py
│   │   ├── materials.py
│   │   ├── physics_engine.py
│   │   ├── manufacturing_cost.py
│   │   └── ...
│   │
│   └── utils/               # Utility functions
│
├── tests/                   # Pytest test suite
│   ├── conftest.py          # Test fixtures
│   ├── test_security_config.py
│   ├── test_phase6_integration.py
│   └── ...
│
├── migrate_and_start.py     # DB migrations + server startup
├── requirements.txt         # Python dependencies
├── start_worker.sh          # Celery worker startup
└── CLAUDE.md                # This file
```

---

## 11. Environment Variables

**Required** (see `.env.example` for full list):
```
DATABASE_URL=postgresql://...
GROK_API_KEY=...
GROK_BASE_URL=https://api.x.ai/v1
GROK_MODEL=grok-3-mini
GROK_FAST_MODEL=grok-3-mini
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
FRONTEND_URL=http://localhost:3000
SECRET_KEY=<32+ random chars>
```

**Optional**:
```
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
SENTRY_DSN=...
ADMIN_EMAILS=...
```

---

## 12. Quick Reference: Key Data Flows

### Simulation Execution Flow
```
Project Created
    ↓
Claude Extracts Assumptions (Sonnet 4.5)
    ↓
Environment + Project → Product Type Detection
    ↓
AgentProfileGenerator → 10,000 Agents (weighted by cluster)
    ↓
Conductor.run():
  For each cluster:
    For each architect in stack:
      output = architect.compute(cluster, agent_profile, assumptions, env)
      if architect has override: apply to Markov matrix
  Markov Funnel → conversion prediction
    ↓
Results Aggregator → JSONB stored in simulations.results_json
```

### Assumption → Transition Adjustment
```
Assumption Text: "users will pay ₹999 without a trial"
    ↓
Keywords detected: ["pric", "cost", "fee", "₹", "afford"]
    ↓
Markov adjustment: DECIDE → PURCHASE probability reduced by 0.108 (CRITICAL weight × impact)
    ↓
Lower conversion predicted for clusters sensitive to pricing
```

### Learning System Flow
```
Founder submits actual conversion rate
    ↓
BlindspotDetector.scan() compares prediction vs actual
    ↓
Architects with critical warnings but low actual impact → correction scalar stored
    ↓
architect_corrections table updated
    ↓
Future simulations apply _apply_correction() to metrics
```

---

## 13. Testing Strategy

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_phase6_integration.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing

# Quick import check
python -c "from app.main import app; print('imports OK')"
```

---

## 14. Performance Guidelines

- **Conductor parallelization**: `CONDUCTOR_WORKERS` setting (default: 4)
- **Funnel parallelization**: ProcessPoolExecutor with `max(1, cpu_count() - 1)` workers
- **Database**: Connection pooling (pool_size=10, max_overflow=20)
- **Statement timeout**: 30 seconds (`DB_STATEMENT_TIMEOUT_MS`)
- **Cluster sync**: Bulk UPDATE in `sync_to_db()` — one round-trip for 416 rows

---

## 15. Debugging Tips

### Common Debug Commands
```bash
# Check cluster sync
python -c "
from app.simulation.clusters.registry import ClusterRegistry
r = ClusterRegistry()
print(f'Clusters: {len(r.all_clusters())}')
print(f'Weight sum: {sum(c.population_weight for c in r.all_clusters()):.4f}')
"

# View simulation results
python -c "
from app.core.database import SessionLocal
from app.models.simulation import Simulation
db = SessionLocal()
sim = db.query(Simulation).order_by(Simulation.created_at.desc()).first()
import json
print(json.dumps(sim.results_json, indent=2))
"
```

### Logging Categories
- `[Funnel]` — FunnelExecutionEngine progress
- `app.simulation.conductor` — Conductor.run() orchestration
- `app.simulation.architects.*` — Individual architect outputs
- `thecee.claude` — Claude API calls

---

## 16. Decision Log (Architecture Decisions)

| Decision | Reason | Status |
|----------|--------|--------|
| Celery + Redis for async work | Simulation takes 5-60s; request timeout would kill it | ✅ |
| SQLAlchemy ORM + raw text() for complex queries | ORM for CRUD, raw SQL for calibration aggregations | ✅ |
| pgvector extension | Reserved for future embedding-based cluster matching | ✅ |
| migrate_and_start.py over Alembic | Simpler for Railway deploy; all migrations are additive | ✅ |
| allow_credentials=False on CORS | JWT in Authorization header, not cookies | ✅ |
| OutcomeTracker.back_populates="outcome_trackers" | Fixed; must stay consistent with Project.outcome_trackers | ✅ |

---

## 17. Getting Help

- **Architecture questions**: Read this file first, then `AGENTS.md`
- **Simulation logic**: `conductor.py`, `markov.py`, `clusters/registry.py`
- **API questions**: `app/api/v1/projects.py`, `app/api/v1/simulations.py`
- **Database schema**: `migrate_and_start.py`
- **Model configuration**: `app/core/claude_client.py`, `app/core/config.py`

---

> **Remember**: TheCee is a **simulation engine**, not a production app. Test before deploy. Validate predictions against real founder outcomes. Update corrections in the learning system when predictions fail.
