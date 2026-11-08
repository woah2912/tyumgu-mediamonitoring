"""Служебные экраны: отладка сбора, проверка адреса и просмотр баз данных."""
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import JSON, String, Text, cast, func, or_, select

from app import seed
from app.collector.inspect import inspect_url
from app.collector.service import execute_run, start_run
from app.db import PublicationsBase, ReportsBase, publications_engine, publications_session, reports_engine
from app.models import CollectionEvent, CollectionRun
from app.web.pages import _render

router = APIRouter(include_in_schema=False)

ROWS_PER_PAGE = 50
CELL_LIMIT = 140
EVENTS_LIMIT = 400
DATABASES = {
    "publications": ("База публикаций", PublicationsBase.metadata, publications_engine),
    "reports": ("База отчётов", ReportsBase.metadata, reports_engine),
}


# ------------------------------------------------------------------ отладка сбора


@router.get("/debug", response_class=HTMLResponse)
def debug_page(request: Request, run: int | None = None):
    with publications_session() as session:
        runs = session.scalars(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(15)).all()
        selected = run or (runs[0].id if runs else None)
        return _render(request, "debug.html", active="debug", runs=runs, selected=selected)


@router.post("/debug/collect")
def debug_collect(background: BackgroundTasks):
    run_id, is_new = start_run("manual")
    if is_new:
        background.add_task(execute_run, run_id)
    return RedirectResponse(f"/debug?run={run_id}", status_code=303)


@router.get("/api/debug/runs/{run_id}/events")
def run_events(run_id: int, after: int = 0):
    with publications_session() as session:
        run = session.get(CollectionRun, run_id)
        if run is None:
            raise HTTPException(404, "Запуск не найден")
        events = session.scalars(
            select(CollectionEvent)
            .where(CollectionEvent.run_id == run_id, CollectionEvent.id > after)
            .order_by(CollectionEvent.id)
            .limit(EVENTS_LIMIT)
        ).all()
        counts = dict(
            session.execute(
                select(CollectionEvent.stage, func.count()).where(CollectionEvent.run_id == run_id).group_by(CollectionEvent.stage)
            ).all()
        )
        return {
            "running": run.finished_at is None,
            "counts": counts,
            "events": [
                {
                    "id": event.id,
                    "at": event.at.strftime("%H:%M:%S"),
                    "source": event.source_name,
                    "stage": event.stage,
                    "message": event.message,
                    "title": event.title,
                    "url": event.url,
                    "details": event.details,
                }
                for event in events
            ],
        }


@router.post("/api/debug/inspect")
def inspect(url: str = Form(...)):
    inspection = inspect_url(url.strip())
    return {"url": inspection.url, "steps": inspection.steps, "items": inspection.items}


# ------------------------------------------------------------------ просмотр баз данных


def _table(database: str, table: str):
    if database not in DATABASES or table not in DATABASES[database][1].tables:
        raise HTTPException(404, "Таблица не найдена")
    title, metadata, engine = DATABASES[database]
    return title, metadata.tables[table], engine


def _show(value, limit: int | None = CELL_LIMIT) -> str:
    if value is None:
        return "—"
    if isinstance(value, bytes):
        return f"двоичные данные, {len(value) / 1024:.0f} КБ"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M:%S")
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value)
    return text if limit is None or len(text) <= limit else text[:limit] + "…"


def _file_size(engine) -> str:
    path = engine.url.database
    if not path or not Path(path).exists():
        return ""
    return f"{Path(path).stat().st_size / 1024:.0f} КБ"


@router.get("/db", response_class=HTMLResponse)
def databases_page(request: Request, message: str = ""):
    overview = []
    for key, (title, metadata, engine) in DATABASES.items():
        with engine.connect() as connection:
            tables = [
                (name, connection.execute(select(func.count()).select_from(table)).scalar())
                for name, table in sorted(metadata.tables.items())
            ]
        overview.append({"key": key, "title": title, "path": engine.url.database, "size": _file_size(engine), "tables": tables})
    return _render(request, "db.html", active="db", overview=overview, message=message)


@router.get("/db/{database}/{table}", response_class=HTMLResponse)
def table_page(request: Request, database: str, table: str, page: int = 1, q: str = ""):
    title, model, engine = _table(database, table)
    statement = select(model)
    if q:
        searchable = [column for column in model.columns if isinstance(column.type, (String, Text, JSON))]
        statement = statement.where(or_(*(cast(column, String).like(f"%{q}%") for column in searchable)))
    key = list(model.primary_key.columns)[0]
    with engine.connect() as connection:
        total = connection.execute(select(func.count()).select_from(statement.subquery())).scalar()
        pages = max(1, (total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)
        page = max(1, min(page, pages))
        rows = connection.execute(
            statement.order_by(key.desc()).offset((page - 1) * ROWS_PER_PAGE).limit(ROWS_PER_PAGE)
        ).mappings().all()
    columns = [column.name for column in model.columns]
    return _render(
        request, "db_table.html", active="db", database=database, database_title=title, table=table,
        columns=columns, key=key.name, total=total, page=page, pages=pages, q=q,
        rows=[{"key": row[key.name], "cells": [_show(row[name]) for name in columns]} for row in rows],
    )


@router.get("/db/{database}/{table}/{row_id}", response_class=HTMLResponse)
def row_page(request: Request, database: str, table: str, row_id: int):
    title, model, engine = _table(database, table)
    key = list(model.primary_key.columns)[0]
    with engine.connect() as connection:
        row = connection.execute(select(model).where(key == row_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "Запись не найдена")
    fields = [(column.name, str(column.type), _show(row[column.name], limit=None)) for column in model.columns]
    return _render(
        request, "db_row.html", active="db", database=database, database_title=title, table=table, row_id=row_id, fields=fields
    )


@router.post("/db/demo/load")
def load_demo():
    added = seed.seed(with_synthetic=True)
    return RedirectResponse(f"/db?message=Загружено тестовых публикаций: {added}", status_code=303)


@router.post("/db/demo/delete")
def delete_demo():
    removed = seed.remove_synthetic()
    return RedirectResponse(f"/db?message=Удалено тестовых публикаций: {removed}", status_code=303)
