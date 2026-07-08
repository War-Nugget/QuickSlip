"""Metadata store: maps codes -> file metadata with TTL.

Uses Redis when available (production / realistic prototype).
Falls back to a simple in-memory dict with manual expiry checks so the
app still runs with zero infrastructure for quick local hacking.
"""
import json
import time
from typing import Optional

from . import config

try:
    import redis.asyncio as aioredis
except ImportError:  # redis lib not installed
    aioredis = None


class MemoryStore:
    """Dead-simple fallback store. Not for production (single process only)."""

    def __init__(self):
        self._data: dict[str, tuple[float, str]] = {}  # key -> (expires_at, json)

    async def set(self, key: str, value: dict, ttl: int) -> None:
        self._data[key] = (time.time() + ttl, json.dumps(value))

    async def get(self, key: str) -> Optional[dict]:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, raw = entry
        if time.time() > expires_at:
            del self._data[key]
            return None
        return json.loads(raw)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr_with_ttl(self, key: str, ttl: int) -> int:
        """Increment a counter, setting TTL on first increment (for rate limiting)."""
        entry = self._data.get(key)
        now = time.time()
        if entry is None or now > entry[0]:
            self._data[key] = (now + ttl, "1")
            return 1
        expires_at, raw = entry
        count = int(raw) + 1
        self._data[key] = (expires_at, str(count))
        return count

    async def ttl(self, key: str) -> int:
        entry = self._data.get(key)
        if entry is None:
            return -2
        remaining = int(entry[0] - time.time())
        return remaining if remaining > 0 else -2

    async def ping(self) -> bool:
        return True


class RedisStore:
    """Redis-backed store. TTL/expiration handled natively by Redis."""

    def __init__(self, url: str):
        self._redis = aioredis.from_url(url, decode_responses=True)

    async def set(self, key: str, value: dict, ttl: int) -> None:
        await self._redis.set(key, json.dumps(value), ex=ttl)

    async def get(self, key: str) -> Optional[dict]:
        raw = await self._redis.get(key)
        return json.loads(raw) if raw else None

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def incr_with_ttl(self, key: str, ttl: int) -> int:
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, ttl)
        return count

    async def ttl(self, key: str) -> int:
        return await self._redis.ttl(key)

    async def ping(self) -> bool:
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False


async def create_store():
    """Try Redis first; fall back to in-memory if unavailable."""
    if aioredis is not None:
        store = RedisStore(config.REDIS_URL)
        if await store.ping():
            return store, "redis"
    return MemoryStore(), "memory"
