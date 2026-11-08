"""Запуск системы одной командой: python run.py

При первом запуске создаёт виртуальное окружение и ставит зависимости. Сразу после
старта система собирает публикации из реальных источников. Флаг --demo добавляет
100 синтетических новостей для демонстрации.

На Windows окружение лежит в %LOCALAPPDATA%, а не в папке проекта: иначе OneDrive
начинает синхронизировать тысячи служебных файлов. В Docker зависимости уже
установлены в образ, поэтому там окружение не создаётся (MM_SKIP_VENV=1).
"""
import logging
import os
import subprocess
import sys
import threading
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = os.getenv("MM_HOST", "127.0.0.1")
PORT = int(os.getenv("MM_PORT", "8000"))
MIN_PYTHON = (3, 12)


def venv_dir() -> Path:
    local = os.getenv("LOCALAPPDATA")
    return Path(local) / "tyumgu-mediamonitoring" / "venv" if os.name == "nt" and local else ROOT / ".venv"


def venv_python() -> Path:
    return venv_dir() / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_environment() -> None:
    python = venv_python()
    marker = venv_dir() / ".requirements-installed"
    requirements = ROOT / "requirements.txt"
    if not python.exists():
        print("Создаю виртуальное окружение…")
        venv.create(venv_dir(), with_pip=True)
    if not marker.exists() or marker.read_bytes() != requirements.read_bytes():
        print("Устанавливаю зависимости, первый раз это занимает несколько минут…")
        subprocess.check_call([str(python), "-m", "pip", "install", "-q", "-r", str(requirements)])
        marker.write_bytes(requirements.read_bytes())


def main() -> None:
    sys.stdout.reconfigure(errors="replace")  # консоль с кодировкой без кириллицы не должна ронять запуск
    if sys.version_info < MIN_PYTHON:
        sys.exit("Нужен Python 3.12 или новее.")

    skip_venv = os.getenv("MM_SKIP_VENV") == "1"
    if not skip_venv and Path(sys.prefix).resolve() != venv_dir().resolve():
        ensure_environment()
        sys.exit(subprocess.call([str(venv_python()), str(ROOT / "run.py"), *sys.argv[1:]]))

    sys.path.insert(0, str(ROOT))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    from app import config, seed

    demo = "--demo" in sys.argv or os.getenv("MM_DEMO") == "1"
    added = seed.seed(with_synthetic=demo)
    if demo:
        print(f"Тестовый набор: добавлено публикаций {added}")
    if config.COLLECT_INTERVAL_MINUTES > 0:
        print(f"Сбор из реальных источников начнётся сразу и будет повторяться каждые {config.COLLECT_INTERVAL_MINUTES} мин.")
        print("При первом сборе скачается модель тональности (около 120 МБ). Ход сбора: страница «Отладка сбора».")

    import uvicorn

    url = f"http://{HOST}:{PORT}"
    print(f"Система запущена: {url}")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
