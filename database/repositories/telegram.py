from sqlalchemy import select
from sqlalchemy.orm import Session

from models.telegram import BindingCode, LeadChannel, Notification, StatusEvent, Submission


def submission(session: Session, request_id: str) -> Submission | None:
    return session.get(Submission, request_id)


def remember_submission(session: Session, request_id: str, fingerprint: str, lead_id: int):
    session.add(Submission(submission_id=request_id, fingerprint=fingerprint, lead_id=lead_id))


def channel(session: Session, lead_id: int) -> LeadChannel | None:
    return session.get(LeadChannel, lead_id)


def add_channel(session: Session, lead_id: int, source='web', user_id=None, chat_id=None):
    result = LeadChannel(lead_id=lead_id, source=source, user_id=user_id, chat_id=chat_id,
                         subscription='active' if chat_id else 'none')
    session.add(result)
    return result


def add_code(session: Session, **values):
    session.add(BindingCode(**values))


def binding_code(session: Session, token_hash: str) -> BindingCode | None:
    return session.get(BindingCode, token_hash)


def binding_request(session: Session, request_id: str) -> BindingCode | None:
    return session.scalar(select(BindingCode).where(BindingCode.request_id == request_id))


def add_event(session: Session, lead_id, old_status, new_status, changed_at) -> StatusEvent:
    result = StatusEvent(lead_id=lead_id, old_status=old_status, new_status=new_status, changed_at=changed_at)
    session.add(result)
    session.flush()
    return result


def latest_event(session: Session, lead_id: int) -> StatusEvent | None:
    return session.scalar(select(StatusEvent).where(StatusEvent.lead_id == lead_id).order_by(StatusEvent.id.desc()).limit(1))


def enqueue(session: Session, **values) -> None:
    session.add(Notification(**values))


def overview(session: Session, lead_ids: list[int]) -> dict:
    channels = {item.lead_id: item for item in session.scalars(select(LeadChannel).where(LeadChannel.lead_id.in_(lead_ids)))}
    latest = {}
    for item in session.scalars(select(Notification).where(Notification.lead_id.in_(lead_ids)).order_by(Notification.id.desc())):
        latest.setdefault(item.lead_id, item.state)
    return {lead_id: {'source': channels[lead_id].source if lead_id in channels else 'web',
                      'subscription': channels[lead_id].subscription if lead_id in channels else 'none',
                      'delivery': latest.get(lead_id)} for lead_id in lead_ids}
