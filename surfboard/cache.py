"""In-memory page cache with TTL."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    data: Any
    ttl: float
    created: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return time.time() - self.created > self.ttl


class PageCache:
    """Thread-safe LRU-ish cache for page data with TTL expiry."""

    def __init__(self, max_size: int = 20, default_ttl: float = 300.0):
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._cache: dict[str, CacheEntry] = {}
        self._access_order: list[str] = []
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.expired:
                del self._cache[key]
                self._access_order.remove(key)
                return None
            # Move to front (most recently used)
            self._access_order.remove(key)
            self._access_order.append(key)
            return entry.data

    def set(self, key: str, data: Any, ttl: float | None = None) -> None:
        with self._lock:
            ttl = ttl if ttl is not None else self._default_ttl
            if key in self._cache:
                self._access_order.remove(key)
            elif len(self._cache) >= self._max_size:
                # Evict least recently used
                oldest = self._access_order.pop(0)
                del self._cache[oldest]
            self._cache[key] = CacheEntry(data=data, ttl=ttl)
            self._access_order.append(key)

    def invalidate(self, key: str) -> None:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._access_order.remove(key)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._access_order.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)
