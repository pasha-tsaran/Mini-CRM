from sqlalchemy.orm import Session

from app.cache.statistics import StatisticsCache
from database.repositories import leads as repository


def get_statistics(session: Session) -> dict[str, int]:
    cache: StatisticsCache = session.info["statistics_cache"]

    def compute() -> dict[str, int]:
        with session.begin():
            return repository.statistics(session)

    return cache.get_or_compute(compute)


def invalidate_statistics(session: Session) -> None:
    # Зависимость передаётся фабрикой сессий, без Flask внутри сервиса.
    cache: StatisticsCache | None = session.info.get("statistics_cache")
    if cache is not None:
        cache.invalidate()
