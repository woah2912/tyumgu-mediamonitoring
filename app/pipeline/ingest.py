"""Обработка новой публикации при сборе: тема, сущности, тональность, упоминания."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collector.feeds import RawItem
from app.models import Mention, MonitoringObject, Publication, Source
from app.nlp.ner import extract_entities
from app.nlp.objects import ObjectMatcher
from app.nlp.sentiment import analyze_sentiment
from app.nlp.text import clean_text, parse_document
from app.nlp.topics import classify_topic


def load_matchers(session: Session) -> list[ObjectMatcher]:
    return [ObjectMatcher.from_model(item) for item in session.scalars(select(MonitoringObject)).all()]


def known_urls(session: Session) -> set[str]:
    return set(session.scalars(select(Publication.url)).all())


def find_mentions(title: str, text: str, matchers: list[ObjectMatcher]) -> list[tuple[ObjectMatcher, object]]:
    document = parse_document(title, text)
    return [(matcher, stats) for matcher in matchers if (stats := matcher.match(document)).total]


def has_mention(title: str, text: str, matchers: list[ObjectMatcher]) -> bool:
    return bool(find_mentions(title, text, matchers))


def ingest_item(
    session: Session,
    source: Source,
    item: RawItem,
    matchers: list[ObjectMatcher],
    external_id: str | None = None,
    is_synthetic: bool = False,
) -> Publication | None:
    """Сохраняет публикацию, если в ней упомянут хотя бы один объект мониторинга."""
    title, text = clean_text(item.title), clean_text(item.text)
    document = parse_document(title, text)
    mentions = [(matcher, matcher.match(document)) for matcher in matchers]
    mentions = [(matcher, stats) for matcher, stats in mentions if stats.total]
    if not mentions:
        return None

    topic, topic_score = classify_topic(title, text)
    tone = analyze_sentiment(document)
    publication = Publication(
        source_id=source.id,
        external_id=external_id,
        url=item.url,
        title=title,
        text=text,
        published_at=item.published_at,
        is_synthetic=is_synthetic,
        topic=topic,
        topic_score=topic_score,
        entities=extract_entities(title, text),
        tone=tone.label,
        tone_score=tone.score,
    )
    publication.mentions = [
        Mention(object_id=matcher.object_id, strong_count=stats.strong, weak_count=stats.weak)
        for matcher, stats in mentions
    ]
    session.add(publication)
    session.flush()
    return publication


def index_object_mentions(session: Session, item: MonitoringObject) -> int:
    """Новый объект мониторинга должен сразу находиться и в уже собранных публикациях."""
    matcher = ObjectMatcher.from_model(item)
    added = 0
    for publication in session.scalars(select(Publication)).all():
        stats = matcher.match(parse_document(publication.title, publication.text))
        if stats.total:
            session.add(
                Mention(
                    publication_id=publication.id,
                    object_id=item.id,
                    strong_count=stats.strong,
                    weak_count=stats.weak,
                )
            )
            added += 1
    return added
