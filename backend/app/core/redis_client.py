from __future__ import annotations

import logging

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_redis_client() -> redis.Redis | None:
    if not settings.REDIS_URL:
        return None
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
        )
        return client
    except Exception as exc:
        logger.warning("Redis client initialization failed: %s", exc)
        return None
