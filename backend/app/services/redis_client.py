import logging
from contextlib import contextmanager
from functools import lru_cache

import redis

from app.config import settings

log = logging.getLogger(__name__)


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5)


@contextmanager
def single_flight(name: str, timeout: int = 600):
    """Yield True if this process acquired the lock, False if another holder runs it.

    Prevents overlapping runs of the same periodic job (e.g. the send queue)."""
    try:
        lock = get_redis().lock(f"lock:{name}", timeout=timeout, blocking=False)
        acquired = lock.acquire()
    except redis.RedisError as exc:
        log.warning("Redis unavailable for lock %s: %s", name, exc)
        yield True
        return
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except redis.RedisError:
                pass
