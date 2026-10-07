import re
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from pydantic_core import PydanticCustomError


LeadStatus = Literal["new", "in_progress", "closed", "rejected"]
Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100)]
Message = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=2000)]
# Разрешаем конкретную структуру номера, а не удаляем любой мусор из ввода.
PHONE_PATTERN = re.compile(r"(?:\+7|8) ?(?:[0-9]{3}|\([0-9]{3}\)) ?[0-9]{3}[ -]?[0-9]{2}[ -]?[0-9]{2}")


class LeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: Name
    phone: str
    message: Message

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        value = value.strip()
        if not PHONE_PATTERN.fullmatch(value):
            raise PydanticCustomError("phone_format", "Неверный формат телефона.")
        digits = re.sub(r"[+ ()-]", "", value)
        return "+7" + digits[1:]


class LeadStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: LeadStatus


class LeadPagination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("limit", "offset", mode="before")
    @classmethod
    def validate_integer(cls, value: object) -> int:
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            try:
                return int(value)
            except ValueError:
                pass
        elif type(value) is int:
            return value
        raise PydanticCustomError("integer_required", "Укажите целое число.")


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str
    message: str
    status: LeadStatus
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def include_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class LeadPage(BaseModel):
    items: list[LeadRead]
    total: int
    limit: int
    offset: int


class LeadCreated(LeadRead):
    telegram_subscription_url: str
