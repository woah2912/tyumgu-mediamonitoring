"""Настройки приложения. Любое значение переопределяется переменной окружения."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("MM_DATA_DIR", BASE_DIR / "data"))

# Две независимые базы: публикации и отчёты (требование заказчика).
PUBLICATIONS_DB_URL = os.getenv("MM_PUBLICATIONS_DB", f"sqlite:///{DATA_DIR / 'publications.db'}")
REPORTS_DB_URL = os.getenv("MM_REPORTS_DB", f"sqlite:///{DATA_DIR / 'reports.db'}")

SYNTHETIC_NEWS_PATH = BASE_DIR / "data" / "synthetic_news.json"

# Период автоматического сбора из источников, минуты. 0 — только ручной запуск.
COLLECT_INTERVAL_MINUTES = int(os.getenv("MM_COLLECT_INTERVAL_MINUTES", "60"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("MM_HTTP_TIMEOUT_SECONDS", "15"))
USER_AGENT = "TyumGU-MediaMonitoring/1.0 (university student project)"

# Нейросетевая часть тональности. Без модели система работает на словаре.
SENTIMENT_MODEL = os.getenv("MM_SENTIMENT_MODEL", "seara/rubert-tiny2-russian-sentiment")
USE_TRANSFORMER = os.getenv("MM_USE_TRANSFORMER", "1") == "1"
