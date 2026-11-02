from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.collector import feeds, service
from app.db import publications_session
from app.models import CollectionRun, Publication, Source

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Лента</title>
<item><title>ТюмГУ открыл новую лабораторию</title><link>https://feed.example/1</link>
<description>Тюменский государственный университет открыл лабораторию.</description>
<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Погода на неделю</title><link>https://feed.example/2</link>
<description>В городе ожидаются дожди.</description></item>
</channel></rss>""".encode("utf-8")

PAGE = '<html><head><link rel="alternate" type="application/rss+xml" href="/rss.xml"></head><body>Сайт</body></html>'


def response(content: bytes, url: str = "https://feed.example/rss.xml"):
    return SimpleNamespace(content=content, text=content.decode("utf-8"), url=url)


@pytest.fixture
def source_id():
    with publications_session() as session:
        source = Source(name="Тестовая лента", feed_url=f"https://feed.example/{id(session)}", level="local")
        session.add(source)
        session.flush()
        yield_id = source.id
    return yield_id


def test_parse_feed_reads_fields_and_strips_html():
    items = feeds.parse_feed(FEED)
    assert len(items) == 2
    assert items[0].title == "ТюмГУ открыл новую лабораторию"
    assert items[0].published_at.year == 2026


def test_html_entities_are_removed_from_feed_text():
    feed = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Лента</title>
    <item><title>ТюмГУ&amp;nbsp;открыл центр</title><link>https://feed.example/e</link>
    <description>&lt;a href="https://x.example"&gt;ТюмГУ&lt;/a&gt;&amp;nbsp;открыл центр</description></item>
    </channel></rss>""".encode("utf-8")
    item = feeds.parse_feed(feed)[0]
    assert item.title == "ТюмГУ открыл центр"
    assert item.text == "ТюмГУ открыл центр"


def test_find_feed_url_discovers_link_on_page(monkeypatch):
    pages = {
        "https://site.example": response(PAGE.encode("utf-8"), "https://site.example"),
        "https://site.example/rss.xml": response(FEED, "https://site.example/rss.xml"),
    }
    monkeypatch.setattr(feeds, "fetch", lambda url: pages[url])
    assert feeds.find_feed_url("https://site.example") == "https://site.example/rss.xml"


def test_page_without_feed_is_reported(monkeypatch):
    monkeypatch.setattr(feeds, "fetch", lambda url: response(b"<html>no feed</html>", url))
    with pytest.raises(feeds.CollectorError):
        feeds.find_feed_url("https://site.example")


def test_only_http_addresses_are_allowed():
    with pytest.raises(feeds.CollectorError):
        feeds.fetch("file:///etc/passwd")


def test_collect_saves_only_mentions_and_skips_known(monkeypatch, source_id):
    monkeypatch.setattr(feeds, "fetch", lambda url: response(FEED))
    monkeypatch.setattr(feeds, "fetch_article_text", lambda url: None)

    first = service.collect_source(source_id)
    second = service.collect_source(source_id)

    assert (first.seen, first.added) == (2, 1)
    assert second.added == 0
    with publications_session() as session:
        saved = session.scalar(select(Publication).where(Publication.url == "https://feed.example/1"))
        assert saved.mentions and saved.topic and saved.entities


def test_aggregator_item_belongs_to_real_publisher(monkeypatch, source_id):
    feed = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Агрегатор</title>
    <item><title>ТюмГУ получил грант - Тюменская линия</title><link>https://news.example/a</link>
    <description>ТюмГУ получил грант Тюменская линия</description>
    <source url="https://t.example">Тюменская линия</source></item>
    <item><title>ТюмГУ вошёл в рейтинг - ТАСС</title><link>https://news.example/b</link>
    <source url="https://tass.example">ТАСС</source></item>
    </channel></rss>""".encode("utf-8")
    monkeypatch.setattr(feeds, "fetch", lambda url: response(feed))
    monkeypatch.setattr(feeds, "fetch_article_text", lambda url: None)

    assert service.collect_source(source_id).added == 2

    with publications_session() as session:
        regional = session.scalar(select(Publication).where(Publication.url == "https://news.example/a"))
        assert regional.title == "ТюмГУ получил грант"
        assert regional.source.name == "Тюменская линия"
        assert regional.source.level == "regional" and regional.source.parent_id == source_id
        federal = session.scalar(select(Publication).where(Publication.url == "https://news.example/b"))
        assert federal.source.level == "federal"


def test_failed_source_does_not_stop_collection(monkeypatch):
    def broken(url):
        raise feeds.CollectorError("Источник недоступен")

    monkeypatch.setattr(feeds, "fetch", broken)
    with publications_session() as session:
        before = session.scalar(select(func.count(CollectionRun.id)))
    run = service.collect_all("manual")
    assert run.finished_at is not None and run.items_added == 0
    assert len(run.errors) == run.sources_total > 0
    with publications_session() as session:
        assert session.scalar(select(func.count(CollectionRun.id))) == before + 1
