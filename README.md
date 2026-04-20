<div align="center">

```
████████╗██╗  ██╗███████╗ ██████╗███████╗███████╗
╚══██╔══╝██║  ██║██╔════╝██╔════╝██╔════╝██╔════╝
   ██║   ███████║█████╗  ██║     █████╗  █████╗  
   ██║   ██╔══██║██╔══╝  ██║     ██╔══╝  ██╔══╝  
   ██║   ██║  ██║███████╗╚██████╗███████╗███████╗
   ╚═╝   ╚═╝  ╚═╝╚══════╝ ╚═════╝╚══════╝╚══════╝
```

### **Don't guess. Simulate.**

*Run 10 000 AI consumers through your idea before spending a rupee.*

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Celery](https://img.shields.io/badge/Celery-5.4-37814A?style=flat-square&logo=celery&logoColor=white)](https://docs.celeryq.dev)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-D97757?style=flat-square&logo=anthropic&logoColor=white)](https://anthropic.com)
[![Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?style=flat-square&logo=railway&logoColor=white)](https://railway.app)

</div>

---

## The Problem

Every startup founder believes their idea will work. Almost none of them test *why* it won't — before it's too late.

Traditional market research is slow, expensive, and biased toward what people say they'll do, not what they actually do.

**TheCee simulates the truth.**

---

## What happens in a simulation

```
Your idea description
        │
        ▼
┌───────────────────┐
│  Claude extracts  │  ← surfaces hidden assumptions you didn't know you were making
│  your assumptions │
└────────┬──────────┘
         │  scored by signal quality (ASPIRATIONAL → VALIDATED_EXTERNAL)
         ▼
┌───────────────────────────────────────────────────────────────────┐
│                     52 Consumer Clusters                          │
│                                                                   │
│  metro_power_professional  ·  tier2_aspirational_founder         │
│  high_income_early_adopter ·  burnt_previously_buyer             │
│  urban_working_mother      ·  gig_economy_worker        · · ·    │
└────────────────────────────┬──────────────────────────────────────┘
                             │  10 000 agents, each with 8 traits
                             ▼
┌───────────────────────────────────────────────────────────────────┐
│                   21 Architect Modules                            │
│                                                                   │
│  Pricing · Onboarding · Trust · Virality · Feature Adoption      │
│  Market Timing · Competitive Dynamics · Retention · Macroeconomic │
│  Distribution Channel · Demographic Interaction · Setup/First Use │
│  Performance Threshold · Support Friction · Physical/Sensory      │
│  Purchase Decision · Ecosystem Compatibility · Assumption Cascade │
│  Aftersales Lifecycle · Health/Safety Hardware · Macroeconomic    │
└────────────────────────────┬──────────────────────────────────────┘
                             │  Markov funnel: ARRIVE → BROWSE → CONSIDER → DECIDE → PURCHASE
                             ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Simulation Results                             │
│                                                                   │
│  • Overall conversion rate + confidence interval                  │
│  • Per-cluster breakdown (who buys, who bounces, and why)        │
│  • Domain findings ranked by conversion impact                    │
│  • Highest-value cluster + cluster narrative                      │
│  • Primary failure domain                                         │
│  • Signal quality score (how trustworthy are your assumptions?)   │
└───────────────────────────────────────────────────────────────────┘
```

---

## Feature surface

| Module | What it does |
|--------|-------------|
| 🧠 **Assumption extraction** | Claude reads your description and surfaces every assumption — especially the dangerous hidden ones |
| 📊 **Signal quality scoring** | Rates each assumption from `ASPIRATIONAL` → `VALIDATED_EXTERNAL` and assigns a 0–1 signal quality score to the entire simulation |
| 👥 **52 consumer clusters** | India-calibrated behavioural segments from `metro_power_professional` to `vernacular_content_creator`, each with 8 psychographic traits |
| 🏗️ **21 architect modules** | Domain specialists (pricing, onboarding, trust, virality…) that independently score your product against each cluster |
| 🎲 **Markov funnel engine** | Agents traverse ARRIVE → BROWSE → CONSIDER → DECIDE → PURCHASE with architect-tuned transition probabilities |
| 💀 **Pre-mortem analysis** | Claude identifies the top failure modes *before* you launch, ranked by probability and severity |
| 🔨 **Assumption stress test** | Individually flips every CRITICAL/HIGH assumption to find the kill shots |
| 🎯 **Intervention planner** | Ranked, executable growth moves tied directly to simulation findings |
| 🗺️ **Competitive analysis** | Maps your competitive landscape and surfaces gaps and counter-moves |
| 📈 **Outcome calibration** | Founders feed back real conversion rates post-launch; the model self-improves over time |
| 🖼️ **Prototype generator** | Claude produces an HTML product prototype + conversion funnel graph from your description |
| 📄 **PDF reports** | Downloadable simulation summary via ReportLab |
| 🔌 **WebSocket progress** | Real-time simulation progress pushed to the frontend as it runs |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Vercel)                     │
│                    Next.js 16 + React 19                     │
│              Zustand · TanStack Query · shadcn/ui            │
└──────────────────────┬──────────────────────────────────────┘
                       │  REST + WebSocket
                       │  NEXT_PUBLIC_API_URL
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   API (Railway: simulation)                  │
│                     FastAPI + Uvicorn                        │
│                                                             │
│   /api/v1/auth          JWT register / login / refresh      │
│   /api/v1/projects      CRUD + AI endpoints (Claude)        │
│   /api/v1/simulations   create / status / results           │
│   /ws/simulation/{id}   WebSocket progress stream           │
└──────────────┬──────────────────────────┬───────────────────┘
               │ Celery task              │ SQLAlchemy
               ▼                         ▼
┌──────────────────────┐    ┌────────────────────────────────┐
│  Worker (Railway:    │    │  PostgreSQL (Supabase)          │
│  thecee-worker)      │    │                                │
│  Celery + Redis      │    │  users · projects · assumptions │
│                      │    │  simulations · environments     │
│  run_full_simulation │    │  decisions · outcomes           │
│  run_stress_test     │    │  cluster_parameters (416 rows)  │
│  run_decision        │    │  architect_corrections          │
│  calibration tasks   │    │  founder_outcomes               │
└──────────────────────┘    │  user_claim_accuracy_profiles   │
               │             └────────────────────────────────┘
               ▼
┌──────────────────────┐
│  Redis (Railway)     │
│  Celery broker       │
│  result backend      │
└──────────────────────┘
```

---

## Quick start

### Prerequisites

- Python 3.11+
- PostgreSQL 16 with `pgvector` extension enabled
- Redis 7+
- Anthropic API key

### 1 · Clone & install

```bash
git clone https://github.com/sahajpatel123/Simulation.git
cd Simulation
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2 · Configure

```bash
cp .env.example .env
# Fill in DATABASE_URL, ANTHROPIC_API_KEY, SECRET_KEY, REDIS_URL
```

### 3 · Migrate and start the API

```bash
python migrate_and_start.py
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

### 4 · Start the worker (separate terminal)

```bash
./start_worker.sh
```

---

## Environment variables

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `DATABASE_URL` | ✅ | — | `postgresql://user:pass@host/db` |
| `SECRET_KEY` | ✅ | — | Min 32 random chars (`openssl rand -hex 32`) |
| `ANTHROPIC_API_KEY` | ✅ | — | Used by assumption extraction, pre-mortem, etc. |
| `REDIS_URL` | ✅ | `redis://localhost:6379/0` | |
| `CELERY_BROKER_URL` | ✅ | `redis://localhost:6379/0` | |
| `CELERY_RESULT_BACKEND` | ✅ | `redis://localhost:6379/1` | |
| `FRONTEND_URL` | ✅ | `http://localhost:3000` | Sets the CORS allowed origin |
| `ALGORITHM` | — | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | — | `10080` | 7 days |
| `VECTOR_DIMENSION` | — | `1536` | pgvector dimensions |

---

## Railway deployment

Three Railway services, one repo:

| Service | Build | Start command | Notes |
|---------|-------|---------------|-------|
| **simulation** | `Dockerfile` | `python migrate_and_start.py` | API + runs DB migrations on every deploy |
| **thecee-worker** | `Dockerfile` | `./start_worker.sh` | Celery worker, same image; needs `DATABASE_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` (same as API). Start must be from repo root (`WORKDIR /app` in Docker). |

**Worker not starting on Railway:** confirm the worker service **start command** is exactly `./start_worker.sh` (not the web `migrate_and_start.py`). The script invokes `celery -A app.worker:celery_app` (module `app/worker.py`, app object `celery_app`).
| **Redis** | managed | — | Railway Redis plugin |

Set all environment variables in each Railway service's settings panel. The `DATABASE_URL` and all `CELERY_*` / `REDIS_URL` vars must point at your Supabase and Railway Redis instances.

---

## API reference

Base: `/api/v1`

<details>
<summary><strong>Auth</strong></summary>

```
POST   /auth/register          create account, returns JWT pair
POST   /auth/login             returns JWT pair
POST   /auth/refresh           exchange refresh token for new access token
GET    /auth/me                current user profile
POST   /auth/logout            (stateless — client drops token)
```
</details>

<details>
<summary><strong>Projects</strong></summary>

```
GET    /projects               list all projects for current user
POST   /projects               create project
GET    /projects/{id}          get project

POST   /projects/{id}/extract-assumptions    Claude → extract + score assumptions
GET    /projects/{id}/assumptions            list scored assumptions

POST   /projects/{id}/environments           set simulation environment / scenario preset
GET    /projects/{id}/environments           get current environment
GET    /projects/{id}/environments/presets   list available scenario presets

POST   /projects/{id}/generate-prototype     Claude → HTML prototype + funnel graph
GET    /projects/{id}/prototype

POST   /projects/{id}/premortem              Claude → failure mode analysis
GET    /projects/{id}/premortem

POST   /projects/{id}/stress-test            Celery → flip each critical assumption
GET    /projects/{id}/stress-test
DELETE /projects/{id}/stress-test

POST   /projects/{id}/interventions          Claude → ranked growth interventions
GET    /projects/{id}/interventions

POST   /projects/{id}/competitive-analysis   Claude → competitor landscape
GET    /projects/{id}/competitive-analysis

POST   /projects/{id}/outcome-feedback       submit real-world conversion rate (calibration)
GET    /projects/{id}/clusters               cluster breakdown from latest simulation
GET    /projects/{id}/domain-findings        domain findings from latest simulation
```
</details>

<details>
<summary><strong>Simulations</strong></summary>

```
POST   /simulations                          enqueue simulation (Celery task)
GET    /simulations/clusters                 list all 52 cluster definitions
GET    /simulations/worker/health            ping Celery worker
GET    /simulations/ws/info                  active WebSocket connection count

GET    /simulations/{id}/status              QUEUED | RUNNING | COMPLETED | FAILED
GET    /simulations/{id}/results             full results (clusters, findings, narrative…)
GET    /simulations/{id}/progress            pct complete + elapsed time
GET    /simulations/{id}/signal-quality      signal quality breakdown

GET    /simulations/project/{project_id}     list all simulations for a project
```
</details>

<details>
<summary><strong>WebSocket</strong></summary>

```
WS     /ws/simulation/{id}?token=<jwt>       real-time progress stream
```

Messages:
```jsonc
// progress update (sent by worker via sync_broadcast)
{ "type": "progress", "status": "RUNNING", "stage": "Running cluster simulation",
  "pct": 45, "agents_processed": 4500, "agents_total": 10000, "ts": "…" }

// completion
{ "type": "progress", "status": "COMPLETED", "pct": 100, "conversion_rate": 0.034 }

// keepalive
send: "ping"   →   receive: {"type":"pong"}
```
</details>

<details>
<summary><strong>Decisions / Outcomes / Reports</strong></summary>

```
GET    /decisions
POST   /decisions
GET    /decisions/{id}

GET    /outcomes
POST   /outcomes
GET    /outcomes/{id}

GET    /reports/{simulation_id}    download PDF report
```
</details>

<details>
<summary><strong>Utility</strong></summary>

```
GET    /health         {"status": "healthy"}
GET    /celery/status  worker count + broker URL
GET    /docs           Swagger UI
GET    /redoc          ReDoc UI
```
</details>

---

## The 52 consumer clusters

TheCee segments the Indian consumer market into 52 behavioural archetypes calibrated across 8 psychographic traits:

> `income_level` · `digital_literacy` · `motivation` · `trust` · `price_sensitivity` · `risk_aversion` · `patience_score` · `social_orientation`

<details>
<summary>Show all 52 clusters</summary>

**Enterprise & Professional**
`metro_power_professional` · `senior_enterprise_decision_maker` · `high_income_early_adopter` · `affluent_metro_late_majority` · `high_income_hardware_enthusiast` · `wealthy_health_conscious_buyer`

**Urban Mid-Income**
`urban_mid_income_saas_buyer` · `urban_mid_income_hardware_considerer` · `young_urban_professional_first_job` · `urban_couple_joint_purchaser` · `mid_income_startup_founder` · `urban_working_mother`

**Students**
`high_literacy_student_freemium_ceiling` · `low_literacy_student_passive` · `student_high_intent_specific_need` · `college_group_purchase` · `recent_graduate_job_seeker`

**Tier-2 / Tier-3 Cities**
`tier2_aspirational_founder` · `tier2_established_business_owner` · `tier3_first_time_app_user` · `tier2_price_sensitive_pragmatist` · `tier3_community_influenced_buyer` · `tier2_educated_young_parent`

**SMB & B2B**
`smb_owner_self_serve` · `smb_owner_referral_dependent` · `mid_market_it_decision_maker` · `enterprise_procurement_gatekeeper` · `technical_founder_evaluator` · `non_technical_co_founder_buyer`

**Hardware**
`early_hardware_adopter_tech_enthusiast` · `considered_hardware_researcher` · `value_hardware_buyer` · `gift_hardware_buyer` · `replacement_hardware_buyer` · `health_hardware_skeptic` · `health_hardware_enthusiast` · `smart_home_early_adopter`

**Psychographic**
`anxiety_driven_researcher` · `impulsive_trend_follower` · `loyalist_returning_buyer` · `price_anchor_manipulated_buyer` · `peer_pressure_converter` · `deliberate_minimalist` · `productivity_maximiser` · `budget_constrained_high_intent` · `passive_enterprise_user` · `burnt_previously_buyer`

**Emerging**
`retiree_digital_explorer` · `gig_economy_worker` · `ngo_nonprofit_buyer` · `diaspora_remittance_buyer` · `vernacular_content_creator`

</details>

---

## The 21 architect modules

Each architect is a domain specialist that independently scores your product for every cluster. Their outputs are combined by the `Conductor` to produce conversion-rate deltas per cluster.

| Architect | Domain scored |
|-----------|--------------|
| `PricingArchitect` | Price point fit, anchor effects, willingness to pay |
| `OnboardingArchitect` | Activation friction, time-to-value, setup complexity |
| `TrustArchitect` | Brand credibility, social proof, risk signals |
| `ViralityArchitect` | Word-of-mouth coefficient, referral loops |
| `FeatureAdoptionArchitect` | Feature discovery, complexity vs. benefit ratio |
| `MarketTimingArchitect` | Category readiness, trend alignment |
| `CompetitiveDynamicsArchitect` | Switching costs, incumbent strength |
| `RetentionArchitect` | Churn drivers, habit formation |
| `MacroeconomicArchitect` | Economic climate impact on discretionary spend |
| `DistributionChannelArchitect` | Channel fit, reach efficiency |
| `DemographicInteractionArchitect` | Cross-demographic effects and spillover |
| `SetupFirstUseArchitect` | First-run experience, Day-0 drop rate |
| `PerformanceThresholdArchitect` | Minimum viable performance expectations |
| `SupportFrictionArchitect` | Support-seeking behaviour, resolution rate |
| `PhysicalSensoryArchitect` | Tangibility, sensory evaluation for physical products |
| `PurchaseDecisionArchitect` | Decision-making complexity, cognitive load |
| `EcosystemCompatibilityArchitect` | Platform lock-in, integration dependencies |
| `AssumptionCascadeArchitect` | Cross-assumption dependency failures |
| `AftersalesLifecycleArchitect` | Post-purchase satisfaction, LTV drivers |
| `HealthSafetyHardwareArchitect` | Regulatory and safety perception (hardware/health) |
| `DemographicInteractionArchitect` | Demographic spillover and network effects |

---

## How the model self-improves

```
Founder submits real conversion rate after launch
              │
              ▼
  CalibrationEngine.validate_outcome()
  weights the data point by:
    • signal quality at run time
    • days since launch
    • product/pricing stability
    • data confidence level
              │
              ▼
  architect_corrections table updated
  (correction_scalar per architect × cluster × product_type)
              │
              ▼
  Future simulations pick up corrections
  automatically via BaseArchitect._apply_correction()
```

Weekly and monthly Celery beat tasks (`run_systematic_bias_update`, `run_structural_pattern_update`) apply batch corrections across all cluster parameters.

---

## Running tests

```bash
pytest tests/ -v
```

Test files:
- `tests/test_phase6_integration.py` — integration tests for the full simulation pipeline
- `tests/test_phase6_e2e.py` — end-to-end API tests

---

## Repository layout

```
app/
├── api/v1/
│   ├── auth.py           register · login · refresh · me
│   ├── projects.py       CRUD + Claude AI endpoints (1 500 lines)
│   ├── simulations.py    simulation lifecycle
│   ├── decisions.py      decision tracking
│   ├── outcomes.py       outcome logging
│   ├── reports.py        PDF generation
│   ├── calibration.py    calibration query endpoints
│   ├── users.py          user profile
│   └── websocket.py      WS progress endpoint
├── core/
│   ├── config.py         pydantic-settings (reads .env)
│   ├── database.py       SQLAlchemy engine + session
│   ├── deps.py           FastAPI dependency injection
│   ├── security.py       JWT create/decode, bcrypt
│   ├── websocket.py      ConnectionManager + sync_broadcast bridge
│   └── prompts.py        all Claude prompt templates
├── models/               SQLAlchemy ORM models (14 tables)
├── schemas/              Pydantic request/response schemas
├── simulation/
│   ├── conductor.py      orchestrates architects across all clusters
│   ├── clusters/         52 ClusterDefinition objects + registry
│   ├── architects/       21 BaseArchitect subclasses
│   ├── markov.py         Markov state machine (ARRIVE→PURCHASE)
│   ├── profiles.py       AgentProfileGenerator (samples traits from clusters)
│   ├── aggregation.py    ResultsAggregator (final metrics)
│   ├── accountability.py AccountabilityEngine (ranked DomainFindings)
│   ├── scored_assumption.py   signal quality scoring
│   └── calibration_engine.py  outcome learning system
├── tasks/
│   ├── simulation_tasks.py    run_full_simulation Celery task
│   ├── stress_test_tasks.py   run_assumption_stress_test
│   ├── decision_tasks.py      decision analysis task
│   └── calibration_tasks.py   periodic bias-correction tasks
├── reports/generator.py       ReportLab PDF generator
├── worker.py                  Celery app instance + periodic task schedule
└── main.py                    FastAPI app, CORS, lifespan

migrate_and_start.py           runs all migrations then starts uvicorn
start_worker.sh                starts the Celery worker
Dockerfile                     python:3.11-slim image
railway.toml                   Railway build config (DOCKERFILE builder)
```

---

## License

[MIT](LICENSE) © TheCee
