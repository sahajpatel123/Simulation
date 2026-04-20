#!/usr/bin/env bash
set -euo pipefail

echo "━━━ Starting TheCee Celery Worker ━━━"
cd "$(dirname "$0")"

if ! command -v redis-cli &> /dev/null; then
    echo "⚠️  redis-cli not found — make sure Redis is running"
fi

# Use module:attribute form so Celery resolves app/worker.py reliably (Railway / Docker).
exec celery -A app.worker:celery_app worker \
    --loglevel=info \
    --pool=solo \
    --concurrency=1 \
    --queues=celery \
    --hostname=thecee-worker@%h
