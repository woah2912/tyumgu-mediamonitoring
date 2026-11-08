"""Таблицы обеих баз.

База публикаций хранит источники, объекты мониторинга и размеченные публикации.
База отчётов не ссылается на неё внешними ключами: отчёт содержит снимок выборки
и остаётся корректным, даже если публикации позже изменятся.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import PublicationsBase, ReportsBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- publications.db


class Source(PublicationsBase):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(500), default="")
    feed_url: Mapped[str | None] = mapped_column(String(800), unique=True, nullable=True)
    # Издание, найденное через агрегатор: в форме его заменяет сам агрегатор.
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    media_type: Mapped[str] = mapped_column(String(60), default="Онлайн-СМИ")
    level: Mapped[str] = mapped_column(String(20), default="local")
    authority: Mapped[float] = mapped_column(Float, default=0.3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    publications: Mapped[list["Publication"]] = relationship(back_populates="source", foreign_keys="Publication.source_id")


class MonitoringObject(PublicationsBase):
    __tablename__ = "monitoring_objects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(40), default="Организация")
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    weak_aliases: Mapped[list] = mapped_column(JSON, default=list)
    references: Mapped[list] = mapped_column(JSON, default=list)
    other_organizations: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(String(300), default="")


class Publication(PublicationsBase):
    __tablename__ = "publications"
    __table_args__ = (Index("ix_publications_published_at", "published_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    # Результаты обработки при сборе.
    topic: Mapped[str] = mapped_column(String(30), default="other")
    topic_score: Mapped[float] = mapped_column(Float, default=0.0)
    entities: Mapped[list] = mapped_column(JSON, default=list)
    tone: Mapped[str] = mapped_column(String(10), default="neutral")
    tone_score: Mapped[float] = mapped_column(Float, default=0.0)

    source: Mapped[Source] = relationship(back_populates="publications")
    mentions: Mapped[list["Mention"]] = relationship(back_populates="publication", cascade="all, delete-orphan")


class Mention(PublicationsBase):
    """Индекс упоминаний: какой объект в какой публикации встречается."""

    __tablename__ = "mentions"
    __table_args__ = (Index("ix_mentions_object", "object_id", "publication_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"))
    object_id: Mapped[int] = mapped_column(ForeignKey("monitoring_objects.id"))
    strong_count: Mapped[int] = mapped_column(Integer, default=0)
    weak_count: Mapped[int] = mapped_column(Integer, default=0)

    publication: Mapped[Publication] = relationship(back_populates="mentions")


class CollectionRun(PublicationsBase):
    """Журнал запусков модуля сбора."""

    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sources_total: Mapped[int] = mapped_column(Integer, default=0)
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_added: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)


class CollectionEvent(PublicationsBase):
    """Журнал отладки: что модуль сбора увидел на каждом шаге."""

    __tablename__ = "collection_events"
    __table_args__ = (Index("ix_collection_events_run", "run_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("collection_runs.id"), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_name: Mapped[str] = mapped_column(String(200), default="")
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # fetch, parse, skip, match, article, saved, error, done
    stage: Mapped[str] = mapped_column(String(12))
    message: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------- reports.db


class Report(ReportsBase):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    object_id: Mapped[int] = mapped_column(Integer)
    object_name: Mapped[str] = mapped_column(String(200))
    context_code: Mapped[str] = mapped_column(String(30))
    context_name: Mapped[str] = mapped_column(String(120))
    context_keywords: Mapped[str] = mapped_column(String(300), default="")
    date_from: Mapped[datetime] = mapped_column(DateTime)
    date_to: Mapped[datetime] = mapped_column(DateTime)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    # processing → ready → exported; failed при ошибке обработки.
    status: Mapped[str] = mapped_column(String(20), default="processing")
    steps: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    clusters: Mapped[list] = mapped_column(JSON, default=list)
    methods: Mapped[dict] = mapped_column(JSON, default=dict)
    has_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Поле удалённого раздела руководства. В старых базах оно обязательное,
    # поэтому остаётся в модели, иначе отчёты в них перестанут сохраняться.
    review_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    publications: Mapped[list["ReportPublication"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    documents: Mapped[list["ReportDocument"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class ReportPublication(ReportsBase):
    """Снимок публикации в отчёте вместе с её разметкой."""

    __tablename__ = "report_publications"
    __table_args__ = (Index("ix_report_publications_report", "report_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"))
    publication_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000))
    published_at: Mapped[datetime] = mapped_column(DateTime)
    source_name: Mapped[str] = mapped_column(String(200))
    source_level: Mapped[str] = mapped_column(String(20))
    source_authority: Mapped[float] = mapped_column(Float)
    media_type: Mapped[str] = mapped_column(String(60))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    topic: Mapped[str] = mapped_column(String(30))
    entities: Mapped[list] = mapped_column(JSON, default=list)
    sentiment: Mapped[str] = mapped_column(String(10))
    sentiment_score: Mapped[float] = mapped_column(Float)
    sentiment_evidence: Mapped[list] = mapped_column(JSON, default=list)
    role: Mapped[str] = mapped_column(String(12))
    main_entity: Mapped[str] = mapped_column(String(200), default="")
    # relevant — остаётся в отчёте; duplicate / random — удалена системой.
    status: Mapped[str] = mapped_column(String(10), default="relevant")
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    removal_reason: Mapped[str] = mapped_column(String(300), default="")
    duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reprints: Mapped[int] = mapped_column(Integer, default=0)
    cluster: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reputation_weight: Mapped[int] = mapped_column(Integer, default=0)

    report: Mapped[Report] = relationship(back_populates="publications")


class ReportDocument(ReportsBase):
    """Сформированные файлы отчёта хранятся в самой базе."""

    __tablename__ = "report_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"))
    format: Mapped[str] = mapped_column(String(10))
    filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    report: Mapped[Report] = relationship(back_populates="documents")
