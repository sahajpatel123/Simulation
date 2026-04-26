# TheCee

Pre-launch behavioral simulation platform.
Runs 52-cluster agent simulation to predict real-world
conversion before founders launch.

## Architecture Overview

Frontend (Next.js 15) → Backend (FastAPI) → Celery Workers
                                         → PostgreSQL (Supabase)
                                         → Redis (Railway)
                                         → Claude API (Anthropic)

Simulation flow:
  Founder describes product
  → Assumption extraction (Claude)
  → Conductor routes 52 clusters through 20 architects
  → CognitiveState mutations applied
  → Cluster conversion rates computed
  → KeyPersonReport generated

## Local setup (monorepo)

This repository contains the FastAPI backend under `app/` and the Next.js app at the same root (`package.json`, `src/`).

### Prerequisites
  Node.js 18+, Python 3.11+, PostgreSQL, Redis

### Backend
  From the repository root (directory that contains `app/` and `requirements.txt`):
  `python -m venv venv` && `source venv/bin/activate` (or `venv\Scripts\activate` on Windows)
  `pip install -r requirements.txt`
  `cp .env.example .env`     # fill in values
  `python migrate_and_start.py`

### Celery Worker
  From the same repository root with the virtualenv active:
  `celery -A app.worker worker --loglevel=info`

### Frontend
  From the same repository root:
  `npm install`
  `cp .env.local.example .env.local`    # fill in values, if the example exists
  `npm run dev`

## Environment Variables

### Backend (.env)
  `DATABASE_URL=postgresql://...`
  `ANTHROPIC_API_KEY=sk-ant-...`
  `RAZORPAY_KEY_ID=rzp_test_...`
  `RAZORPAY_KEY_SECRET=...`
  `RAZORPAY_WEBHOOK_SECRET=...`
  `RAZORPAY_PRO_PLAN_ID=plan_...`
  `RAZORPAY_ENTERPRISE_PLAN_ID=plan_...`
  `REDIS_URL=redis://...`
  `SECRET_KEY=...`
  `PUBLIC_API_BASE_URL=https://your-api-domain`
  `ENVIRONMENT=development`
  `SENTRY_DSN=`           # optional
  `CONDUCTOR_WORKERS=4`
  `ACCESS_TOKEN_EXPIRE_MINUTES=60`
  `REFRESH_TOKEN_EXPIRE_DAYS=30`

### Frontend (.env.local)
  `NEXT_PUBLIC_API_URL=http://localhost:8080`
  `NEXT_PUBLIC_ALLOW_INDEXING=false`

## Railway + Vercel Deployment

### Backend on Railway
  1. Push to GitHub
  2. New Railway project → Deploy from GitHub
  3. Add PostgreSQL service and Redis service
  4. Set all env vars from list above
  5. Start command: `python migrate_and_start.py`
  6. Add second service for Celery worker:
     Start command: `celery -A app.worker worker --loglevel=info`

### Frontend on Vercel
  1. Import GitHub repo to Vercel
  2. Set `NEXT_PUBLIC_API_URL` to Railway backend URL
  3. Deploy (root directory: this repo, or a subdirectory if the frontend is split out)

### Razorpay Webhook
  Dashboard → Webhooks → Add:
  URL: `https://your-railway-url/api/v1/billing/webhook`
  Events: `subscription.activated`, `subscription.charged`,
          `subscription.cancelled`, `subscription.expired`,
          `subscription.halted`

## Running Tests
  From repository root, with the virtualenv active:
  `pytest tests/ -v`
  `npm run typecheck`
  `npm run build`

## API documentation

  With the backend running (default `8080` if configured): OpenAPI UI at `http://localhost:8080/docs` and ReDoc at `http://localhost:8080/redoc`.
