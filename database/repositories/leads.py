from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from models.lead import Lead


def lock_writes(session: Session) -> None:
    """Захватить SQLite write lock до чтения для атомарных read-modify-write."""
    session.execute(text('BEGIN IMMEDIATE'))


def add(session: Session, *, name: str, phone: str, message: str) -> Lead:
    lead = Lead(name=name, phone=phone, message=message)
    session.add(lead)
    session.flush()
    return lead


def get(session: Session, lead_id: int) -> Lead | None:
    if not 1 <= lead_id <= 2**63 - 1:
        return None
    return session.get(Lead, lead_id)


def list_page(session: Session, limit: int, offset: int) -> list[Lead]:
    if offset > 2**63 - 1:
        return []
    query = select(Lead).order_by(Lead.created_at.desc(), Lead.id.desc()).limit(limit).offset(offset)
    return list(session.scalars(query))


def count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Lead)) or 0


def statistics(session: Session) -> dict[str, int]:
    counters = {"total": 0, "new": 0, "in_progress": 0, "closed": 0, "rejected": 0}
    query = select(Lead.status, func.count()).group_by(Lead.status)
    for status, amount in session.execute(query):
        counters[status] = amount
        counters["total"] += amount
    return counters
