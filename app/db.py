"""Подключения к двум базам: публикации (publications.db) и отчёты (reports.db)."""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app import config


class PublicationsBase(DeclarativeBase):
    """Базовый класс таблиц базы публикаций."""


class ReportsBase(DeclarativeBase):
    """Базовый класс таблиц базы отчётов."""


def _make_engine(url: str):
    connect_args = {}
    if url.startswith("sqlite"):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False, "timeout": 30}
    return create_engine(url, connect_args=connect_args)


publications_engine = _make_engine(config.PUBLICATIONS_DB_URL)
reports_engine = _make_engine(config.REPORTS_DB_URL)

_PublicationsSession = sessionmaker(publications_engine, expire_on_commit=False)
_ReportsSession = sessionmaker(reports_engine, expire_on_commit=False)


@contextmanager
def _scope(factory) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def publications_session():
    return _scope(_PublicationsSession)


def reports_session():
    return _scope(_ReportsSession)


def init_db() -> None:
    from app import models  # noqa: F401  регистрирует таблицы

    PublicationsBase.metadata.create_all(publications_engine)
    ReportsBase.metadata.create_all(reports_engine)
