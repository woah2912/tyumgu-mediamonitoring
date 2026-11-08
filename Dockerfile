# Образ системы медиамониторинга ТюмГУ.
# Сборка и запуск: docker compose up -d --build
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/huggingface \
    MM_SKIP_VENV=1 \
    MM_HOST=0.0.0.0 \
    MM_PORT=8000 \
    MM_DATA_DIR=/data

WORKDIR /app

# Зависимости ставятся отдельным слоем: при правке кода они не переустанавливаются.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Модель тональности скачивается при сборке, чтобы на демонстрации не ждать загрузки.
RUN python -c "from transformers import pipeline; pipeline('text-classification', model='seara/rubert-tiny2-russian-sentiment')"

COPY run.py .
COPY app ./app
COPY data/synthetic_news.json ./data/synthetic_news.json

# Приложение работает не от root; базы лежат в томе /data и переживают пересборку образа.
RUN useradd --create-home mediamonitoring \
    && mkdir -p /data \
    && chown -R mediamonitoring /data /opt/huggingface
USER mediamonitoring
ENV HF_HUB_OFFLINE=1
VOLUME /data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["python", "run.py", "--no-browser"]
