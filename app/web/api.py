"""JSON-интерфейс: статус обработки и данные для динамических блоков страниц."""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app import rules
from app.collector.service import last_run
from app.db import reports_session
from app.models import Report, ReportPublication
from app.nlp.topics import TOPIC_NAMES

router = APIRouter(prefix="/api", tags=["api"])

EXCERPT_LENGTH = 320


def _load_report(session, report_id: int) -> Report:
    report = session.get(Report, report_id)
    if report is None:
        raise HTTPException(404, "Отчёт не найден")
    return report


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/reports/{report_id}/status")
def report_status(report_id: int) -> dict:
    with reports_session() as session:
        report = _load_report(session, report_id)
        return {"status": report.status, "steps": report.steps, "error": report.error}


@router.get("/reports/{report_id}/metrics")
def report_metrics(report_id: int) -> dict:
    with reports_session() as session:
        report = _load_report(session, report_id)
        return {"metrics": report.metrics, "clusters": report.clusters}


@router.get("/reports/{report_id}/publications")
def report_publications(report_id: int) -> list[dict]:
    with reports_session() as session:
        _load_report(session, report_id)
        items = session.scalars(
            select(ReportPublication)
            .where(ReportPublication.report_id == report_id)
            .order_by(ReportPublication.published_at.desc())
        ).all()
        return [
            {
                "id": item.id,
                "title": item.title,
                "excerpt": item.text[:EXCERPT_LENGTH],
                "url": item.url,
                "date": item.published_at.strftime("%d.%m.%Y"),
                "source": item.source_name,
                "level": rules.LEVEL_LABELS.get(item.source_level, item.source_level),
                "is_synthetic": item.is_synthetic,
                "topic": TOPIC_NAMES.get(item.topic, item.topic),
                "sentiment": item.sentiment,
                "sentiment_label": rules.SENTIMENT_LABELS[item.sentiment],
                "score": item.sentiment_score,
                "evidence": item.sentiment_evidence,
                "role": rules.ROLE_LABELS[item.role],
                "main_entity": item.main_entity,
                "cluster": item.cluster,
                "status": item.status,
                "relevance": item.relevance_score,
                "reason": item.removal_reason,
                "reprints": item.reprints,
                "weight": item.reputation_weight,
            }
            for item in items
        ]


@router.get("/collector/status")
def collector_status() -> dict:
    return last_run()
