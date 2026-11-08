"""Модуль сбора публикаций: новые записи из источников в базу публикаций.

Каждый шаг пишется в журнал отладки (collection_events), поэтому на странице
«Отладка сбора» видно, какой сайт запрошен, что он ответил и где найдено упоминание.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import config, rules
from app.collector import feeds
from app.collector.inspect import mention_evidence
from app.db import publications_session
from app.models import CollectionEvent, CollectionRun, Source, utcnow
from app.nlp.topics import TOPIC_NAMES
from app.pipeline.ingest import find_mentions, ingest_item, known_urls, load_matchers

logger = logging.getLogger(__name__)

EVENTS_COMMIT_EVERY = 25
KEEP_RUNS_WITH_EVENTS = 20
STALE_RUN = timedelta(minutes=30)


@dataclass
class SourceResult:
    source_id: int
    seen: int = 0
    added: int = 0
    error: str | None = None


class Trace:
    """Пишет события сбора в ту же сессию, чтобы они фиксировались вместе с публикациями."""

    def __init__(self, session: Session, run_id: int | None, source: Source):
        self.session = session
        self.run_id = run_id
        self.source = source
        self.pending = 0

    def __call__(self, stage: str, message: str, title: str = "", url: str = "", **details) -> None:
        self.session.add(
            CollectionEvent(
                run_id=self.run_id, source_id=self.source.id, source_name=self.source.name, stage=stage,
                message=message, title=title, url=url, details=details,
            )
        )
        self.pending += 1
        if self.pending >= EVENTS_COMMIT_EVERY:
            self.commit()

    def commit(self) -> None:
        self.session.commit()
        self.pending = 0


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


def collect_source(source_id: int, run_id: int | None = None) -> SourceResult:
    """Забирает ленту, отбирает записи с упоминанием объектов и обрабатывает их."""
    result = SourceResult(source_id=source_id)
    with publications_session() as session:
        source = session.get(Source, source_id)
        trace = Trace(session, run_id, source)
        matchers = load_matchers(session)
        known = known_urls(session)

        trace("fetch", f"Запрашиваю ленту {source.feed_url}", url=source.feed_url)
        try:
            response = feeds.fetch(source.feed_url)
            info = feeds.describe_response(response)
            trace("fetch", f"Ответ {info['status']}: {info['bytes'] // 1024} КБ за {info['ms']} мс", **info)
            items = feeds.parse_feed(response.content)
            trace("parse", f"В ленте записей: {len(items)}")
        except feeds.CollectorError as error:
            result.error = str(error)
            trace("error", result.error)
            items = []
        trace.commit()  # заход на сайт должен быть виден в журнале сразу

        result.seen = len(items)
        for item in items:
            if item.url in known:
                trace("skip", "Уже есть в базе", item.title, item.url)
                continue
            mentions = find_mentions(item.title, item.text, matchers)
            if not mentions:
                trace("skip", "Упоминаний объектов нет", item.title, item.url)
                continue
            names = ", ".join(matcher.name for matcher, _ in mentions)
            trace("match", f"Найдено упоминание: {names}", item.title, item.url, **mention_evidence(item.title, item.text, mentions))

            full_text = feeds.fetch_article_text(item.url)
            if full_text:
                trace("article", f"Загружен полный текст статьи: {len(full_text)} символов", item.title, item.url)
            else:
                trace("article", "Полный текст недоступен, используется анонс из ленты", item.title, item.url)
            item.text = full_text or item.text or item.title
            known.add(item.url)

            target = _publisher_source(session, source, item.publisher) if item.publisher else source
            publication = ingest_item(session, target, item, matchers)
            if publication is None:
                trace("skip", "В полном тексте упоминание не подтвердилось", item.title, item.url)
            else:
                result.added += 1
                trace(
                    "saved",
                    f"Сохранено: тема «{TOPIC_NAMES.get(publication.topic, publication.topic)}», "
                    f"тональность {rules.SENTIMENT_LABELS[publication.tone].lower()}",
                    item.title, item.url, publication_id=publication.id, publisher=target.name,
                    entities=[entity["name"] for entity in publication.entities[:8]],
                )
            trace.commit()  # загрузка следующей статьи не должна держать блокировку базы

        source.last_collected_at = utcnow()
        source.last_status = result.error or f"Просмотрено {result.seen}, добавлено {result.added}"
        trace("done", source.last_status)
    return result


def close_interrupted_runs() -> int:
    """Запуски, оборванные остановкой приложения, иначе навсегда остались бы «идущими»."""
    with publications_session() as session:
        runs = session.scalars(select(CollectionRun).where(CollectionRun.finished_at.is_(None))).all()
        for run in runs:
            run.finished_at = utcnow()
            run.errors = [*run.errors, {"source_id": None, "error": "Сбор прерван: приложение было остановлено"}]
        return len(runs)


def start_run(trigger: str) -> tuple[int, bool]:
    """Создаёт запуск. Если полный сбор уже идёт, возвращает его и False."""
    with publications_session() as session:
        if trigger != "custom":
            running = session.scalar(
                select(CollectionRun).where(
                    CollectionRun.finished_at.is_(None),
                    CollectionRun.trigger != "custom",
                    CollectionRun.started_at > utcnow() - STALE_RUN,
                )
            )
            if running is not None:
                return running.id, False
        run = CollectionRun(trigger=trigger)
        session.add(run)
        session.flush()
        return run.id, True


def execute_run(run_id: int, source_ids: list[int] | None = None) -> CollectionRun:
    with publications_session() as session:
        if source_ids is None:
            source_ids = list(
                session.scalars(select(Source.id).where(Source.is_active, Source.feed_url.is_not(None))).all()
            )

    seen, added, errors = 0, 0, []
    for source_id in source_ids:
        try:
            result = collect_source(source_id, run_id)
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
        _prune_events(session)
    logger.info("Сбор %s завершён: просмотрено %s, добавлено %s, ошибок %s", run_id, seen, added, len(errors))
    return run


def _prune_events(session: Session) -> None:
    """Журнал отладки хранится только для последних запусков."""
    keep = select(CollectionRun.id).order_by(CollectionRun.id.desc()).limit(KEEP_RUNS_WITH_EVENTS)
    session.execute(delete(CollectionEvent).where(CollectionEvent.run_id.not_in(keep)))


def collect_all(trigger: str = "manual") -> CollectionRun:
    run_id, _ = start_run(trigger)
    return execute_run(run_id)


def collect_custom(source_id: int) -> SourceResult:
    """Свой источник сотрудника собирается отдельным запуском, чтобы его было видно в отладке."""
    run_id, _ = start_run("custom")
    run = execute_run(run_id, [source_id])
    error = run.errors[0]["error"] if run.errors else None
    return SourceResult(source_id=source_id, seen=run.items_seen, added=run.items_added, error=error)


def last_run() -> dict:
    with publications_session() as session:
        run = session.scalar(select(CollectionRun).order_by(CollectionRun.started_at.desc()))
        if run is None:
            return {"id": None, "running": False, "added": 0, "seen": 0, "errors": 0, "finished_at": None}
        return {
            "id": run.id,
            "running": run.finished_at is None,
            "added": run.items_added,
            "seen": run.items_seen,
            "errors": len(run.errors),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }


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
    """Сбор сразу после запуска и затем по расписанию, пока работает приложение."""
    if config.COLLECT_INTERVAL_MINUTES <= 0:
        return
    while True:
        try:
            await asyncio.to_thread(collect_all, "schedule")
        except Exception:
            logger.exception("Ошибка планового сбора")
        await asyncio.sleep(config.COLLECT_INTERVAL_MINUTES * 60)
