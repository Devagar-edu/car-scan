"""
cache.py - File-based cache to avoid re-scraping within TTL window.
TTL default: 45 minutes.
"""

import os
import json
import logging
import pickle
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/.cache")
DEFAULT_TTL_MINUTES = 45


def _ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(key: str) -> Path:
    safe_key = key.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe_key}.pkl"


def _meta_path(key: str) -> Path:
    safe_key = key.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe_key}.meta.json"


def cache_set(key: str, value: Any, ttl_minutes: int = DEFAULT_TTL_MINUTES) -> None:
    """Store a value in the cache with expiry."""
    _ensure_cache_dir()
    try:
        with open(_cache_path(key), "wb") as f:
            pickle.dump(value, f)
        meta = {
            "key": key,
            "cached_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()
        }
        with open(_meta_path(key), "w") as f:
            json.dump(meta, f)
        logger.debug(f"Cache SET: {key} (TTL={ttl_minutes}m)")
    except Exception as e:
        logger.error(f"Cache write error for {key}: {e}")


def cache_get(key: str) -> Optional[Any]:
    """Retrieve a value from cache if not expired. Returns None if missing/expired."""
    cp = _cache_path(key)
    mp = _meta_path(key)
    if not cp.exists() or not mp.exists():
        return None
    try:
        with open(mp) as f:
            meta = json.load(f)
        expires_at = datetime.fromisoformat(meta["expires_at"])
        if datetime.now() > expires_at:
            logger.info(f"Cache EXPIRED: {key}")
            return None
        with open(cp, "rb") as f:
            value = pickle.load(f)
        logger.info(f"Cache HIT: {key}")
        return value
    except Exception as e:
        logger.error(f"Cache read error for {key}: {e}")
        return None


def cache_invalidate(key: str) -> None:
    """Delete a cached entry."""
    for path in [_cache_path(key), _meta_path(key)]:
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.error(f"Cache invalidation error for {key}: {e}")
    logger.info(f"Cache INVALIDATED: {key}")


def cache_clear_all() -> None:
    """Clear all cached entries."""
    _ensure_cache_dir()
    for f in CACHE_DIR.glob("*.pkl"):
        f.unlink(missing_ok=True)
    for f in CACHE_DIR.glob("*.meta.json"):
        f.unlink(missing_ok=True)
    logger.info("Cache cleared.")


def cache_info() -> dict:
    """Return info about current cache state."""
    _ensure_cache_dir()
    entries = []
    for mp in CACHE_DIR.glob("*.meta.json"):
        try:
            with open(mp) as f:
                meta = json.load(f)
            expires = datetime.fromisoformat(meta["expires_at"])
            entries.append({
                "key": meta["key"],
                "expires_at": meta["expires_at"],
                "expired": datetime.now() > expires
            })
        except Exception:
            pass
    return {"entries": entries, "count": len(entries)}
