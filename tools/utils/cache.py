"""
tools.utils.cache — Simple TTL-based function result caching

Uses diskcache for persistence across runs, with fallback to in-memory dict.

Usage:
    from tools.utils.cache import cached, clear_cache

    @cached(ttl=300)  # cache for 5 minutes
    def my_function(ticker):
        ...  # expensive call
        return result

    clear_cache()  # wipe all cached results
"""

from __future__ import annotations

import functools
import hashlib
import json
import time
from typing import Any, Callable, Optional

# Try diskcache for persistent cache, fall back to in-memory
_CACHE_DIR = "/tmp/brickellquant_cache"
_MEMORY_CACHE: dict[str, tuple[Any, float]] = {}  # key → (value, expiry_timestamp)

try:
    import diskcache
    _disk_cache = diskcache.Cache(_CACHE_DIR)
    _USE_DISK = True
except ImportError:
    _disk_cache = None
    _USE_DISK = False


def get_cache() -> dict:
    """
    Get cache info.

    Returns:
        Dict with: backend, size, cache_dir (if disk)

    Example:
        info = get_cache()
        print(info)
    """
    if _USE_DISK and _disk_cache is not None:
        return {
            "backend": "diskcache",
            "cache_dir": _CACHE_DIR,
            "size": len(_disk_cache),
        }
    return {
        "backend": "in-memory",
        "size": len(_MEMORY_CACHE),
    }


def clear_cache() -> int:
    """
    Clear all cached results.

    Returns:
        Number of entries cleared

    Example:
        cleared = clear_cache()
        print(f"Cleared {cleared} cached entries")
    """
    global _MEMORY_CACHE

    count = 0
    if _USE_DISK and _disk_cache is not None:
        count = len(_disk_cache)
        _disk_cache.clear()
    else:
        count = len(_MEMORY_CACHE)
        _MEMORY_CACHE = {}

    return count


def _make_cache_key(func: Callable, args: tuple, kwargs: dict) -> str:
    """Generate a stable cache key from function name + arguments."""
    key_data = {
        "func": f"{func.__module__}.{func.__qualname__}",
        "args": str(args),
        "kwargs": str(sorted(kwargs.items())),
    }
    raw = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def cached(ttl: int = 300):
    """
    Decorator to cache function results for a specified TTL.

    Args:
        ttl: Cache lifetime in seconds. Default: 300 (5 minutes)
             Use ttl=0 to disable caching.

    Usage:
        @cached(ttl=60)
        def get_price(ticker):
            return expensive_api_call(ticker)

        @cached(ttl=3600)  # 1 hour
        def get_annual_report(ticker):
            ...

    Common TTL values:
        60     = 1 minute  (prices)
        300    = 5 minutes (news, quotes)
        600    = 10 minutes (financial data)
        1800   = 30 minutes (SEC filings)
        3600   = 1 hour (historical, ownership)
        86400  = 24 hours (rarely changing data)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if ttl == 0:
                return func(*args, **kwargs)

            cache_key = _make_cache_key(func, args, kwargs)
            now = time.time()

            # ── Check cache ────────────────────────────────────────────
            if _USE_DISK and _disk_cache is not None:
                try:
                    cached_val = _disk_cache.get(cache_key)
                    if cached_val is not None:
                        value, expiry = cached_val
                        if now < expiry:
                            return value
                except Exception:
                    pass
            else:
                if cache_key in _MEMORY_CACHE:
                    value, expiry = _MEMORY_CACHE[cache_key]
                    if now < expiry:
                        return value

            # ── Execute function ───────────────────────────────────────
            result = func(*args, **kwargs)
            expiry = now + ttl

            # ── Store result ───────────────────────────────────────────
            if _USE_DISK and _disk_cache is not None:
                try:
                    _disk_cache.set(cache_key, (result, expiry), expire=ttl)
                except Exception:
                    _MEMORY_CACHE[cache_key] = (result, expiry)
            else:
                _MEMORY_CACHE[cache_key] = (result, expiry)

            return result

        # Attach cache control methods
        wrapper.cache_clear = lambda: clear_cache()  # type: ignore
        wrapper.cache_ttl = ttl  # type: ignore
        return wrapper

    return decorator
