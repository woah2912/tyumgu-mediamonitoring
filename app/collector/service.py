"""Модуль сбора публикаций: новые записи из источников в базу публикаций."""
import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select

from app import config, rules
from app.collector import feeds
from app.db import publications_session
from app.models import CollectionRun, Source, utcnow
from app.pipeline.ingest import has_mention, ingest_item, known_urls, load_matchers

logger = logging.getLogger(__name__)


@dataclass
class SourceResult:
    source_id: int
    seen: int = 0
    added: int = 0
    error: str | None = None


def _publisher_source(session, aggregator: Source, name: str) -> Source:
    source = session.scalar(select(Source).where(Source.name == name))
    if source is None:
        level = "federal" if name in rules.FEDERAL_PUBLISHERS else "regional"
        source = Source(
            name=name, parent_id=aggregator.id, media_type="Онлайн-СМИ", level=level,
            authority=rules.LEVEL_AUTHORITY[level],
        )
        session.add(source)
        session.flush()
    return source


def collect_source(source_id: int) -> SourceResult:
    """Забирает ленту, отбирает записи с упоминанием объектов и обрабатывает их."""
    result = SourceResult(source_id=source_id)
    with publications_session() as session:
        source = session.get(Source, source_id)
        matchers = load_matchers(session)
        known = known_urls(session)
        try:
            items = feeds.parse_feed(feeds.fetch(source.feed_url).content)
        except feeds.CollectorError as error:
            result.error = str(error)
            items = []

        result.seen = len(items)
        for item in items:
            if item.url in known or not has_mention(item.title, item.text, matchers):
                continue
            item.text = feeds.fetch_article_text(item.url) or item.text or item.title
            known.add(item.url)
            target = _publisher_source(session, source, item.publisher) if item.publisher else source
            if ingest_item(session, target, item, matchers) is not None:
                result.added += 1
            session.commit()  # загрузка следующей статьи не должна держать блокировку базы

        source.last_collected_at = utcnow()
        source.last_status = result.error or f"Просмотрено {result.seen}, добавлено {result.added}"
    return result


def last_run() -> dict:
    with publications_session() as session:
        run = session.scalar(select(CollectionRun).order_by(CollectionRun.started_at.desc()))
        if run is None:
            return {"running": False, "added": 0, "seen": 0, "errors": 0, "finished_at": None}
        return {
            "running": run.finished_at is None,
            "added": run.items_added,
            "seen": run.items_seen,
            "errors": len(run.errors),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }


def collect_all(trigger: str = "manual") -> CollectionRun:
    with publications_session() as session:
        run = CollectionRun(trigger=trigger)
        session.add(run)
        session.flush()
        run_id = run.id
        source_ids = session.scalars(
            select(Source.id).where(Source.is_active, Source.feed_url.is_not(None))
        ).all()

    seen, added, errors = 0, 0, []
    for source_id in source_ids:
        try:
            result = collect_source(source_id)
        except Exception as error:  # сбой одного источника не должен останавливать сбор
            logger.exception("Ошибка сбора источника %s", source_id)
            result = SourceResult(source_id=source_id, error=str(error))
        seen += result.seen
        added += result.added
        if result.error:
            errors.append({"source_id": source_id, "error": result.error})

    with publications_session() as session:
        run = session.get(CollectionRun, run_id)
        run.sources_total = len(source_ids)
        run.items_seen = seen
        run.items_added = added
        run.errors = errors
        run.finished_at = utcnow()
    return run


def register_custom_source(url: str, name: str = "") -> tuple[int, str | None]:
    """Добавляет свой источник сотрудника. Возвращает его id и текст ошибки."""
    url = url.strip()
    with publications_session() as session:
        existing = session.scalar(select(Source).where(Source.url == url))
        if existing is None:
            existing = session.scalar(select(Source).where(Source.feed_url == url))
        if existing is not None:
            return existing.id, None

    feed_url = feeds.find_feed_url(url)
    with publications_session() as session:
        existing = session.scalar(select(Source).where(Source.feed_url == feed_url))
        if existing is not None:
            return existing.id, None
        source = Source(
            name=name.strip() or urlparse(url).hostname or url,
            url=url,
            feed_url=feed_url,
            media_type="Свой источник",
            level="local",
            authority=rules.LEVEL_AUTHORITY["local"],
            is_custom=True,
        )
        session.add(source)
        session.flush()
        return source.id, None


async def collection_loop() -> None:
    """Периодический сбор, пока работает приложение."""
    if config.COLLECT_INTERVAL_MINUTES <= 0:
        return
    while True:
        await asyncio.sleep(config.COLLECT_INTERVAL_MINUTES * 60)
        try:
            await asyncio.to_thread(collect_all, "schedule")
        except Exception:
            logger.exception("Ошибка планового сбора")
