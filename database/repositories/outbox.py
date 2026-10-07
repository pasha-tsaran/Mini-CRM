from datetime import timedelta

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import aliased

from database.repositories.leads import lock_writes
from models.telegram import LeadChannel, Notification


ACTIVE = ('pending', 'retry', 'processing')


def claim(session, now):
    lock_writes(session)
    older = aliased(Notification)
    blocked_by_previous = exists(select(older.id).where(
        older.lead_id == Notification.lead_id, older.id < Notification.id, older.state.in_(ACTIVE)))
    item = session.scalar(select(Notification).where(
        ~blocked_by_previous,
        or_(and_(Notification.state.in_(('pending', 'retry')), Notification.next_attempt_at <= now),
            and_(Notification.state == 'processing', Notification.lease_until <= now)),
    ).order_by(Notification.id).limit(1))
    if item:
        item.state = 'processing'
        item.attempts += 1
        item.lease_until = now + timedelta(seconds=60)
        session.flush()
    return item


def finish(session, item_id, attempt):
    lock_writes(session)
    item = session.get(Notification, item_id)
    if item and item.state == 'processing' and item.attempts == attempt:
        return item
    return None


def block_chat(session, chat_id):
    session.execute(update(LeadChannel).where(LeadChannel.chat_id == chat_id).values(subscription='blocked'))
    session.execute(update(Notification).where(Notification.chat_id == chat_id, Notification.state.in_(ACTIVE)).values(
        state='blocked', error_code='bot_blocked', lease_until=None))
