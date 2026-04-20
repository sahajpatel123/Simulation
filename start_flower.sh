#!/usr/bin/env bash
set -euo pipefail

echo "━━━ Starting TheCee Flower Dashboard ━━━"
cd "$(dirname "$0")"

exec celery -A app.worker:celery_app flower \
    --port=5555 \
    --broker_api=redis://localhost:6379/0
