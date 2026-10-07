from datetime import timezone
from zoneinfo import ZoneInfo

from database.repositories import telegram


STATUS_LABELS = {'new': 'Новая', 'in_progress': 'В работе', 'closed': 'Закрыта', 'rejected': 'Отклонена'}


def record_transition(session, lead, old_status, changed_at):
    event = telegram.add_event(session, lead.id, old_status, lead.status, changed_at)
    channel = telegram.channel(session, lead.id)
    if channel and channel.subscription == 'active':
        telegram.enqueue(session, event_key=f'status:{event.id}', lead_id=lead.id,
                         chat_id=channel.chat_id, status=lead.status,
                         event_at=changed_at, next_attempt_at=changed_at)


def format_notification(item, zone_name: str) -> str:
    title = 'Текущий статус' if item.kind == 'snapshot' else 'Статус'
    text = f'Заявка №{item.lead_id}\n{title}: {STATUS_LABELS[item.status]}'
    if item.event_at is None:
        return text + '\nВремя изменения статуса не зафиксировано.'
    local = item.event_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zone_name))
    label = 'МСК' if zone_name == 'Europe/Moscow' else f'{zone_name} (UTC{local:%z})'
    action = 'Взята в работу' if item.status == 'in_progress' else 'Время изменения'
    return f'{text}\n{action}: {local:%d.%m.%Y, %H:%M} {label}'
