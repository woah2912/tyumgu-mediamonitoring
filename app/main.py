"""Точка входа веб-приложения."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.collector.service import close_interrupted_runs, collection_loop
from app.db import init_db
from app.web import admin, api, pages


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    close_interrupted_runs()
    task = asyncio.create_task(collection_loop())
    yield
    task.cancel()


app = FastAPI(title="Медиамониторинг ТюмГУ", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(api.router)
app.include_router(pages.router)
app.include_router(admin.router)
