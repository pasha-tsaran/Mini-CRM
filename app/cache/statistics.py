from collections.abc import Callable
from threading import Lock
from time import monotonic

from cachetools import TTLCache


class StatisticsCache:
    """Один набор счётчиков, TTL 30 секунд, с защитой от устаревших расчётов."""

    def __init__(self, timer: Callable[[], float] = monotonic) -> None:
        self._cache = TTLCache(maxsize=1, ttl=30, timer=timer)
        self._lock = Lock()
        self._generation = 0

    def get_or_compute(self, compute: Callable[[], dict[str, int]]) -> dict[str, int]:
        while True:
            with self._lock:
                cached = self._cache.get("counts")
                if cached is not None:
                    return cached.copy()
                generation = self._generation

            # SQL выполняется без блокировки кеша. Каждый повтор — новая транзакция.
            counters = compute()
            with self._lock:
                if generation != self._generation:
                    continue
                self._cache["counts"] = counters.copy()
                return counters.copy()

    def invalidate(self) -> None:
        with self._lock:
            self._generation += 1
            self._cache.clear()
