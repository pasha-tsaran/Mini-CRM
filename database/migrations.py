"""Добавочное обновление схемы; существующие leads не перестраиваются."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, inspect

from database.base import Base


def upgrade(engine: Engine) -> Path | None:
    existing = set(inspect(engine).get_table_names())
    missing = set(Base.metadata.tables) - existing
    backup = None
    if missing and 'leads' in existing:
        source = Path(engine.url.database)
        backups = source.parent / 'backups'
        backups.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = backups / f'{source.stem}-{stamp}-{uuid4().hex[:8]}.sqlite3'
        # SQLite backup API даёт согласованный снимок, в том числе при WAL.
        origin = sqlite3.connect(str(source))
        destination = sqlite3.connect(str(backup))
        try:
            origin.backup(destination)
        finally:
            destination.close()
            origin.close()
    Base.metadata.create_all(engine)
    return backup
