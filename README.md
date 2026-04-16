# TheCee — Decision Simulation Engine

Agent-based startup simulation platform that stress-tests business ideas
against 52 consumer clusters before founders commit real resources.

---

## What it does

| Feature | Description |
|---|---|
| **Assumption extraction** | Claude surfaces hidden assumptions from a product description |
| **Signal quality scoring** | Rates how well-validated each assumption is |
| **Agent simulation** | 10 000+ consumer agents run a Markov funnel across 52 behavioural clusters |
| **Domain findings** | 17 architect modules score pricing, onboarding, trust, virality, and more |
| **Pre-mortem analysis** | AI identifies the top failure modes before launch |
| **Stress testing** | Individually flips each CRITICAL/HIGH assumption to find kill shots |
| **Interventions** | Ranked, executable growth moves tied to specific findings |
| **Competitive analysis** | Maps the competitive landscape and gap analysis |
| **Outcome calibration** | Founders feed back real conversion rates; model improves over time |
| **PDF reports** | Downloadable simulation summary |

---

## Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI + SQLAlchemy (async-ready) |
| Task queue | Celery + Redis |
| Database | PostgreSQL + pgvector |
| AI | Anthropic Claude (sonnet-4-5 / haiku-4-5) |
| Frontend | Next.js 16 (Vercel) |
| Deploy | Railway (API + worker), Supabase (DB), Upstash Redis |

---

## Repository layout

```
thecee-backend/
├── app/
│   ├── api/v1/          # FastAPI routers (auth, projects, simulations, …)
│   ├── core/            # Config, DB engine, security, WebSocket manager
│   ├── models/          # SQLAlchemy ORM models
│   ├── schemas/         # Pydantic request/response schemas
│   ├── simulation/      # Conductor, Markov engine, 52 clusters, 17 architects
│   ├── tasks/           # Celery task definitions
│   ├── reports/         # PDF report generator
│   └── worker.py        # Celery app instance
├── src/                 # Next.js frontend (deployed separately on Vercel)
├── tests/               # Integration & e2e test suite
├── migrate_and_start.py # Runs migrations then starts uvicorn (Railway start command)
├── start_worker.sh      # Celery worker start script (thecee-worker Railway service)
├── Dockerfile           # Python 3.11-slim image for Railway
└── requirements.txt     # Python dependencies
```

---

## Local setup

### Prerequisites

- Python 3.11+
- PostgreSQL 16 with the `pgvector` extension
- Redis 7+
- An Anthropic API key

### 1. Clone and create virtual environment

```bash
git clone https://github.com/sahajpatel123/Simulation.git
cd Simulation
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in DATABASE_URL, ANTHROPIC_API_KEY, SECRET_KEY, etc.
```

### 3. Start PostgreSQL and Redis

```bash
# macOS (Homebrew)
brew services start postgresql@16
brew services start redis
```

Make sure pgvector is installed:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 4. Run migrations and start the API

```bash
python migrate_and_start.py
# API available at http://localhost:8000
# Docs at        http://localhost:8000/docs
```

### 5. Start the Celery worker (separate terminal)

```bash
./start_worker.sh
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string |
| `SECRET_KEY` | ✅ | — | JWT signing secret (min 32 chars) |
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic API key |
| `REDIS_URL` | ✅ | `redis://localhost:6379/0` | Redis connection |
| `CELERY_BROKER_URL` | ✅ | `redis://localhost:6379/0` | Celery broker |
| `CELERY_RESULT_BACKEND` | ✅ | `redis://localhost:6379/1` | Celery result store |
| `FRONTEND_URL` | ✅ | `http://localhost:3000` | Allowed CORS origin |
| `ALGORITHM` | — | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | — | `10080` (7 days) | Token lifetime |
| `VECTOR_DIMENSION` | — | `1536` | pgvector dimension |

---

## Railway deployment

Three Railway services share one project:

| Service | Start command | Notes |
|---|---|---|
| **simulation** | `python migrate_and_start.py` | API + runs migrations on every deploy |
| **thecee-worker** | `./start_worker.sh` | Celery worker, same image |
| **Redis** | *(managed)* | Railway Redis plugin |

Both `simulation` and `thecee-worker` build from this repo using the
`Dockerfile` (`builder = "DOCKERFILE"` in `railway.toml`).

Set all environment variables listed above in the Railway service settings.

---

## API overview

Base URL: `/api/v1`

```
POST   /auth/register
POST   /auth/login
POST   /auth/refresh
GET    /auth/me

GET    /projects
POST   /projects
GET    /projects/{id}
POST   /projects/{id}/extract-assumptions
POST   /projects/{id}/environments
POST   /projects/{id}/generate-prototype
POST   /projects/{id}/premortem
POST   /projects/{id}/stress-test
POST   /projects/{id}/interventions
POST   /projects/{id}/competitive-analysis
POST   /projects/{id}/outcome-feedback

POST   /simulations
GET    /simulations/{id}/status
GET    /simulations/{id}/results
GET    /simulations/{id}/progress
GET    /simulations/{id}/signal-quality

WS     /ws/simulation/{id}?token=<jwt>

GET    /health
GET    /celery/status
```

Full interactive docs: `http://localhost:8000/docs`

---

## Running tests

```bash
pytest tests/ -v
```

---

## License

MIT — see [LICENSE](LICENSE).
