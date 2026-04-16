# TheCee — Claude-specific context

Read `AGENTS.md` first for the full coding guide.

---

## Quick orientation

This is a **Python FastAPI + Celery** simulation engine. The `src/` directory
contains a Next.js frontend but it is deployed separately — focus on Python
unless the task explicitly says otherwise.

**The three most important files to read before making any change:**
1. `app/main.py` — FastAPI app setup, CORS, lifespan
2. `app/simulation/conductor.py` — how architects orchestrate the simulation
3. `migrate_and_start.py` — all DB schema migrations (add new columns here)

---

## Common tasks

### Running a quick sanity check
```bash
python -c "from app.main import app; print('imports OK')"
pytest tests/ -x -q
```

### Checking what's unpushed
```bash
git log origin/main..HEAD --oneline
```

### Seeing the full DB schema
```bash
python -c "
from app.core.database import engine
from sqlalchemy import inspect
for t in inspect(engine).get_table_names():
    print(t)
"
```

---

## Things Claude frequently gets wrong here

1. **Importing inside function bodies** — always put imports at module top.

2. **Adding `ALTER TABLE` in route handlers** — add to `migrate_and_start.py`
   instead; it runs on every deploy and is idempotent.

3. **Touching `" 2.*"` files** — ignore them entirely; they are iCloud
   duplicate artefacts already covered by `.gitignore`.

4. **Assuming the WebSocket broadcasts reach Celery workers** — they don't.
   `sync_broadcast` is a no-op when called from a separate process. The
   frontend must poll `/simulations/{id}/progress` for reliable status.

5. **Using `model.dict()`** — use `model.model_dump()` (Pydantic v2).

6. **Using `Session` without `Depends(get_db)`** — always use the dependency
   in API routes; use `SimulationTask.db` in Celery tasks.

7. **Hardcoding cluster IDs** — use `ClusterRegistry().all_clusters()` or
   check `_CLUSTER_IDS` in `migrate_and_start.py`.

---

## Architecture decisions already made (don't relitigate)

| Decision | Reason |
|----------|--------|
| Celery + Redis for async work | Simulation takes 5–60 s; request timeout would kill it |
| SQLAlchemy ORM + raw `text()` for complex queries | ORM for CRUD, raw SQL for calibration aggregations |
| pgvector extension | Reserved for future embedding-based cluster matching |
| `migrate_and_start.py` over Alembic | Simpler for Railway deploy; all migrations are additive |
| `allow_credentials=False` on CORS | JWT in Authorization header, not cookies |
| `OutcomeTracker.back_populates="outcome_trackers"` | Fixed; must stay consistent with `Project.outcome_trackers` |

---

## Claude API usage in this codebase

Claude is called synchronously in route handlers (not via Celery) for:
- Assumption extraction (`claude-sonnet-4-5`)
- Prototype generation (`claude-haiku-4-5-20251001`)
- Pre-mortem analysis (`claude-haiku-4-5-20251001`)
- Intervention generation (`claude-haiku-4-5-20251001`)
- Competitive analysis (`claude-haiku-4-5-20251001`)

All Claude calls are in `app/api/v1/projects.py`. The `claude` client is
instantiated once at module level.

Response parsing always:
1. Strips markdown fences if present
2. Uses `re.search(r"\{.*\}", raw, re.DOTALL)` as a fallback
3. Raises `HTTPException(500)` on malformed JSON, never crashes silently
