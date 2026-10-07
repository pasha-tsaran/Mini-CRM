from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class LeadChannel(Base):
    __tablename__ = 'lead_channels'
    __table_args__ = (
        CheckConstraint("source IN ('web', 'telegram')"),
        CheckConstraint("subscription IN ('none', 'active', 'blocked')"),
    )
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), primary_key=True)
    source: Mapped[str] = mapped_column(String, default='web')
    user_id: Mapped[int | None] = mapped_column(Integer)
    chat_id: Mapped[int | None] = mapped_column(Integer)
    subscription: Mapped[str] = mapped_column(String, default='none')


class Submission(Base):
    __tablename__ = 'telegram_submissions'
    submission_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), unique=True)


class BindingCode(Base):
    __tablename__ = 'telegram_binding_codes'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    chat_id: Mapped[int | None] = mapped_column(Integer)


class StatusEvent(Base):
    __tablename__ = 'lead_status_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    old_status: Mapped[str] = mapped_column(String)
    new_status: Mapped[str] = mapped_column(String)
    changed_at: Mapped[datetime] = mapped_column(DateTime)


class Notification(Base):
    __tablename__ = 'notification_outbox'
    __table_args__ = (Index('ix_outbox_due', 'state', 'next_attempt_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String, unique=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    chat_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default='transition')
    event_at: Mapped[datetime | None] = mapped_column(DateTime)
    state: Mapped[str] = mapped_column(String, default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String)
