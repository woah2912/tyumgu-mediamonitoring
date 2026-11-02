"""Таблицы отчёта в формате XLSX: данные для дальнейшего анализа."""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app import rules
from app.nlp.topics import TOPIC_NAMES

_HEADER_FILL = PatternFill("solid", fgColor="E8EFF8")


def _sheet(book: Workbook, title: str, header: list[str], rows: list[list], widths: list[int]) -> None:
    sheet = book.create_sheet(title)
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = _HEADER_FILL
    for row in rows:
        sheet.append(row)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"
    if rows:
        sheet.auto_filter.ref = sheet.dimensions


def render_xlsx(report, items) -> bytes:
    data = report.metrics
    book = Workbook()
    book.remove(book.active)

    sentiment = data["sentiment"]
    summary = [
        ["Отчёт", report.title],
        ["Объект", report.object_name],
        ["Контекст", report.context_name],
        ["Период с", report.date_from.date()],
        ["Период по", report.date_to.date()],
        ["Найдено публикаций", data["found"]],
        ["В отчёте после очистки", data["kept"]],
        ["Удалено дубликатов", data["removed_duplicates"]],
        ["Удалено случайных", data["removed_random"]],
        ["Позитив", sentiment["positive"]],
        ["Нейтрально", sentiment["neutral"]],
        ["Негатив", sentiment["negative"]],
        ["Индекс тональности", data["tone_index"]],
        ["Медиаиндекс", data["media_index"]],
        ["Доля главной роли, %", data["main_role_share"]],
        ["Влиятельные негативные упоминания", data["influential"]],
    ]
    if report.has_synthetic:
        summary.append(["Внимание", "Выборка содержит синтетические тестовые публикации"])
    _sheet(book, "Сводка", ["Показатель", "Значение"], summary, [38, 70])

    def row(item) -> list:
        return [
            item.published_at.date(),
            item.source_name,
            rules.LEVEL_LABELS.get(item.source_level, item.source_level),
            item.title,
            TOPIC_NAMES.get(item.topic, item.topic),
            f"Кластер {item.cluster + 1}" if item.cluster is not None else "",
            rules.SENTIMENT_LABELS[item.sentiment],
            item.sentiment_score,
            rules.ROLE_LABELS[item.role],
            item.main_entity,
            item.relevance_score,
            item.url,
        ]

    columns = ["Дата", "Источник", "Уровень", "Заголовок", "Тема", "Кластер", "Тональность", "Оценка", "Роль", "Главный объект", "Релевантность", "Ссылка"]
    column_widths = [12, 30, 14, 60, 26, 11, 13, 9, 15, 24, 13, 40]

    kept = [item for item in items if item.status == "relevant"]
    _sheet(book, "Публикации", columns, [row(item) for item in kept], column_widths)

    negative = sorted((item for item in kept if item.sentiment == "negative"), key=lambda item: -item.reputation_weight)
    _sheet(
        book,
        "Негатив",
        ["Вес", *columns],
        [[item.reputation_weight, *row(item)] for item in negative],
        [7, *column_widths],
    )

    removed = [item for item in items if item.status != "relevant"]
    _sheet(
        book,
        "Удалённые",
        ["Дата", "Источник", "Заголовок", "Причина", "Ссылка"],
        [[item.published_at.date(), item.source_name, item.title, item.removal_reason, item.url] for item in removed],
        [12, 30, 60, 60, 40],
    )

    _sheet(
        book,
        "Кластеры",
        ["Кластер", "Тема", "Ключевые слова", "Публикаций", "Позитив", "Негатив", "Пример"],
        [
            [cluster["id"] + 1, cluster["name"], ", ".join(cluster["terms"]), cluster["size"], cluster.get("positive", 0), cluster.get("negative", 0), cluster["example"]]
            for cluster in report.clusters
        ],
        [10, 30, 50, 12, 10, 10, 60],
    )

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
