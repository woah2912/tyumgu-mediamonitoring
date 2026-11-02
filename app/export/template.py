"""Шаблон документа отчёта: содержание описано блоками, а DOCX и PDF только их отрисовывают."""
from dataclasses import dataclass

from app import metrics as metrics_module
from app import rules
from app.export import charts
from app.nlp.ner import ENTITY_LABELS
from app.nlp.topics import TOPIC_NAMES

SYNTHETIC_NOTE = (
    "Выборка содержит синтетические тестовые публикации. Издания, персоны и события в них вымышлены, "
    "поэтому показатели нельзя использовать для реальных управленческих выводов."
)


@dataclass
class Heading:
    text: str


@dataclass
class Paragraph:
    text: str
    warning: bool = False


@dataclass
class Bullets:
    items: list[str]


@dataclass
class Image:
    data: bytes
    caption: str


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    widths: list[float]  # доли ширины страницы


def date(value) -> str:
    return value.strftime("%d.%m.%Y")


def _methodology() -> list[str]:
    return [
        "Тональность: сумма словарной оценки и оценки модели, шкала от −1 до +1. "
        f"Позитив — от {rules.SENTIMENT_POSITIVE_FROM}, негатив — до {rules.SENTIMENT_NEGATIVE_TO}.",
        "Индекс тональности = (позитив − негатив) / все публикации × 100.",
        "Медиаиндекс = сумма по публикациям: авторитет источника × вес роли × вес тональности.",
        "Репутационный вес негативного упоминания (0–100) учитывает авторитет источника, роль объекта, "
        f"силу негатива и число перепечаток. Влиятельным считается вес от {rules.INFLUENTIAL_FROM}.",
        "Релевантность: балльная оценка значимости объекта в тексте с порогом "
        f"{rules.RELEVANCE_THRESHOLD}; анонсы, ориентиры на местности и упоминания других организаций получают штраф.",
    ]


def build_blocks(report, items) -> list:
    data = report.metrics
    kept = [item for item in items if item.status == "relevant"]
    removed = [item for item in items if item.status != "relevant"]
    negative = sorted((item for item in kept if item.sentiment == "negative"), key=lambda item: -item.reputation_weight)

    blocks: list = []
    if report.has_synthetic:
        blocks.append(Paragraph(SYNTHETIC_NOTE, warning=True))

    blocks.append(Heading("Параметры запроса"))
    blocks.append(
        Table(
            ["Параметр", "Значение"],
            [
                ["Объект мониторинга", report.object_name],
                ["Контекст", report.context_name + (f" (ключевые слова: {report.context_keywords})" if report.context_keywords else "")],
                ["Период", f"{date(report.date_from)} – {date(report.date_to)}"],
                ["Источники с публикациями", str(len(report.sources))],
                ["Оценка тональности", report.methods.get("sentiment", "")],
            ],
            [0.3, 0.7],
        )
    )

    blocks.append(Heading("Выводы"))
    blocks.append(Bullets(metrics_module.build_conclusions(data, report.object_name)))

    blocks.append(Heading("Ключевые показатели"))
    sentiment = data["sentiment"]
    blocks.append(
        Table(
            ["Показатель", "Значение"],
            [
                ["Найдено публикаций", str(data["found"])],
                ["В отчёте после очистки", str(data["kept"])],
                ["Удалено дубликатов", str(data["removed_duplicates"])],
                ["Удалено случайных публикаций", str(data["removed_random"])],
                ["Позитив / нейтрально / негатив", f"{sentiment['positive']} / {sentiment['neutral']} / {sentiment['negative']}"],
                ["Индекс тональности", f"{data['tone_index']:+.1f}"],
                ["Медиаиндекс", f"{data['media_index']:.1f}"],
                ["Доля главной роли", f"{data['main_role_share']:.1f}%"],
                ["Влиятельные негативные упоминания", str(data["influential"])],
            ],
            [0.6, 0.4],
        )
    )

    blocks.append(Heading("Динамика упоминаний"))
    step = "по неделям" if data["timeline"]["step"] == "week" else "по дням"
    blocks.append(Image(charts.timeline_chart(data), f"Рисунок 1. Число публикаций {step} с разбивкой по тональности"))

    blocks.append(Heading("Тематика"))
    blocks.append(Image(charts.topics_chart(data), "Рисунок 2. Публикации по темам"))
    if report.clusters:
        blocks.append(
            Table(
                ["Кластер", "Ключевые слова", "Публикаций", "Негатив"],
                [
                    [cluster["name"], ", ".join(cluster["terms"]), str(cluster["size"]), str(cluster.get("negative", 0))]
                    for cluster in report.clusters
                ],
                [0.28, 0.42, 0.17, 0.13],
            )
        )

    blocks.append(Heading("Источники"))
    blocks.append(Image(charts.sources_chart(data), "Рисунок 3. Источники с наибольшим числом публикаций"))
    blocks.append(
        Table(
            ["Уровень источника", "Публикаций", "Негатив"],
            [[row["name"], str(row["count"]), str(row["negative"])] for row in data["levels"]],
            [0.5, 0.25, 0.25],
        )
    )

    blocks.append(Heading("Роль объекта и упоминаемые сущности"))
    blocks.append(
        Table(
            ["Роль объекта", "Публикаций"],
            [[row["name"], str(row["count"])] for row in data["roles"]],
            [0.7, 0.3],
        )
    )
    rows = [
        [ENTITY_LABELS.get(kind, kind), ", ".join(f"{entry['name']} ({entry['count']})" for entry in entries[:6])]
        for kind, entries in sorted(data["entities"].items())
    ]
    if rows:
        blocks.append(Table(["Тип", "Чаще всего упоминаются"], rows, [0.2, 0.8]))

    blocks.append(Heading("Негативные упоминания"))
    if negative:
        blocks.append(Paragraph("Список отсортирован по системной оценке репутационного веса. Итоговое решение принимает руководство."))
        blocks.append(
            Table(
                ["Дата", "Источник", "Публикация", "Роль", "Вес"],
                [
                    [date(item.published_at), item.source_name, item.title, rules.ROLE_LABELS[item.role], str(item.reputation_weight)]
                    for item in negative
                ],
                [0.11, 0.23, 0.44, 0.14, 0.08],
            )
        )
    else:
        blocks.append(Paragraph("Негативных упоминаний в очищенной выборке нет."))

    blocks.append(Heading("Удалённые публикации"))
    if removed:
        blocks.append(
            Table(
                ["Публикация", "Источник", "Причина удаления"],
                [[item.title, item.source_name, item.removal_reason] for item in removed],
                [0.42, 0.22, 0.36],
            )
        )
    else:
        blocks.append(Paragraph("Система не удаляла публикации из выборки."))

    blocks.append(Heading("Публикации в отчёте"))
    blocks.append(
        Table(
            ["Дата", "Источник", "Заголовок", "Тема", "Тональность"],
            [
                [
                    date(item.published_at),
                    item.source_name,
                    item.title,
                    TOPIC_NAMES.get(item.topic, item.topic),
                    rules.SENTIMENT_LABELS[item.sentiment],
                ]
                for item in sorted(kept, key=lambda item: item.published_at)
            ],
            [0.11, 0.21, 0.4, 0.16, 0.12],
        )
    )

    blocks.append(Heading("Методика"))
    blocks.append(Bullets(_methodology()))
    return blocks
