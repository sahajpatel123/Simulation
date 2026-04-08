#!/bin/bash
echo "━━━ Starting TheCee Flower Dashboard ━━━"
celery -A app.worker.celery_app flower \
    --port=5555 \
    --broker_api=redis://localhost:6379/0
