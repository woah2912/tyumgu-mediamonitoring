"""Служебные экраны: журнал отладки сбора, проверка адреса, просмотр баз."""
from types import SimpleNamespace

from sqlalchemy import func, select

from app import seed
from app.collector import feeds, service
from app.db import publications_session
from app.models import CollectionEvent, Publication, Source
from app.nlp.objects import ObjectMatcher

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Отладочная лента</title>
<item><title>Учёные Тюменского государственного университета открыли лабораторию</title><link>https://debug.example/1</link>
<description>ТюмГУ открыл лабораторию климата.</description></item>
<item><title>Погода на выходные</title><link>https://debug.example/2</link>
<description>Ожидается снег.</description></item>
</channel></rss>""".encode("utf-8")

PAGE = """<html><head><title>Новости вуза</title>
<link rel="alternate" type="application/rss+xml" href="/rss.xml"></head>
<body><article><p>Тюменский государственный университет запустил новую программу для школьников региона.
Занятия будут вести преподаватели ТюмГУ, обучение бесплатное, набор открыт до конца месяца.
Это уже третья подобная программа университета за последний год, и интерес к ней растёт.</p></article></body></html>"""


def response(content: bytes, url: str):
    return SimpleNamespace(content=content, text=content.decode("utf-8"), url=url, status_code=200, headers={"content-type": "text/xml"})


def test_find_spans_points_to_inflected_name():
    matcher = ObjectMatcher(1, "ТюмГУ", ["Тюменский государственный университет"], ["тюменский вуз"])
    text = "Учёные Тюменского государственного университета и другой тюменский вуз."
    spans = matcher.find_spans(text)
    assert [text[span["start"] : span["end"]] for span in spans] == ["Тюменского государственного университета", "тюменский вуз"]
    assert [span["strength"] for span in spans] == ["strong", "weak"]


def test_collection_run_writes_debug_trace(monkeypatch, client):
    monkeypatch.setattr(feeds, "fetch", lambda url: response(FEED, url))
    monkeypatch.setattr(feeds, "fetch_article_text", lambda url: None)
    with publications_session() as session:
        source = Source(name="Отладочная лента", feed_url="https://debug.example/rss", level="local")
        session.add(source)
        session.flush()
        source_id = source.id

    run_id, is_new = service.start_run("custom")
    assert is_new
    service.execute_run(run_id, [source_id])

    data = client.get(f"/api/debug/runs/{run_id}/events").json()
    stages = [event["stage"] for event in data["events"]]
    assert not data["running"]
    assert stages[:3] == ["fetch", "fetch", "parse"]
    assert {"match", "article", "saved", "skip", "done"} <= set(stages)

    match = next(event for event in data["events"] if event["stage"] == "match")
    assert match["url"] == "https://debug.example/1"
    assert match["details"]["objects"][0]["name"] == "ТюмГУ"
    assert any(fragment["match"] == "Тюменского государственного университета" for fragment in match["details"]["fragments"])

    later = client.get(f"/api/debug/runs/{run_id}/events", params={"after": data["events"][-1]["id"]}).json()
    assert later["events"] == []
    assert client.get(f"/debug?run={run_id}").status_code == 200


def test_full_collection_is_not_started_twice(monkeypatch):
    first, is_new = service.start_run("manual")
    second, second_is_new = service.start_run("schedule")
    assert is_new and not second_is_new and second == first
    service.execute_run(first, [])


def test_inspect_explains_page_and_its_feed(monkeypatch, client):
    pages = {
        "https://site.example/news": response(PAGE.encode("utf-8"), "https://site.example/news"),
        "https://site.example/rss.xml": response(FEED, "https://site.example/rss.xml"),
    }
    monkeypatch.setattr(feeds, "fetch", lambda url: pages[url])
    monkeypatch.setattr(feeds, "fetch_article_text", lambda url: None)
    with publications_session() as session:
        before = session.scalar(select(func.count(Publication.id)))

    data = client.post("/api/debug/inspect", data={"url": "https://site.example/news"}).json()

    messages = " ".join(step["message"] for step in data["steps"])
    assert "веб-страница" in messages and "объявлена лента" in messages
    found = [item for item in data["items"] if item["found"]]
    assert len(found) == 2 and len(data["items"]) == 3
    assert found[0]["fragments"] and found[0]["topic"] and found[0]["tone"]
    with publications_session() as session:
        assert session.scalar(select(func.count(Publication.id))) == before


def test_inspect_reports_unreachable_address(monkeypatch, client):
    def broken(url):
        raise feeds.CollectorError("Источник недоступен")

    monkeypatch.setattr(feeds, "fetch", broken)
    data = client.post("/api/debug/inspect", data={"url": "https://dead.example"}).json()
    assert data["steps"][-1]["stage"] == "error" and data["items"] == []


def test_database_viewer_lists_tables_and_rows(client):
    overview = client.get("/db").text
    assert "publications" in overview and "reports" in overview and "collection_events" in overview

    table = client.get("/db/publications/publications", params={"q": "мегагрант"}).text
    assert "мегагрант" in table

    with publications_session() as session:
        publication_id = session.scalar(select(Publication.id).where(Publication.title.like("%мегагрант%")))
    row = client.get(f"/db/publications/publications/{publication_id}").text
    assert "entities" in row and "мегагрант" in row

    assert client.get("/db/publications/unknown").status_code == 404
    assert client.get("/db/other/publications").status_code == 404
    assert client.get("/db/publications/publications/999999").status_code == 404


def test_demo_data_can_be_removed_and_loaded_back(client):
    with publications_session() as session:
        synthetic = session.scalar(select(func.count(Publication.id)).where(Publication.is_synthetic))
    assert synthetic == 100

    assert seed.remove_synthetic() == 100
    with publications_session() as session:
        assert not session.scalar(select(func.count(Publication.id)).where(Publication.is_synthetic))
        assert not session.scalar(select(func.count(Source.id)).where(Source.is_synthetic))

    response = client.post("/db/demo/load", follow_redirects=False)
    assert response.status_code == 303
    with publications_session() as session:
        assert session.scalar(select(func.count(Publication.id)).where(Publication.is_synthetic)) == 100


def test_interrupted_run_is_closed_on_startup():
    run_id, _ = service.start_run("manual")
    assert service.close_interrupted_runs() >= 1
    second, is_new = service.start_run("manual")
    assert is_new and second != run_id
    service.execute_run(second, [])


def test_old_debug_events_are_pruned():
    for _ in range(service.KEEP_RUNS_WITH_EVENTS + 2):
        run_id, _ = service.start_run("custom")
        with publications_session() as session:
            session.add(CollectionEvent(run_id=run_id, stage="done", message="тест"))
        service.execute_run(run_id, [])
    with publications_session() as session:
        runs_with_events = session.scalar(select(func.count(func.distinct(CollectionEvent.run_id))))
    assert runs_with_events <= service.KEEP_RUNS_WITH_EVENTS
