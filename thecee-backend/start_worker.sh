#!/bin/bash
echo "━━━ Starting TheCee Celery Worker ━━━"

if ! command -v redis-cli &> /dev/null; then
    echo "⚠️  redis-cli not found — make sure Redis is running"
fi

celery -A app.worker.celery_app worker \
    --loglevel=info \
    --pool=solo \
    --concurrency=1 \
    --queues=celery \
    --hostname=thecee-worker@%h
