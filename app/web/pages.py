"""Страницы системы. Дорожки BPMN: сотрудник — новый отчёт, руководство — раздел проверки."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import joinedload

from app import metrics as metrics_module
from app import rules
from app.collector import feeds
from app.collector.service import collect_custom, execute_run, last_run, register_custom_source, start_run
from app.db import publications_session, reports_session
from app.export.service import export_report
from app.models import (
    CollectionRun,
    Mention,
    MentionReview,
    MonitoringObject,
    Publication,
    Report,
    ReportDocument,
    ReportPublication,
    Source,
    utcnow,
)
from app.nlp.ner import ENTITY_LABELS
from app.nlp.topics import TOPIC_NAMES
from app.pipeline.ingest import index_object_mentions
from app.pipeline.report import ALL_CONTEXTS, ReportRequest, context_name, finish_report, mark_step, start_report

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

PAGE_SIZE = 25
DEFAULT_PERIOD_DAYS = 90
STATUS_LABELS = {
    "processing": "Обрабатывается",
    "ready": "Готов к экспорту",
    "exported": "Ждёт анализа руководства",
    "closed": "Процесс завершён",
    "failed": "Ошибка",
}


def _date(value: datetime | None, pattern: str = "%d.%m.%Y") -> str:
    return value.strftime(pattern) if value else "—"


templates.env.filters["date"] = _date
templates.env.filters["datetime"] = lambda value: _date(value, "%d.%m.%Y %H:%M")
templates.env.filters["filesize"] = lambda size: f"{size / 1024:.0f} КБ" if size < 1_048_576 else f"{size / 1_048_576:.1f} МБ"
templates.env.globals.update(
    STATUS_LABELS=STATUS_LABELS,
    TOPIC_NAMES=TOPIC_NAMES,
    SENTIMENT_LABELS=rules.SENTIMENT_LABELS,
    ROLE_LABELS=rules.ROLE_LABELS,
    LEVEL_LABELS=rules.LEVEL_LABELS,
    ENTITY_LABELS=ENTITY_LABELS,
    rules=rules,
)


def _render(request: Request, name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context)


def _form_context(session) -> dict:
    sources = session.scalars(
        select(Source).where(Source.is_active, Source.parent_id.is_(None)).order_by(Source.authority.desc(), Source.name)
    ).all()
    today = date.today()
    return {
        "objects": session.scalars(select(MonitoringObject).order_by(MonitoringObject.id)).all(),
        "contexts": {ALL_CONTEXTS: context_name(ALL_CONTEXTS), **TOPIC_NAMES},
        "groups": [(rules.LEVEL_LABELS[level], [item for item in sources if item.level == level]) for level in rules.LEVEL_LABELS],
        "default_from": (today - timedelta(days=DEFAULT_PERIOD_DAYS)).isoformat(),
        "default_to": today.isoformat(),
        "today": today.isoformat(),
    }


@router.get("/", response_class=HTMLResponse)
def new_report_page(request: Request):
    with publications_session() as session:
        return _render(request, "new_report.html", active="new", **_form_context(session))


def _add_custom_sources(raw: str) -> tuple[list[int], list[str]]:
    """Добавляет свои источники сотрудника и сразу собирает из них публикации."""
    source_ids, warnings = [], []
    for url in (line.strip() for line in raw.splitlines()):
        if not url:
            continue
        try:
            source_id, _ = register_custom_source(url)
        except feeds.CollectorError as error:
            warnings.append(f"{url}: {error}")
            continue
        result = collect_custom(source_id)
        if result.error:
            warnings.append(f"{url}: {result.error}")
        source_ids.append(source_id)
    return source_ids, warnings


@router.post("/reports")
def create_report(
    request: Request,
    background: BackgroundTasks,
    object_id: int = Form(...),
    context_code: str = Form(ALL_CONTEXTS),
    context_keywords: str = Form(""),
    date_from: date = Form(...),
    date_to: date = Form(...),
    source_ids: list[int] = Form(default=[]),
    custom_sources: str = Form(""),
):
    custom_ids, warnings = _add_custom_sources(custom_sources)
    selected = source_ids + custom_ids

    def form_with(message: str, status_code: int = 200):
        with publications_session() as session:
            page = _render(
                request, "new_report.html", active="new", message=message, warnings=warnings,
                submitted={"object_id": object_id, "context_code": context_code, "context_keywords": context_keywords,
                           "date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "source_ids": selected,
                           "custom_sources": custom_sources},
                **_form_context(session),
            )
        page.status_code = status_code
        return page

    if date_from > date_to:
        return form_with("Дата начала периода позже даты окончания.", 422)
    if not selected:
        return form_with("Выберите хотя бы один источник.", 422)

    report_id = start_report(
        ReportRequest(
            object_id=object_id,
            context_code=context_code,
            date_from=datetime.combine(date_from, datetime.min.time()),
            date_to=datetime.combine(date_to, datetime.min.time()),
            source_ids=selected,
            context_keywords=context_keywords.strip(),
        )
    )
    if report_id is None:
        return form_with("Данные не найдены: по заданным объекту, контексту, периоду и источникам публикаций нет.")

    background.add_task(finish_report, report_id)
    return RedirectResponse(f"/reports/{report_id}", status_code=303)


@router.get("/reports", response_class=HTMLResponse)
def reports_archive(request: Request, status: str = ""):
    with reports_session() as session:
        statement = select(Report).order_by(Report.created_at.desc())
        if status:
            statement = statement.where(Report.status == status)
        reports = session.scalars(statement).all()
        return _render(request, "reports.html", active="reports", reports=reports, status=status)


def _get_report(session, report_id: int) -> Report:
    report = session.get(Report, report_id)
    if report is None:
        raise HTTPException(404, "Отчёт не найден")
    return report


@router.get("/reports/{report_id}", response_class=HTMLResponse)
def report_page(request: Request, report_id: int):
    with reports_session() as session:
        report = _get_report(session, report_id)
        conclusions = metrics_module.build_conclusions(report.metrics, report.object_name) if report.metrics else []
        return _render(
            request, "report.html", active="reports", report=report, conclusions=conclusions,
            documents=list(report.documents), payload=json.dumps({"metrics": report.metrics}, ensure_ascii=False),
        )


@router.post("/reports/{report_id}/export")
def export_action(report_id: int):
    with reports_session() as session:
        report = _get_report(session, report_id)
        if report.status not in {"ready", "exported", "closed"}:
            raise HTTPException(409, "Отчёт ещё обрабатывается")
    export_report(report_id)
    return RedirectResponse(f"/reports/{report_id}#documents", status_code=303)


@router.get("/reports/{report_id}/documents/{document_id}")
def download_document(report_id: int, document_id: int, inline: bool = False):
    with reports_session() as session:
        document = session.get(ReportDocument, document_id)
        if document is None or document.report_id != report_id:
            raise HTTPException(404, "Документ не найден")
        disposition = "inline" if inline else "attachment"
        return Response(
            document.content,
            media_type=document.mime,
            headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(document.filename)}"},
        )


# ------------------------------------------------------------------ руководство


@router.get("/review", response_class=HTMLResponse)
def review_queue(request: Request):
    with reports_session() as session:
        waiting = session.scalars(select(Report).where(Report.status == "exported").order_by(Report.exported_at.desc())).all()
        closed = session.scalars(select(Report).where(Report.status == "closed").order_by(Report.closed_at.desc())).all()
        return _render(request, "review_queue.html", active="review", waiting=waiting, closed=closed)


@router.get("/reports/{report_id}/review", response_class=HTMLResponse)
def review_page(request: Request, report_id: int):
    with reports_session() as session:
        report = _get_report(session, report_id)
        if report.status not in {"exported", "closed"}:
            return RedirectResponse(f"/reports/{report_id}", status_code=303)
        negative = session.scalars(
            select(ReportPublication)
            .options(joinedload(ReportPublication.review))
            .where(
                ReportPublication.report_id == report_id,
                ReportPublication.status == "relevant",
                ReportPublication.sentiment == "negative",
            )
            .order_by(ReportPublication.reputation_weight.desc())
        ).all()
        return _render(
            request, "review.html", active="review", report=report, negative=negative, documents=list(report.documents)
        )


@router.post("/reports/{report_id}/review")
async def save_review(request: Request, report_id: int):
    form = await request.form()
    with reports_session() as session:
        report = _get_report(session, report_id)
        if report.status != "exported":
            raise HTTPException(409, "Отчёт не ожидает анализа руководства")
        negative = session.scalars(
            select(ReportPublication).where(
                ReportPublication.report_id == report_id,
                ReportPublication.status == "relevant",
                ReportPublication.sentiment == "negative",
            )
        ).all()

        reacted = 0
        for item in negative:
            weight = max(0, min(100, int(form.get(f"weight_{item.id}", item.reputation_weight))))
            influential = form.get(f"influential_{item.id}") == "yes"
            reaction = str(form.get(f"reaction_{item.id}", "")).strip() if influential else ""
            session.add(
                MentionReview(report_publication_id=item.id, weight=weight, is_influential=influential, reaction=reaction)
            )
            reacted += 1 if reaction else 0

        influential_count = sum(1 for item in negative if form.get(f"influential_{item.id}") == "yes")
        report.review_summary = str(form.get("summary", "")).strip()
        report.status = "closed"
        report.closed_at = utcnow()
        mark_step(report, "review", "done", "Документ проанализирован")
        if negative:
            mark_step(report, "weight", "done", f"Оценено упоминаний: {len(negative)}, влиятельных: {influential_count}")
            mark_step(report, "react", "done" if influential_count else "skipped",
                      f"Реакций: {reacted}" if influential_count else "Влиятельных упоминаний нет")
        else:
            mark_step(report, "weight", "skipped", "Негативных упоминаний нет")
            mark_step(report, "react", "skipped", "Негативных упоминаний нет")
    return RedirectResponse(f"/reports/{report_id}/review", status_code=303)


# ------------------------------------------------------------------ база публикаций


@router.get("/publications", response_class=HTMLResponse)
def publications_page(
    request: Request,
    q: str = "",
    topic: str = "",
    tone: str = "",
    source: int | None = Query(None),
    object_id: int | None = Query(None),
    page: int = 1,
):
    with publications_session() as session:
        statement = select(Publication).options(joinedload(Publication.source))
        if q:
            pattern = f"%{q}%"
            statement = statement.where(or_(Publication.title.like(pattern), Publication.text.like(pattern)))
        if topic:
            statement = statement.where(Publication.topic == topic)
        if tone:
            statement = statement.where(Publication.tone == tone)
        if source:
            statement = statement.where(Publication.source_id == source)
        if object_id:
            statement = statement.join(Mention).where(Mention.object_id == object_id)

        total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, pages))
        rows = session.scalars(
            statement.order_by(Publication.published_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
        ).unique().all()
        return _render(
            request, "publications.html", active="publications", rows=rows, total=total, page=page, pages=pages,
            q=q, topic=topic, tone=tone, source=source, object_id=object_id,
            sources=session.scalars(select(Source).order_by(Source.name)).all(),
            objects=session.scalars(select(MonitoringObject).order_by(MonitoringObject.id)).all(),
        )


@router.get("/publications/{publication_id}", response_class=HTMLResponse)
def publication_page(request: Request, publication_id: int):
    with publications_session() as session:
        publication = session.scalar(
            select(Publication).options(joinedload(Publication.source)).where(Publication.id == publication_id)
        )
        if publication is None:
            raise HTTPException(404, "Публикация не найдена")
        object_ids = [mention.object_id for mention in publication.mentions]
        objects = session.scalars(select(MonitoringObject).where(MonitoringObject.id.in_(object_ids))).all()
        return _render(request, "publication.html", active="publications", item=publication, objects=objects)


# ------------------------------------------------------------------ справочники


@router.get("/sources", response_class=HTMLResponse)
def sources_page(request: Request, error: str = ""):
    with publications_session() as session:
        rows = session.execute(
            select(Source, func.count(Publication.id))
            .outerjoin(Publication, Publication.source_id == Source.id)
            .group_by(Source.id)
            .order_by(Source.is_synthetic, Source.authority.desc(), Source.name)
        ).all()
        runs = session.scalars(select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(5)).all()
        return _render(request, "sources.html", active="sources", rows=rows, runs=runs, error=error, running=last_run()["running"])


@router.post("/sources")
def add_source(name: str = Form(""), url: str = Form(...)):
    try:
        source_id, _ = register_custom_source(url, name)
    except feeds.CollectorError as error:
        return RedirectResponse(f"/sources?error={quote(str(error))}", status_code=303)
    collect_custom(source_id)
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/collect")
def run_collection(background: BackgroundTasks):
    run_id, is_new = start_run("manual")
    if is_new:
        background.add_task(execute_run, run_id)
    return RedirectResponse(f"/debug?run={run_id}", status_code=303)


@router.post("/sources/{source_id}/toggle")
def toggle_source(source_id: int):
    with publications_session() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise HTTPException(404, "Источник не найден")
        source.is_active = not source.is_active
    return RedirectResponse("/sources", status_code=303)


@router.get("/objects", response_class=HTMLResponse)
def objects_page(request: Request):
    with publications_session() as session:
        rows = session.execute(
            select(MonitoringObject, func.count(Mention.id))
            .outerjoin(Mention, Mention.object_id == MonitoringObject.id)
            .group_by(MonitoringObject.id)
            .order_by(MonitoringObject.id)
        ).all()
        return _render(request, "objects.html", active="objects", rows=rows)


def _split(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


@router.post("/objects")
def add_object(
    name: str = Form(...),
    kind: str = Form("Организация"),
    aliases: str = Form(...),
    weak_aliases: str = Form(""),
    other_organizations: str = Form(""),
):
    with publications_session() as session:
        if session.scalar(select(MonitoringObject).where(MonitoringObject.name == name.strip())) is None:
            item = MonitoringObject(
                name=name.strip(),
                kind=kind,
                aliases=_split(aliases),
                weak_aliases=_split(weak_aliases),
                other_organizations=_split(other_organizations),
            )
            session.add(item)
            session.flush()
            index_object_mentions(session, item)
    return RedirectResponse("/objects", status_code=303)


@router.post("/objects/{object_id}")
def edit_object(
    object_id: int,
    aliases: str = Form(...),
    weak_aliases: str = Form(""),
    other_organizations: str = Form(""),
):
    """Новые названия сразу применяются и к уже собранным публикациям."""
    with publications_session() as session:
        item = session.get(MonitoringObject, object_id)
        if item is None:
            raise HTTPException(404, "Объект не найден")
        item.aliases = _split(aliases)
        item.weak_aliases = _split(weak_aliases)
        item.other_organizations = _split(other_organizations)
        item.note = ""
        session.execute(delete(Mention).where(Mention.object_id == object_id))
        index_object_mentions(session, item)
    return RedirectResponse("/objects", status_code=303)


@router.get("/method", response_class=HTMLResponse)
def method_page(request: Request):
    return _render(request, "method.html", active="method")
