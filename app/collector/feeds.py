"""Получение публикаций из RSS/Atom-лент и извлечение полного текста статей."""
import calendar
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
import trafilatura

from app import config
from app.models import utcnow
from app.nlp.text import clean_text

MIN_ARTICLE_LENGTH = 200
_FEED_TYPES = {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}
# Страницы этих агрегаторов не содержат текста статьи.
_NO_FULL_TEXT_HOSTS = {"news.google.com"}


class CollectorError(Exception):
    """Источник недоступен или не содержит ленту."""


@dataclass
class RawItem:
    title: str
    text: str
    url: str
    published_at: datetime
    publisher: str | None = None  # настоящее издание, если лента — агрегатор


def fetch(url: str) -> httpx.Response:
    if urlparse(url).scheme not in {"http", "https"}:
        raise CollectorError("Адрес должен начинаться с http:// или https://")
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise CollectorError(f"Источник недоступен: {error}") from error
    return response


def _published(entry) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc).replace(tzinfo=None)
    return utcnow()


def parse_feed(content: bytes) -> list[RawItem]:
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        title = clean_text(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        text = clean_text(entry.get("summary", "") or entry.get("description", ""))
        publisher = clean_text(entry.get("source", {}).get("title", "")) or None
        if publisher:
            # Агрегатор дописывает издание к заголовку и тексту: «Новость - Издание».
            title = title.removesuffix(f" - {publisher}")
            text = text.removesuffix(publisher).strip()
        items.append(RawItem(title=title, text=text, url=link, published_at=_published(entry), publisher=publisher))
    return items


class _FeedLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "link" and "alternate" in (data.get("rel") or "") and data.get("type") in _FEED_TYPES and data.get("href"):
            self.links.append(data["href"])


def feed_links(html: str, base_url: str) -> list[str]:
    """Ссылки на ленты, объявленные в заголовке HTML-страницы."""
    parser = _FeedLinkParser()
    parser.feed(html)
    return [urljoin(base_url, link) for link in parser.links]


def find_feed_url(url: str) -> str:
    """Адрес может быть лентой или страницей сайта со ссылкой на ленту."""
    response = fetch(url)
    if feedparser.parse(response.content).entries:
        return str(response.url)
    for candidate in feed_links(response.text, str(response.url)):
        if feedparser.parse(fetch(candidate).content).entries:
            return candidate
    raise CollectorError("На странице не найдена RSS- или Atom-лента")


def describe_response(response) -> dict:
    """Что ответил сервер: для журнала отладки."""
    elapsed = getattr(response, "elapsed", None)
    headers = getattr(response, "headers", {}) or {}
    return {
        "url": str(getattr(response, "url", "")),
        "status": getattr(response, "status_code", 200),
        "bytes": len(response.content),
        "ms": round(elapsed.total_seconds() * 1000) if elapsed else None,
        "content_type": headers.get("content-type", ""),
    }


def fetch_article_text(url: str) -> str | None:
    if urlparse(url).hostname in _NO_FULL_TEXT_HOSTS:
        return None
    try:
        text = trafilatura.extract(fetch(url).text, include_comments=False, include_tables=False)
    except CollectorError:
        return None
    return text if text and len(text) >= MIN_ARTICLE_LENGTH else None
