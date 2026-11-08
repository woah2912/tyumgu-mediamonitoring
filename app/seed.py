"""Начальное наполнение: объекты мониторинга, реальные ленты, синтетические новости."""
import json
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import config, rules
from app.collector.feeds import RawItem
from app.db import init_db, publications_session
from app.models import Mention, MonitoringObject, Publication, Source
from app.pipeline.ingest import ingest_item, load_matchers

_UNIVERSITY_ALIASES = ["ТюмГУ", "Тюменский государственный университет", "Тюменский госуниверситет", "UTMN"]
RECTOR_NOTE = "Добавьте в названия фамилию действующего ректора."

OBJECTS = [
    {
        "name": "ТюмГУ",
        "kind": "Организация",
        "aliases": _UNIVERSITY_ALIASES,
        "weak_aliases": ["тюменский вуз", "тюменский университет", "вуз Тюмени", "университет в Тюмени"],
        "references": ["университет", "вуз"],
        "other_organizations": [
            "ТИУ", "Тюменский индустриальный университет", "индустриальный университет",
            "ТюмГМУ", "Тюменский медицинский университет", "медицинский университет",
            "Томский государственный университет", "Томский университет", "ТГУ",
            "ГАУ Северного Зауралья", "ТГИК", "Тюменский институт культуры",
        ],
    },
    {
        "name": "Ректор ТюмГУ",
        "kind": "Персона",
        "aliases": ["ректор ТюмГУ", "ректор Тюменского государственного университета"],
        "references": ["ректор"],
        "note": RECTOR_NOTE,
    },
    {
        "name": "Школа перспективных исследований",
        "kind": "Подразделение",
        "aliases": ["Школа перспективных исследований", "SAS ТюмГУ", "School of Advanced Studies"],
        "references": ["школа"],
    },
    {
        "name": "Программа «Приоритет 2030»",
        "kind": "Проект",
        "aliases": ["Приоритет 2030", "Приоритет-2030"],
    },
    {
        "name": "Кампус ТюмГУ",
        "kind": "Проект",
        "aliases": ["кампус ТюмГУ", "межвузовский кампус", "кампус в Тюмени"],
        "references": ["кампус", "стройка"],
    },
]

REAL_FEEDS = [
    ("Google Новости: ТюмГУ", "https://news.google.com", "https://news.google.com/rss/search?q=%D0%A2%D1%8E%D0%BC%D0%93%D0%A3&hl=ru&gl=RU&ceid=RU:ru", "Агрегатор", "federal"),
    ("Google Новости: Тюменский госуниверситет", "https://news.google.com", "https://news.google.com/rss/search?q=%22%D0%A2%D1%8E%D0%BC%D0%B5%D0%BD%D1%81%D0%BA%D0%B8%D0%B9%20%D0%B3%D0%BE%D1%81%D1%83%D0%B4%D0%B0%D1%80%D1%81%D1%82%D0%B2%D0%B5%D0%BD%D0%BD%D1%8B%D0%B9%20%D1%83%D0%BD%D0%B8%D0%B2%D0%B5%D1%80%D1%81%D0%B8%D1%82%D0%B5%D1%82%22&hl=ru&gl=RU&ceid=RU:ru", "Агрегатор", "federal"),
    ("ТАСС", "https://tass.ru", "https://tass.ru/rss/v2.xml", "Информагентство", "federal"),
    ("РИА Новости", "https://ria.ru", "https://ria.ru/export/rss2/archive/index.xml", "Информагентство", "federal"),
    ("Интерфакс", "https://www.interfax.ru", "https://www.interfax.ru/rss.asp", "Информагентство", "federal"),
    ("URA.RU", "https://ura.news", "https://ura.news/rss", "Онлайн-СМИ", "regional"),
    ("72.ru", "https://72.ru", "https://72.ru/rss-feeds/rss.xml", "Онлайн-СМИ", "regional"),
]


def seed_objects(session: Session) -> None:
    for item in OBJECTS:
        exists = session.scalar(select(MonitoringObject).where(MonitoringObject.name == item["name"]))
        if exists is None:
            session.add(MonitoringObject(**item))


def seed_real_feeds(session: Session) -> None:
    for name, url, feed_url, media_type, level in REAL_FEEDS:
        if session.scalar(select(Source).where(Source.feed_url == feed_url)) is None:
            session.add(
                Source(
                    name=name, url=url, feed_url=feed_url, media_type=media_type,
                    level=level, authority=rules.LEVEL_AUTHORITY[level],
                )
            )


# Вымышленный ректор тестовых новостей: в рабочей базе его быть не должно.
DEMO_RECTOR = "Рябинин"


def load_synthetic_news(session: Session) -> int:
    """Загружает тестовый набор через тот же конвейер, что и настоящие публикации."""
    dataset = json.loads(config.SYNTHETIC_NEWS_PATH.read_text(encoding="utf-8"))
    rector = session.scalar(select(MonitoringObject).where(MonitoringObject.name == "Ректор ТюмГУ"))
    if rector is not None and DEMO_RECTOR not in rector.aliases:
        rector.aliases = [*rector.aliases, DEMO_RECTOR]
        session.flush()
    sources: dict[str, Source] = {}
    for key, entry in dataset["sources"].items():
        source = session.scalar(select(Source).where(Source.name == entry["name"]))
        if source is None:
            source = Source(
                name=entry["name"], url=entry["url"], media_type=entry["media_type"], level=entry["level"],
                authority=rules.LEVEL_AUTHORITY[entry["level"]], is_synthetic=True,
            )
            session.add(source)
            session.flush()
        sources[key] = source

    known = set(session.scalars(select(Publication.external_id).where(Publication.external_id.is_not(None))).all())
    matchers = load_matchers(session)
    added = 0
    for entry in dataset["publications"]:
        if entry["id"] in known:
            continue
        item = RawItem(
            title=entry["title"],
            text=entry["text"],
            url=f"{entry['url']}",
            published_at=datetime.fromisoformat(entry["published_at"]),
        )
        if ingest_item(session, sources[entry["source"]], item, matchers, entry["id"], is_synthetic=True):
            added += 1
    return added


def remove_synthetic() -> int:
    """Убирает тестовый набор из базы публикаций. Отчёты не трогает: в них свой снимок."""
    with publications_session() as session:
        ids = session.scalars(select(Publication.id).where(Publication.is_synthetic)).all()
        session.execute(delete(Mention).where(Mention.publication_id.in_(ids)))
        session.execute(delete(Publication).where(Publication.id.in_(ids)))
        session.execute(delete(Source).where(Source.is_synthetic))
        rector = session.scalar(select(MonitoringObject).where(MonitoringObject.name == "Ректор ТюмГУ"))
        if rector is not None and DEMO_RECTOR in rector.aliases:
            rector.aliases = [alias for alias in rector.aliases if alias != DEMO_RECTOR]
            if DEMO_RECTOR in rector.note:  # подсказка из ранних версий говорила о тестовой персоне
                rector.note = RECTOR_NOTE
        return len(ids)


def seed(with_synthetic: bool = False) -> int:
    init_db()
    with publications_session() as session:
        seed_objects(session)
        seed_real_feeds(session)
    with publications_session() as session:
        if with_synthetic:
            return load_synthetic_news(session)
    return 0
