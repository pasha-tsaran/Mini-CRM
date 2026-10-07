from sqlalchemy.orm import Session

from app.schemas.lead import LeadCreate, LeadCreated, LeadPage, LeadPagination, LeadRead, LeadStatusUpdate
from app.schemas.telegram import TelegramLead
from app.services.notifications import record_transition
from app.services.statistics import invalidate_statistics
from app.services.telegram import IntegrationConflict, fingerprint, issue_code, utcnow
from database.repositories import leads as repository
from database.repositories import telegram as telegram_repository


class LeadNotFoundError(Exception):
    """Заявка с указанным идентификатором не существует."""


def create_lead(session: Session, data: LeadCreate, *, telegram: TelegramLead | None = None,
                bot_username: str | None = None) -> LeadRead:
    # Контекст завершает commit до возврата; при исключении выполняет rollback.
    with session.begin():
        repository.lock_writes(session)
        if telegram:
            digest = fingerprint(telegram.model_dump())
            existing = telegram_repository.submission(session, telegram.submission_id)
            if existing:
                if existing.fingerprint != digest:
                    raise IntegrationConflict
                return LeadRead.model_validate(repository.get(session, existing.lead_id))
        lead = repository.add(session, **data.model_dump())
        if telegram:
            telegram_repository.add_channel(session, lead.id, 'telegram', telegram.telegram_user_id, telegram.telegram_chat_id)
            telegram_repository.remember_submission(session, telegram.submission_id, digest, lead.id)
        result = LeadRead.model_validate(lead)
        if bot_username and not telegram:
            result = LeadCreated(**result.model_dump(), telegram_subscription_url=issue_code(session, lead.id, bot_username))
    invalidate_statistics(session)
    return result


def list_leads(session: Session, pagination: LeadPagination) -> LeadPage:
    with session.begin():
        total = repository.count(session)
        items = repository.list_page(session, pagination.limit, pagination.offset)
        return LeadPage(
            items=[LeadRead.model_validate(lead) for lead in items],
            total=total, limit=pagination.limit, offset=pagination.offset,
        )


def update_status(session: Session, lead_id: int, data: LeadStatusUpdate) -> LeadRead:
    with session.begin():
        repository.lock_writes(session)
        lead = repository.get(session, lead_id)
        if lead is None:
            raise LeadNotFoundError
        old_status = lead.status
        lead.status = data.status
        if old_status != data.status:
            record_transition(session, lead, old_status, utcnow())
        session.flush()
        result = LeadRead.model_validate(lead)
    invalidate_statistics(session)
    return result
