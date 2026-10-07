from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.lead import LeadCreate


TelegramId = Annotated[int, Field(strict=True, gt=0, le=2**52 - 1)]
RequestId = Annotated[str, Field(min_length=16, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')]


class Recipient(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    telegram_user_id: TelegramId
    telegram_chat_id: TelegramId

    @model_validator(mode='after')
    def private_chat(self):
        if self.telegram_user_id != self.telegram_chat_id:
            raise ValueError('Нужен личный чат отправителя.')
        return self


class TelegramLead(LeadCreate, Recipient):
    submission_id: RequestId


class TelegramBinding(Recipient):
    code: Annotated[str, Field(min_length=32, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')]
    request_id: RequestId
