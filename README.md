<div align="center">

# 🧬 **TheCee**

### *"10,000 AI consumers. One startup idea. Zero guesswork."*

<br>

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-306998?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat&logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Celery](https://img.shields.io/badge/Celery-5.4-37814A?style=flat&logo=celery&logoColor=white)](https://docs.celeryq.dev)
[![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat&logo=redis&logoColor=white)](https://redis.io)
[![Railway](https://img.shields.io/badge/Deployed%20on-Railway-0B0D0E?style=flat&logo=railway&logoColor=white)](https://railway.app)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat)](LICENSE)

<br>

> **Before you write a line of product code — simulate 10,000 consumers across 52 psychographic clusters,**
> **evaluate 20 business domains, and know exactly why your idea will succeed or fail.**

[✨ Try the API](#-api-documentation) • [🧠 How It Works](#-how-it-works) • [⚡ Quick Start](#-quick-start) • [📊 Learn More](ARCHITECTURE.md)

<br>

---

```mermaid
flowchart LR
    F[👤 Founder Input] --> A[🤖 Assumption<br>Extraction]
    A --> S[🧮 Score<br>Assumptions]
    S --> G[👥 Generate<br>10K Agents]
    G --> C[🎯 Conductor<br>52 Clusters × 20 Architects]
    C --> M[📉 Markov<br>Funnel]
    M --> R[📊 Results<br>Aggregator]
    R --> E[⚖️ Accountability<br>Engine]
    E --> O[📋 Business<br>Recommendations]

    style F fill:#1a1a2e,stroke:#e94560,color:#fff
    style A fill:#16213e,stroke:#0f3460,color:#fff
    style S fill:#16213e,stroke:#0f3460,color:#fff
    style G fill:#16213e,stroke:#0f3460,color:#fff
    style C fill:#1a1a2e,stroke:#e94560,color:#fff
    style M fill:#16213e,stroke:#0f3460,color:#fff
    style R fill:#16213e,stroke:#0f3460,color:#fff
    style E fill:#16213e,stroke:#0f3460,color:#fff
    style O fill:#1a1a2e,stroke:#e94560,color:#fff
```

---

</div>

## 🔮 **Forget Surveys. Forget Focus Groups.**

TheCee replaces expensive user research with a **behavioral simulation engine** that pits your startup idea against **52 distinct consumer archetypes**, evaluated by **20 domain-specialist AI architects**, all flowing through a **Markov decision funnel**.

**What you get:**
- 🎯 **Predicted conversion rate** with confidence intervals
- 🔥 **Primary failure domain** — the exact reason your idea fails
- 🧠 **Per-cluster breakdown** — which segments love/hate your idea
- 💰 **Revenue projection** at any price point
- 📋 **Ranked domain findings** — actionable recommendations, not noise

---

## 🧠 **How It Works**

### 1. 🧬 The 52 Clusters

Every consumer is different. TheCee models **52 Indian consumer archetypes** — from *metro power professionals* to *tier-3 first-time app users* — each with **8 calibrated personality traits**:

```
income_level │ digital_literacy │ motivation │ trust
price_sensitivity │ risk_aversion │ patience_score │ social_orientation
```

These aren't stereotypes. They're **data-calibrated behavioral vectors** that evolve as real founder outcomes flow back into the system.

### 2. 🏛️ The 20 Architects

Domain specialists that evaluate one business dimension each:

| Architect | Evaluates |
|-----------|-----------|
| `MarketTimingArchitect` | Is the market ready? Timing right? |
| `PricingArchitect` | Will they pay? At what price? |
| `TrustArchitect` | Brand credibility signals |
| `OnboardingArchitect` | First-usage experience |
| `RetentionArchitect` | Long-term stickiness |
| `ViralityArchitect` | Word-of-mouth potential |
| `CompetitiveDynamicsArchitect` | Incumbent response & switching friction |
| `MacroeconomicArchitect` | Economic headwinds/tailwinds |
| *+ 12 more domain specialists* | Hardware, health, ecosystem, etc. |

Each architect calls `.compute()` per cluster — **1,040 evaluations per simulation** — then outputs override deltas to the Markov matrix.

### 3. 📉 The Markov Funnel

```
ARRIVE → BROWSE → CONSIDER → DECIDE → 🟢 PURCHASE
                                 ↘ → 🔴 ABANDON → RETURN ↗
```

A **7-state stochastic model** where every transition probability is modulated by:
- 📝 **Assumption keywords** (pricing, trust, retention, UX, competition)
- 🧬 **Cluster personality traits**
- 🏛️ **Architect override signals**
- 🌍 **Environmental parameters** (scenario, market maturity)

### 4. 🔄 Self-Learning Calibration

> *"The simulation gets smarter every time a founder submits real data."*

The `CalibrationEngine` compares **predicted vs actual** conversion rates from real founder outcomes, then:
- 🎚️ Updates per-architect correction scalars
- 🧬 Adjusts cluster trait calibrations via **Bayesian updates**
- 📊 Tracks user-level accuracy trends
- 🧠 Detects market blindspots automatically

---

## ⚡ **Quick Start**

### Prerequisites
```
🐍 Python 3.12+    📦 Node.js 18+    🐘 PostgreSQL    📡 Redis
```

### 🖥️ Backend

```bash
# Clone & enter
git clone https://github.com/Sahajpatel123/Simulation.git && cd thecee

# Python setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env        # 👈 Set DATABASE_URL, GROK_API_KEY, REDIS_URL

# Migrate + launch API
python migrate_and_start.py  # Creates DB tables, syncs clusters, starts uvicorn
```

### ⚙️ Celery Worker

```bash
# Terminal 2 (same venv)
./start_worker.sh
```

Check worker health: `http://localhost:8000/celery/status`

### 🌐 Frontend

```bash
# Terminal 3
npm install
cp .env.local.example .env.local
npm run dev                 # → http://localhost:3000
```

---

## 🧪 **Testing**

```bash
# Backend (51 tests, all green ✅)
source .venv/bin/activate
pytest tests/ -v

# Frontend
npm run typecheck
npm run build
```

---

## 🚀 **Deployment**

### Backend → Railway
```
1. Push to GitHub
2. New Railway project → Deploy from repo
3. Add PostgreSQL + Redis services
4. Set all env vars
5. Start command: python migrate_and_start.py
6. Add second service: celery -A app.worker worker --loglevel=info
```

### Frontend → Vercel
```
1. Import repo to Vercel
2. Set NEXT_PUBLIC_API_URL to Railway backend
3. Deploy
```

---

## 📋 **API Reference**

With backend running:
| Tool | URL |
|------|-----|
| **Swagger UI** | `http://localhost:8000/docs` |
| **ReDoc** | `http://localhost:8000/redoc` |
| **Health Check** | `http://localhost:8000/health` |
| **Celery Status** | `http://localhost:8000/celery/status` |

---

## 🧱 **Project Structure**

```
thecee/
├── backend/app/          # 🐍 Python FastAPI (the engine)
│   ├── api/v1/           #   14 route modules
│   ├── simulation/       #   Core engine: conductor, 20 architects, Markov funnel
│   ├── models/           #   17 SQLAlchemy ORM models
│   ├── schemas/          #   16 Pydantic schemas
│   ├── tasks/            #   8 Celery task modules
│   ├── core/             #   Config, DB, auth, LLM client
│   └── hardware/         #   Hardware product simulation pipeline
├── src/                  # 🎨 Next.js 16 frontend
├── tests/                # 🧪 pytest suite (51 tests)
├── AGENTS.md             # 🤖 AI coding guide
├── CLAUDE.md             # 📘 Full architecture reference
└── ARCHITECTURE.md       # 📐 Deep-dive architecture doc
```

---

## 🏛️ **Architecture Philosophy**

| Principle | Why |
|-----------|-----|
| **Pure compute** | Architects do zero I/O — pure math, deterministic |
| **Cluster-first** | 52 archetypes drive everything, not demographic averages |
| **Self-correcting** | Every founder outcome improves future simulations |
| **A/B testable** | Config-driven knobs, all default to no-op |
| **Performance-budgeted** | Full 10K simulation under 30s |

---

<div align="center">

<br>

**Built with** 🧠 **fastapi** · ⚡ **celery** · 🎯 **postgresql** · 🔮 **grok**

*"Simulate before you build. Know before you launch."*

[🐛 Report Bug](https://github.com/Sahajpatel123/Simulation/issues) · [✨ Feature Request](https://github.com/Sahajpatel123/Simulation/issues)

<br>

</div>
