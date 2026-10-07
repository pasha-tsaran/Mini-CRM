from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint("length(name) <= 100 AND length(trim(name)) >= 1", name="ck_leads_name_length"),
        CheckConstraint("length(message) <= 2000 AND length(trim(message)) >= 1", name="ck_leads_message_length"),
        CheckConstraint(
            "length(phone) = 12 AND substr(phone, 1, 2) = '+7' "
            "AND substr(phone, 3) NOT GLOB '*[^0-9]*'",
            name="ck_leads_phone_format",
        ),
        CheckConstraint(
            "status IN ('new', 'in_progress', 'closed', 'rejected')",
            name="ck_leads_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(12), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", server_default="new")
    # SQLite хранит наивное время; все значения в этой колонке по договору — UTC.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        server_default=text("CURRENT_TIMESTAMP"),
    )
