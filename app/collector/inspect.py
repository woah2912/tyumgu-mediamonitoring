"""Как система видит источник: проверка адреса без записи в базу и подсветка находок."""
import re
from dataclasses import dataclass, field
from html import unescape

import trafilatura

from app.collector import feeds
from app.db import publications_session
from app.models import utcnow
from app.nlp.ner import extract_entities
from app.nlp.objects import ObjectMatcher
from app.nlp.sentiment import analyze_sentiment
from app.nlp.text import clean_text, parse_document
from app.nlp.topics import TOPIC_NAMES, classify_topic
from app.pipeline.ingest import find_mentions, load_matchers

FRAGMENT_WIDTH = 70
FRAGMENT_LIMIT = 3
INSPECT_LIMIT = 40
FULL_TEXT_LIMIT = 3
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def fragments(text: str, matchers: list[ObjectMatcher]) -> list[dict]:
    """Кусочки текста вокруг найденных названий: before, match, after."""
    spans = sorted((span for matcher in matchers for span in matcher.find_spans(text)), key=lambda span: span["start"])
    result = []
    for span in spans[:FRAGMENT_LIMIT]:
        left = max(0, span["start"] - FRAGMENT_WIDTH)
        right = min(len(text), span["end"] + FRAGMENT_WIDTH)
        result.append(
            {
                "before": ("…" if left else "") + text[left : span["start"]],
                "match": text[span["start"] : span["end"]],
                "after": text[span["end"] : right] + ("…" if right < len(text) else ""),
                "strength": span["strength"],
            }
        )
    return result


def mention_evidence(title: str, text: str, mentions) -> dict:
    """Какие объекты найдены, сколько раз и где именно в тексте."""
    return {
        "objects": [
            {"name": matcher.name, "strong": stats.strong, "weak": stats.weak, "in_title": stats.in_title}
            for matcher, stats in mentions
        ],
        "fragments": fragments(title if text.strip() == title.strip() else f"{title}. {text}", [matcher for matcher, _ in mentions]),
    }


@dataclass
class Inspection:
    url: str
    steps: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)

    def step(self, stage: str, message: str, **details) -> None:
        self.steps.append({"stage": stage, "message": message, "details": details, "at": utcnow().strftime("%H:%M:%S")})


def _analyze(record: dict, title: str, text: str, mentions) -> None:
    document = parse_document(title, text)
    targets = sorted({index for _, stats in mentions for index in stats.target_sentences})
    topic, _ = classify_topic(title, text)
    tone = analyze_sentiment(document, targets or None)
    record.update(
        topic=TOPIC_NAMES.get(topic, topic),
        tone=tone.label,
        tone_score=tone.score,
        evidence=tone.evidence[:5],
        entities=[f"{entity['name']} ({entity['type']})" for entity in extract_entities(title, text)[:8]],
    )


def _page_as_item(response) -> feeds.RawItem | None:
    text = trafilatura.extract(response.text, include_comments=False, include_tables=False)
    if not text:
        return None
    title_match = _TITLE.search(response.text)
    title = clean_text(unescape(title_match.group(1))) if title_match else str(response.url)
    return feeds.RawItem(title=title, text=text, url=str(response.url), published_at=utcnow())


def inspect_url(url: str) -> Inspection:
    """Повторяет путь модуля сбора по одному адресу и объясняет каждый шаг. В базу ничего не пишет."""
    inspection = Inspection(url=url)
    inspection.step("fetch", f"Запрашиваю {url}")
    try:
        response = feeds.fetch(url)
    except feeds.CollectorError as error:
        inspection.step("error", str(error))
        return inspection
    info = feeds.describe_response(response)
    inspection.step("fetch", f"Ответ {info['status']}: {info['bytes'] // 1024} КБ за {info['ms']} мс", **info)

    items = feeds.parse_feed(response.content)
    if items:
        inspection.step("parse", f"Это лента RSS/Atom: записей {len(items)}")
    else:
        inspection.step("parse", "Это веб-страница: извлекаю текст статьи и ищу ссылку на ленту")
        page = _page_as_item(response)
        if page:
            inspection.step("article", f"Текст страницы извлечён: {len(page.text)} символов")
        links = feeds.feed_links(response.text, str(response.url))
        if links:
            inspection.step("parse", f"На странице объявлена лента: {links[0]}", feed=links[0])
            try:
                items = feeds.parse_feed(feeds.fetch(links[0]).content)
                inspection.step("parse", f"Лента загружена: записей {len(items)}")
            except feeds.CollectorError as error:
                inspection.step("error", f"Ленту загрузить не удалось: {error}")
        else:
            inspection.step("parse", "Ссылки на ленту нет: для регулярного сбора такой адрес не подойдёт")
        items = ([page] if page else []) + items

    with publications_session() as session:
        matchers = load_matchers(session)

    full_texts = 0
    for item in items[:INSPECT_LIMIT]:
        mentions = find_mentions(item.title, item.text, matchers)
        record = {"title": item.title, "url": item.url, "published": item.published_at.strftime("%d.%m.%Y %H:%M"), "found": bool(mentions)}
        if mentions and full_texts < FULL_TEXT_LIMIT and item.url != str(response.url):
            text = feeds.fetch_article_text(item.url)
            full_texts += 1
            if text:
                inspection.step("article", f"Загружен полный текст: «{item.title[:60]}», {len(text)} символов", url=item.url)
                item.text = text
                mentions = find_mentions(item.title, text, matchers) or mentions
            else:
                inspection.step("article", f"Полный текст недоступен, анализ по анонсу: «{item.title[:60]}»", url=item.url)
        if mentions:
            record.update(mention_evidence(item.title, item.text, mentions))
            _analyze(record, item.title, item.text, mentions)
        inspection.items.append(record)

    found = sum(1 for item in inspection.items if item["found"])
    skipped = max(0, len(items) - INSPECT_LIMIT)
    tail = f", ещё {skipped} не проверялись" if skipped else ""
    inspection.step("done", f"Проверено записей: {len(inspection.items)}, с упоминаниями: {found}{tail}")
    return inspection
