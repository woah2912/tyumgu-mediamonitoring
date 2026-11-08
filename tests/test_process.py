"""Сквозной сценарий BPMN TO-BE через веб-интерфейс."""
import io
import json
import re

import docx
import openpyxl
import pytest
from sqlalchemy import select

from app import config
from app.collector import feeds
from app.db import publications_session, reports_session
from app.models import MonitoringObject, Report, ReportDocument, ReportPublication, Source


def form_data(**overrides) -> dict:
    with publications_session() as session:
        object_id = session.scalar(select(MonitoringObject.id).where(MonitoringObject.name == "ТюмГУ"))
        source_ids = session.scalars(select(Source.id).where(Source.is_synthetic)).all()
    return {
        "object_id": object_id,
        "context_code": "all",
        "date_from": "2026-08-01",
        "date_to": "2026-11-02",
        "source_ids": source_ids,
        **overrides,
    }


def create_report(client, **overrides) -> int:
    response = client.post("/reports", data=form_data(**overrides), follow_redirects=False)
    assert response.status_code == 303
    return int(re.search(r"/reports/(\d+)$", response.headers["location"]).group(1))


@pytest.fixture(scope="module")
def report_id(client):
    return create_report(client)


def steps_of(report: Report) -> dict:
    return {step["code"]: step for step in report.steps}


def test_dataset_has_100_marked_synthetic_publications():
    data = json.loads(config.SYNTHETIC_NEWS_PATH.read_text(encoding="utf-8"))
    assert len(data["publications"]) == 100
    assert len({item["id"] for item in data["publications"]}) == 100
    assert all(item["url"].split("/")[2].endswith(".example") for item in data["publications"])


def test_no_data_shows_message_and_creates_no_report(client):
    with reports_session() as session:
        before = len(session.scalars(select(Report.id)).all())
    response = client.post("/reports", data=form_data(date_from="2020-01-01", date_to="2020-02-01"))
    assert response.status_code == 200
    assert "Данные не найдены" in response.text
    with reports_session() as session:
        assert len(session.scalars(select(Report.id)).all()) == before


def test_wrong_period_is_rejected(client):
    response = client.post("/reports", data=form_data(date_from="2026-10-01", date_to="2026-09-01"))
    assert response.status_code == 422


def test_report_runs_whole_system_lane(report_id):
    with reports_session() as session:
        report = session.get(Report, report_id)
        steps = steps_of(report)
        assert report.status == "ready"
        for code in ["query", "sentiment", "role", "redirect", "relevance", "duplicates", "random", "analytics"]:
            assert steps[code]["status"] == "done", code
        assert steps["export"]["status"] == "pending"


def test_selection_is_cleaned_to_match_labels(report_id):
    data = json.loads(config.SYNTHETIC_NEWS_PATH.read_text(encoding="utf-8"))
    expected = {item["url"]: item["labels"]["relevance"] for item in data["publications"]}
    with reports_session() as session:
        items = session.scalars(select(ReportPublication).where(ReportPublication.report_id == report_id)).all()
        assert len(items) == 100
        assert all(item.status == expected[item.url] for item in items)
        removed = [item for item in items if item.status != "relevant"]
        assert all(item.removal_reason for item in removed)


def test_report_metrics_and_clusters(report_id):
    with reports_session() as session:
        report = session.get(Report, report_id)
        data = report.metrics
        assert data["kept"] == 75 and data["removed_duplicates"] == 12 and data["removed_random"] == 13
        assert sum(data["sentiment"].values()) == data["kept"]
        assert sum(point["positive"] + point["neutral"] + point["negative"] for point in data["timeline"]["points"]) == data["kept"]
        assert len(report.clusters) >= 2
        assert sum(cluster["size"] for cluster in report.clusters) == data["kept"]
        assert all(cluster["terms"] for cluster in report.clusters)


