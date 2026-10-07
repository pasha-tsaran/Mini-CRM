import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.schemas.telegram import TelegramBinding
from database.repositories import leads, telegram


class IntegrationConflict(Exception):
    """Несовместимый повтор запроса или недействительный код привязки."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fingerprint(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def token_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def issue_code(session: Session, lead_id: int, username: str) -> str:
    code = secrets.token_urlsafe(32)
    telegram.add_code(session, token_hash=token_hash(code), lead_id=lead_id,
                      expires_at=utcnow() + timedelta(minutes=30))
    return f'https://t.me/{username}?start={code}'


def bind_telegram(session: Session, data: TelegramBinding) -> dict:
    with session.begin():
        leads.lock_writes(session)
        # Бот хранит и передаёт только SHA-256 start-кода; raw-вариант допустим
        # исключительно на этом авторизованном маршруте, для API-клиентов.
        digest = data.code if len(data.code) == 64 and all(c in '0123456789abcdef' for c in data.code) else token_hash(data.code)
        code = telegram.binding_code(session, digest)
        if code is None:
            raise IntegrationConflict
        previous = telegram.binding_request(session, data.request_id)
        if previous is not None and previous.token_hash != digest:
            raise IntegrationConflict
        # Идемпотентный повтор именно подтверждения после потери ответа CRM.
        if code.used_at:
            if (code.request_id, code.user_id, code.chat_id) == (data.request_id, data.telegram_user_id, data.telegram_chat_id):
                return {'id': code.lead_id, 'subscribed': True}
            raise IntegrationConflict
        if code.expires_at <= utcnow():
            raise IntegrationConflict
        channel = telegram.channel(session, code.lead_id)
        if channel and channel.chat_id is not None:
            raise IntegrationConflict
        if channel is None:
            channel = telegram.add_channel(session, code.lead_id)
        channel.user_id = data.telegram_user_id
        channel.chat_id = data.telegram_chat_id
        channel.subscription = 'active'
        code.used_at, code.request_id = utcnow(), data.request_id
        code.user_id, code.chat_id = data.telegram_user_id, data.telegram_chat_id
        lead = leads.get(session, code.lead_id)
        event = telegram.latest_event(session, lead.id)
        telegram.enqueue(session, event_key=f'binding:{lead.id}', lead_id=lead.id,
                         chat_id=channel.chat_id, status=lead.status, kind='snapshot',
                         event_at=event.changed_at if event else None, next_attempt_at=utcnow())
        result = {'id': lead.id, 'subscribed': True}
    return result


def delivery_overview(session: Session, lead_ids: list[int]) -> dict:
    with session.begin():
        return telegram.overview(session, lead_ids)
