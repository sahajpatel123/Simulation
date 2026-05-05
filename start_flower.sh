#!/usr/bin/env bash
set -euo pipefail

echo "━━━ Starting TheCee Flower Dashboard ━━━"
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/backend${PYTHONPATH:+:${PYTHONPATH}}"

exec celery -A app.worker:celery_app flower \
    --port=5555 \
    --broker_api=redis://localhost:6379/0