def test_negative_mentions_get_reputation_weight(report_id):
    with reports_session() as session:
        items = session.scalars(
            select(ReportPublication).where(
                ReportPublication.report_id == report_id,
                ReportPublication.status == "relevant",
                ReportPublication.sentiment == "negative",
            )
        ).all()
        assert items and all(item.reputation_weight > 0 for item in items)
        assert max(item.reprints for item in items) >= 2


def test_report_page_and_api(client, report_id):
    assert "Экспортировать отчёт" in client.get(f"/reports/{report_id}").text
    assert client.get(f"/api/reports/{report_id}/status").json()["status"] == "ready"
    rows = client.get(f"/api/reports/{report_id}/publications").json()
    assert len(rows) == 100 and {"title", "sentiment", "topic", "role", "status"} <= set(rows[0])


def test_export_saves_documents_into_reports_database(client, report_id):
    response = client.post(f"/reports/{report_id}/export", follow_redirects=False)
    assert response.status_code == 303

    with reports_session() as session:
        report = session.get(Report, report_id)
        documents = {item.format: item for item in report.documents}
        assert report.status == "exported"
        assert set(documents) == {"docx", "pdf", "xlsx"}
        assert steps_of(report)["document"]["status"] == "done"
        ids = {name: item.id for name, item in documents.items()}

    assert (config.DATA_DIR / "reports.db").exists() and (config.DATA_DIR / "publications.db").exists()

    pdf = client.get(f"/reports/{report_id}/documents/{ids['pdf']}")
    assert pdf.content.startswith(b"%PDF")
    assert "attachment" in pdf.headers["content-disposition"]

    word = docx.Document(io.BytesIO(client.get(f"/reports/{report_id}/documents/{ids['docx']}").content))
    assert len(word.inline_shapes) == 3
    assert any("Выводы" in item.text for item in word.paragraphs)

    book = openpyxl.load_workbook(io.BytesIO(client.get(f"/reports/{report_id}/documents/{ids['xlsx']}").content))
    assert book["Публикации"].max_row == 76
    assert book["Удалённые"].max_row == 26


def test_second_export_replaces_files(client, report_id):
    client.post(f"/reports/{report_id}/export")
    with reports_session() as session:
        assert len(session.scalars(select(ReportDocument).where(ReportDocument.report_id == report_id)).all()) == 3


def test_document_of_other_report_is_not_served(client, report_id):
    with reports_session() as session:
        document_id = session.scalar(select(ReportDocument.id).where(ReportDocument.report_id == report_id))
    assert client.get(f"/reports/{report_id + 1000}/documents/{document_id}").status_code == 404


def test_context_and_keywords_narrow_selection(client):
    report_id = create_report(client, context_code="all", context_keywords="общежитие")
    with reports_session() as session:
        titles = session.scalars(select(ReportPublication.title).where(ReportPublication.report_id == report_id)).all()
    assert titles and len(titles) < 20
    assert any("общежити" in title.lower() for title in titles)


def test_other_object_gets_its_own_selection(client):
    with publications_session() as session:
        rector = session.scalar(select(MonitoringObject.id).where(MonitoringObject.name == "Ректор ТюмГУ"))
    report_id = create_report(client, object_id=rector)
    with reports_session() as session:
        report = session.get(Report, report_id)
        assert report.object_name == "Ректор ТюмГУ" and report.status == "ready"
        assert report.metrics["found"] < 40


