from flask import Flask, g
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import database_path
from database.init_db import init_db


def init_app(app: Flask) -> None:
    path = database_path(app.config["DATABASE_PATH"])
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create("sqlite", database=str(path)))
    factory = sessionmaker(
        bind=engine, expire_on_commit=False,
        info={"statistics_cache": app.extensions["statistics_cache"]},
    )
    init_db(engine)
    app.extensions["database_engine"] = engine
    app.extensions["db_session_factory"] = factory

    @app.before_request
    def open_session() -> None:
        g.db_session = factory()

    @app.teardown_request
    def close_session(error: BaseException | None) -> None:
        session = g.pop("db_session", None)
        if session is not None:
            # close также откатывает оставшуюся незавершённую транзакцию чтения.
            session.close()


def get_session() -> Session:
    return g.db_session
