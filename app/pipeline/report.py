"""Сквозная обработка запроса на отчёт — дорожка «Автоматизированная система» BPMN TO-BE.

Этап start_report выполняется до перенаправления пользователя, finish_report —
уже после него, как и на диаграмме: страница отчёта показывает ход обработки.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, time

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app import metrics, rules
from app.db import publications_session, reports_session
from app.models import Mention, MonitoringObject, Publication, Report, ReportPublication, Source, utcnow
from app.nlp import clustering, dedup, relevance, roles, sentiment
from app.nlp.objects import ObjectMatcher
from app.nlp.text import STOPWORDS, content_lemmas, lemma, parse_document, words
from app.nlp.topics import TOPIC_NAMES, topic_scores

logger = logging.getLogger(__name__)

ALL_CONTEXTS = "all"

STEPS = [
    ("query", "Выполнить запрос к базе данных", "system"),
    ("sentiment", "Провести оценку тональности", "system"),
    ("role", "Определить главную роль", "system"),
    ("redirect", "Перенаправить на страницу отчёта", "system"),
    ("relevance", "Проверить релевантность публикаций", "system"),
    ("duplicates", "Удалить дубликаты", "system"),
    ("random", "Удалить случайные публикации", "system"),
    ("analytics", "Кластеризовать темы и рассчитать метрики", "system"),
    ("export", "Экспортировать отчёт", "employee"),
    ("document", "Сформировать документ", "system"),
]


@dataclass
class ReportRequest:
    object_id: int
    context_code: str
    date_from: datetime
    date_to: datetime
    source_ids: list[int]
    context_keywords: str = ""


@dataclass
class _Analyzed:
    publication: Publication
    document: object
    stats: object
    tone: object = None
    role: object = None
    extra: dict = field(default_factory=dict)


def mark_step(report: Report, code: str, status: str, detail: str = "") -> None:
    # Новый список нужен, чтобы SQLAlchemy заметил изменение JSON-колонки.
    updated = []
    for step in report.steps:
        step = dict(step)
        if step["code"] == code:
            step.update(status=status, detail=detail, finished_at=utcnow().isoformat(timespec="seconds"))
        updated.append(step)
    report.steps = updated


def _initial_steps() -> list[dict]:
    return [
        {"code": code, "title": title, "lane": lane, "status": "pending", "detail": "", "finished_at": None}
        for code, title, lane in STEPS
    ]


def context_name(code: str) -> str:
    return "Все темы" if code == ALL_CONTEXTS else TOPIC_NAMES.get(code, code)


def _keyword_lemmas(keywords: str) -> set[str]:
    return {lemma(word) for word in words(keywords)} - STOPWORDS


def query_publications(session: Session, request: ReportRequest) -> list[Publication]:
    """Запрос к базе публикаций по объекту, контексту, периоду и источникам."""
    date_to = datetime.combine(request.date_to.date(), time.max)
    publishers = select(Source.id).where(Source.parent_id.in_(request.source_ids))
    statement = (
        select(Publication)
        .join(Mention, Mention.publication_id == Publication.id)
        .options(joinedload(Publication.source))
        .where(
            Mention.object_id == request.object_id,
            Publication.published_at >= request.date_from,
            Publication.published_at <= date_to,
            or_(Publication.source_id.in_(request.source_ids), Publication.source_id.in_(publishers)),
        )
        .order_by(Publication.published_at)
    )
    if request.context_code != ALL_CONTEXTS:
        statement = statement.where(Publication.topic == request.context_code)
    rows = list(session.scalars(statement).unique().all())

    keywords = _keyword_lemmas(request.context_keywords)
    if keywords:
        rows = [row for row in rows if keywords & set(content_lemmas(f"{row.title} {row.text}"))]
    return rows


def _snapshot(report_id: int, item: _Analyzed) -> ReportPublication:
    publication = item.publication
    source = publication.source
    return ReportPublication(
        report_id=report_id,
        publication_id=publication.id,
        title=publication.title,
        text=publication.text,
        url=publication.url,
        published_at=publication.published_at,
        source_name=source.name,
        source_level=source.level,
        source_authority=source.authority,
        media_type=source.media_type,
        is_synthetic=publication.is_synthetic,
        topic=publication.topic,
        entities=publication.entities,
        sentiment=item.tone.label,
        sentiment_score=item.tone.score,
        sentiment_evidence=item.tone.evidence,
        role=item.role.role,
        main_entity=item.role.main_entity,
    )


def start_report(request: ReportRequest) -> int | None:
    """Запрос, тональность, главная роль. None означает «данные не найдены»."""
    with publications_session() as session:
        item = session.get(MonitoringObject, request.object_id)
        rows = query_publications(session, request)
        if not rows:
            return None

        matcher = ObjectMatcher.from_model(item)
        analyzed = []
        for publication in rows:
            document = parse_document(publication.title, publication.text)
            analyzed.append(_Analyzed(publication, document, matcher.match(document)))

        for entry in analyzed:
            entry.tone = sentiment.analyze_sentiment(entry.document, entry.stats.target_sentences or None)
        for entry in analyzed:
            entry.role = roles.determine_role(entry.publication.entities, entry.stats, matcher)

        with reports_session() as reports:
            period = f"{request.date_from:%d.%m.%Y} – {request.date_to:%d.%m.%Y}"
            report = Report(
                title=f"{item.name}: {context_name(request.context_code)}, {period}",
                object_id=item.id,
                object_name=item.name,
                context_code=request.context_code,
                context_name=context_name(request.context_code),
                context_keywords=request.context_keywords,
                date_from=request.date_from,
                date_to=request.date_to,
                sources=sorted({entry.publication.source.name for entry in analyzed}),
                steps=_initial_steps(),
                has_synthetic=any(entry.publication.is_synthetic for entry in analyzed),
                methods={"sentiment": sentiment.method_name()},
            )
            reports.add(report)
            reports.flush()
            reports.add_all(_snapshot(report.id, entry) for entry in analyzed)
            mark_step(report, "query", "done", f"Найдено публикаций: {len(rows)}")
            mark_step(report, "sentiment", "done", "Оценка по единой шкале выполнена")
            mark_step(report, "role", "done", "Главный объект и роль определены")
            mark_step(report, "redirect", "done", "Пользователь перенаправлен на страницу отчёта")
            return report.id


def _find_removals(publications, matcher: ObjectMatcher) -> tuple[dict[int, int], dict[int, relevance.RelevanceResult]]:
    documents = {item.id: parse_document(item.title, item.text) for item in publications}
    duplicates = dedup.find_duplicates(
        [
            dedup.DedupItem(item.id, content_lemmas(f"{item.title} {item.text}"), item.published_at, item.source_authority)
            for item in publications
        ]
    )
    checks = {
        item.id: relevance.check_relevance(documents[item.id], matcher.match(documents[item.id]), matcher)
        for item in publications
    }
    return duplicates, checks


def finish_report(report_id: int) -> None:
    """Релевантность, удаление лишнего, кластеры и метрики."""
    try:
        with reports_session() as session:
            report = session.get(Report, report_id)
            with publications_session() as publications:
                matcher = ObjectMatcher.from_model(publications.get(MonitoringObject, report.object_id))
            items = session.scalars(select(ReportPublication).where(ReportPublication.report_id == report_id)).all()
            _clean_selection(session, report, items, matcher)
            _build_analytics(session, report, items)
    except Exception as error:
        logger.exception("Ошибка обработки отчёта %s", report_id)
        with reports_session() as session:
            report = session.get(Report, report_id)
            report.status = "failed"
            report.error = str(error)


def _clean_selection(session: Session, report: Report, items, matcher: ObjectMatcher) -> None:
    duplicates, checks = _find_removals(items, matcher)
    irrelevant = [item for item in items if not checks[item.id].is_relevant and item.id not in duplicates]
    for item in items:
        item.relevance_score = checks[item.id].score

    all_relevant = not duplicates and not irrelevant
    verdict = "Все публикации релевантны" if all_relevant else (
        f"Нерелевантных: {len(irrelevant) + len(duplicates)}"
    )
    mark_step(report, "relevance", "done", verdict)
    session.commit()

    if all_relevant:
        mark_step(report, "duplicates", "skipped", "Не требуется")
        mark_step(report, "random", "skipped", "Не требуется")
        session.commit()
        return

    by_id = {item.id: item for item in items}
    for duplicate_id, original_id in duplicates.items():
        duplicate, original = by_id[duplicate_id], by_id[original_id]
        duplicate.status = "duplicate"
        duplicate.duplicate_of = original_id
        duplicate.removal_reason = f"Перепечатка публикации «{original.title}» ({original.source_name})"
        original.reprints += 1
    mark_step(report, "duplicates", "done", f"Удалено дубликатов: {len(duplicates)}")
    session.commit()

    for item in irrelevant:
        item.status = "random"
        reasons = checks[item.id].reasons or ["низкая значимость объекта в тексте"]
        item.removal_reason = "; ".join(reasons).capitalize()
    mark_step(report, "random", "done", f"Удалено случайных публикаций: {len(irrelevant)}")
    session.commit()


def _build_analytics(session: Session, report: Report, items) -> None:
    kept = [item for item in items if item.status == "relevant"]
    for item in kept:
        if item.sentiment == "negative":
            item.reputation_weight = metrics.reputation_weight(
                item.source_authority, item.role, item.sentiment_score, item.reprints
            )

    assignment, clusters = clustering.cluster_publications(
        [
            clustering.ClusterInput(
                item.id,
                item.title,
                content_lemmas(f"{item.title} {item.text}"),
                item.topic,
                list(topic_scores(item.title, item.text).values()),
            )
            for item in kept
        ]
    )
    for item in kept:
        item.cluster = assignment.get(item.id)
    for cluster in clusters:
        members = [item for item in kept if item.cluster == cluster["id"]]
        cluster["negative"] = sum(1 for item in members if item.sentiment == "negative")
        cluster["positive"] = sum(1 for item in members if item.sentiment == "positive")

    report.clusters = clusters
    report.metrics = metrics.compute_metrics(items, report.date_from, report.date_to)
    report.status = "ready"
    mark_step(report, "analytics", "done", f"Кластеров: {len(clusters)}, метрики рассчитаны")