def test_custom_source_is_collected_for_report(client, monkeypatch):
    feed = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Свой</title>
    <item><title>ТюмГУ провёл конференцию</title><link>https://own.example/1</link>
    <description>Тюменский государственный университет провёл конференцию.</description>
    <pubDate>Sat, 03 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>""".encode("utf-8")
    fake = type("Page", (), {"content": feed, "text": feed.decode("utf-8"), "url": "https://own.example/rss"})
    monkeypatch.setattr(feeds, "fetch", lambda url: fake)
    monkeypatch.setattr(feeds, "fetch_article_text", lambda url: None)

    data = form_data(source_ids=[], custom_sources="https://own.example/rss")
    response = client.post("/reports", data=data, follow_redirects=False)
    assert response.status_code == 303

    with publications_session() as session:
        assert session.scalar(select(Source).where(Source.feed_url == "https://own.example/rss")).is_custom


def test_aggregator_selection_includes_its_publishers(client):
    with publications_session() as session:
        aggregator = Source(name="Агрегатор", feed_url="https://aggregator.example/rss", level="federal")
        session.add(aggregator)
        session.flush()
        aggregator_id = aggregator.id
        child = session.scalar(select(Source).where(Source.name == "Газета «Тюменский меридиан»"))
        child.parent_id = aggregator_id

    report_id = create_report(client, source_ids=[aggregator_id])
    with reports_session() as session:
        report = session.get(Report, report_id)
        assert report.sources == ["Газета «Тюменский меридиан»"]

    with publications_session() as session:
        session.scalar(select(Source).where(Source.name == "Газета «Тюменский меридиан»")).parent_id = None


def test_unreachable_custom_source_is_reported(client, monkeypatch):
    def broken(url):
        raise feeds.CollectorError("Источник недоступен")

    monkeypatch.setattr(feeds, "fetch", broken)
    response = client.post("/reports", data=form_data(custom_sources="https://dead.example/rss", date_from="2020-01-01", date_to="2020-02-01"))
    assert "Источник недоступен" in response.text


@pytest.mark.parametrize("path", ["/", "/reports", "/publications", "/sources", "/objects", "/debug", "/db"])
def test_pages_open(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/review", "/method", "/reports/1/review"])
def test_removed_sections_are_gone(client, path):
    assert client.get(path).status_code == 404


def test_menu_has_no_removed_sections(client):
    page = client.get("/").text
    assert "Анализ отчётов" not in page and "Методика" not in page


def test_static_files_are_versioned_against_stale_cache(client):
    page = client.get("/debug").text
    assert "/static/css/app.css?v=" in page and "/static/js/debug.js?v=" in page
    assert 'href="/static/css/app.css"' not in page


def test_report_page_has_no_bpmn_tracker(client, report_id):
    page = client.get(f"/reports/{report_id}").text
    assert "Ход процесса" not in page and "BPMN" not in page


def test_report_steps_cover_employee_and_system_lanes_only(report_id):
    with reports_session() as session:
        lanes = {step["lane"] for step in session.get(Report, report_id).steps}
    assert lanes == {"system", "employee"}


def test_publications_filters(client):
    response = client.get("/publications", params={"q": "мегагрант", "tone": "positive"})
    assert "мегагрант" in response.text
    assert client.get("/publications", params={"q": "несуществующее слово"}).text.count("Ничего не найдено") == 1


def test_object_aliases_can_be_edited_and_reindexed(client):
    with publications_session() as session:
        rector = session.scalar(select(MonitoringObject).where(MonitoringObject.name == "Ректор ТюмГУ"))
        assert "Рябинин" in rector.aliases
    client.post(f"/objects/{rector.id}", data={"aliases": "ректор ТюмГУ, Голубев"})
    with publications_session() as session:
        rector = session.get(MonitoringObject, rector.id)
        assert rector.aliases == ["ректор ТюмГУ", "Голубев"]
    response = client.get("/publications", params={"object_id": rector.id})
    assert "проректор по науке" in response.text
    client.post(f"/objects/{rector.id}", data={"aliases": "ректор ТюмГУ, ректор Тюменского государственного университета, Рябинин"})


def test_new_object_is_indexed_immediately(client):
    client.post("/objects", data={"name": "Институт психологии", "kind": "Подразделение", "aliases": "Институт психологии"})
    assert "Институт психологии" in client.get("/objects").text
    with publications_session() as session:
        item = session.scalar(select(MonitoringObject).where(MonitoringObject.name == "Институт психологии"))
    response = client.get("/publications", params={"object_id": item.id})
    assert "Фестиваль студенческого творчества" in response.text
