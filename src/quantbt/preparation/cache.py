"""Bounded content-addressed prepared-object cache."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from threading import RLock


class ResetScope(str, Enum):
    ACCOUNT_ONLY = "account_only"
    ACCOUNT_AND_ORDERS = "account_and_orders"
    SCENARIO_STATE = "scenario_state"
    RESULT_BUFFERS = "result_buffers"
    FULL_REBUILD = "full_rebuild"


@dataclass(frozen=True, slots=True)
class CachePolicy:
    max_bytes: int = 256 * 1024 * 1024
    max_entries: int = 8
    eviction: str = "lru"
    pin_during_run: bool = True
    weak_result_owners: bool = True

    def __post_init__(self) -> None:
        if self.max_bytes < 0 or self.max_entries < 0:
            raise ValueError("cache budgets must be >= 0")
        if self.eviction != "lru":
            raise ValueError("only lru cache eviction is supported")


@dataclass(slots=True)
class _Entry:
    value: object
    size_bytes: int
    pins: int = 0
    reuse_count: int = 0


class PreparedObjectCache:
    """Small LRU cache whose keys are immutable content fingerprints."""

    def __init__(self, policy: CachePolicy = CachePolicy()):
        self.policy = policy
        self._entries: OrderedDict[tuple[str, ...], _Entry] = OrderedDict()
        self._lock = RLock()
        self._resident_bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._clears = 0
        self._generation = 0

    def get(self, key: tuple[str, ...], *, pin: bool = False):
        with self._lock:
            entry = self._entries.get(tuple(key))
            if entry is None:
                self._misses += 1
                return None
            self._hits += 1
            entry.reuse_count += 1
            if pin and self.policy.pin_during_run:
                entry.pins += 1
            self._entries.move_to_end(tuple(key))
            return entry.value

    def release(self, key: tuple[str, ...]) -> None:
        """Release one explicit pin and immediately enforce cache budgets."""

        with self._lock:
            entry = self._entries.get(tuple(key))
            if entry is None:
                return
            if entry.pins <= 0:
                raise RuntimeError("prepared cache entry is not pinned")
            entry.pins -= 1
            self._evict()

    @contextmanager
    def borrow(self, key: tuple[str, ...]):
        """Pin an existing entry for a run and release it deterministically."""

        value = self.get(key, pin=True)
        try:
            yield value
        finally:
            if value is not None and self.policy.pin_during_run:
                self.release(key)

    def put(self, key: tuple[str, ...], value, *, size_bytes: int) -> bool:
        key = tuple(str(part) for part in key)
        size_bytes = max(0, int(size_bytes))
        with self._lock:
            old = self._entries.get(key)
            if old is not None and old.pins:
                if old.value is value:
                    return True
                raise RuntimeError("cannot replace a pinned prepared cache entry")
            old = self._entries.pop(key, None)
            if old is not None:
                self._resident_bytes -= old.size_bytes
            if self.policy.max_entries == 0 or size_bytes > self.policy.max_bytes:
                return False
            self._entries[key] = _Entry(value=value, size_bytes=size_bytes)
            self._resident_bytes += size_bytes
            self._evict()
            return key in self._entries

    def _evict(self) -> None:
        while (
            len(self._entries) > self.policy.max_entries
            or self._resident_bytes > self.policy.max_bytes
        ):
            candidate = next((key for key, entry in self._entries.items() if entry.pins == 0), None)
            if candidate is None:
                break
            entry = self._entries.pop(candidate)
            self._resident_bytes -= entry.size_bytes
            self._evictions += 1

    def clear(self, *, force: bool = False) -> dict[str, int]:
        """Clear resident entries with explicit pinned-entry semantics.

        A normal clear refuses to silently discard an entry borrowed by an
        active run. ``force=True`` is reserved for process teardown or an
        explicitly abandoned run; external owners may still keep a value alive
        after cache eviction, but no cache reference remains.
        """

        with self._lock:
            pinned = sum(entry.pins for entry in self._entries.values())
            if pinned and not force:
                raise RuntimeError("cannot clear prepared cache while entries are pinned")
            released_bytes = int(self._resident_bytes)
            released_entries = int(len(self._entries))
            self._entries.clear()
            self._resident_bytes = 0
            self._clears += 1
            self._generation += 1
            return {
                "released_entries": released_entries,
                "released_bytes": released_bytes,
                "generation": int(self._generation),
            }

    @property
    def diagnostics(self) -> dict[str, int]:
        with self._lock:
            return {
                "cache_hit": int(self._hits),
                "cache_miss": int(self._misses),
                "resident_bytes": int(self._resident_bytes),
                "entry_count": int(len(self._entries)),
                "eviction_count": int(self._evictions),
                "reuse_count": int(sum(entry.reuse_count for entry in self._entries.values())),
                "pinned_entries": int(sum(entry.pins > 0 for entry in self._entries.values())),
                "clear_count": int(self._clears),
                "generation": int(self._generation),
            }


__all__ = ["CachePolicy", "PreparedObjectCache", "ResetScope"]
