"""Строит UML-диаграммы системы: прецеденты, последовательности и классы.

Запуск из корня проекта: python docs/uml/build_uml.py
Результат: файлы .png и .svg рядом со скриптом.
"""
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, Polygon, Rectangle  # noqa: E402

OUTPUT = Path(__file__).parent
INK = "#1f1f1f"
MUTED = "#5a5a5a"
LINE = "#3c3c3c"
FILL = "#fdf8e6"
HEAD = "#f3e8bf"
BOUNDARY = "#7a7a7a"
FRAGMENT = "#8a8a8a"
MONO = "DejaVu Sans Mono"


class Canvas:
    def __init__(self, width, height, title, subtitle):
        self.figure, self.axis = plt.subplots(figsize=(width / 100, height / 100))
        self.axis.set_xlim(0, width)
        self.axis.set_ylim(0, height)
        self.axis.axis("off")
        self.axis.text(24, height - 20, title, fontsize=16, fontweight="bold", color=INK, va="top")
        self.axis.text(24, height - 50, subtitle, fontsize=10.5, color=MUTED, va="top")

    def text(self, x, y, value, size=9, **options):
        options.setdefault("color", INK)
        self.axis.text(x, y, value, fontsize=size, zorder=6, **options)

    def line(self, points, dashed=False, width=1.1, color=LINE, zorder=2):
        xs, ys = zip(*points)
        self.axis.plot(xs, ys, color=color, linewidth=width, linestyle=(0, (5, 3)) if dashed else "-", zorder=zorder, solid_capstyle="butt")

    def arrow(self, points, head="open", dashed=False, label="", at=0.5, offset=(0, 8), size=8.5, label_options=None):
        """Ломаная со стрелкой на конце: head = open | filled | none."""
        if len(points) > 2:
            self.line(points[:-1], dashed=dashed)
        start, end = points[-2], points[-1]
        style = {"open": "->", "filled": "-|>", "none": "-"}[head]
        self.axis.add_patch(
            FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=14, color=LINE, linewidth=1.1,
                            linestyle=(0, (5, 3)) if dashed else "-", shrinkA=0, shrinkB=0, zorder=3)
        )
        if label:
            segment = max(range(len(points) - 1), key=lambda i: abs(points[i + 1][0] - points[i][0]) + abs(points[i + 1][1] - points[i][1]))
            (x1, y1), (x2, y2) = points[segment], points[segment + 1]
            options = dict(ha="center", va="center", bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.92))
            options.update(label_options or {})
            self.text(x1 + (x2 - x1) * at + offset[0], y1 + (y2 - y1) * at + offset[1], label, size=size, **options)

    def diamond(self, point, toward, filled=True):
        """Ромб композиции на конце связи, обращённый от целого к части."""
        x, y = point
        dx, dy = toward[0] - x, toward[1] - y
        length = (dx * dx + dy * dy) ** 0.5 or 1
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        size, half = 22, 7
        shape = [(x, y), (x + ux * size / 2 + px * half, y + uy * size / 2 + py * half), (x + ux * size, y + uy * size),
                 (x + ux * size / 2 - px * half, y + uy * size / 2 - py * half)]
        self.axis.add_patch(Polygon(shape, closed=True, facecolor=LINE if filled else "white", edgecolor=LINE, linewidth=1.1, zorder=4))

    def save(self, name):
        self.figure.savefig(OUTPUT / f"{name}.png", dpi=150, facecolor="white", bbox_inches="tight", pad_inches=0.15)
        self.figure.savefig(OUTPUT / f"{name}.svg", facecolor="white", bbox_inches="tight", pad_inches=0.15)
        plt.close(self.figure)


# ------------------------------------------------------------------ прецеденты


def actor(c: Canvas, x, y, name):
    c.axis.add_patch(Circle((x, y + 58), 13, facecolor="white", edgecolor=LINE, linewidth=1.3, zorder=4))
    c.line([(x, y + 45), (x, y + 10)], width=1.3)
    c.line([(x - 22, y + 34), (x + 22, y + 34)], width=1.3)
    c.line([(x - 18, y - 16), (x, y + 10), (x + 18, y - 16)], width=1.3)
    c.text(x, y - 24, name, size=9.5, ha="center", va="top", fontweight="bold")


def use_case(c: Canvas, x, y, label, width=280, height=60):
    c.axis.add_patch(Ellipse((x, y), width, height, facecolor=FILL, edgecolor=LINE, linewidth=1.1, zorder=4))
    c.text(x, y, "\n".join(textwrap.wrap(label, 24)), size=8.8, ha="center", va="center", linespacing=1.15)
    return {"x": x, "y": y, "w": width / 2, "h": height / 2}


def edge(case, toward):
    """Точка на краю эллипса в сторону другой точки."""
    dx, dy = toward[0] - case["x"], toward[1] - case["y"]
    scale = 1 / ((dx / case["w"]) ** 2 + (dy / case["h"]) ** 2) ** 0.5
    return case["x"] + dx * scale, case["y"] + dy * scale


def relation(c: Canvas, source, target, kind):
    """«include» и «extend»: пунктир со стрелкой от базового прецедента (или расширения) к цели."""
    start = edge(source, (target["x"], target["y"]))
    end = edge(target, (source["x"], source["y"]))
    c.arrow([start, end], head="open", dashed=True, label=f"«{kind}»", size=8, offset=(0, 9))


def association(c: Canvas, point, case):
    c.line([point, edge(case, point)], width=1.1)


def use_cases() -> None:
    c = Canvas(1560, 1170, "Система медиамониторинга ТюмГУ", "UML: диаграмма прецедентов")
    c.axis.add_patch(Rectangle((300, 40), 990, 1050, facecolor="none", edgecolor=BOUNDARY, linewidth=1.3, zorder=1))
    c.text(795, 1078, "Система медиамониторинга ТюмГУ", size=11, ha="center", va="top", fontweight="bold")

    actor(c, 140, 820, "Сотрудник УСК")
    actor(c, 140, 470, "Руководство УСК")
    actor(c, 140, 160, "Администратор")
    actor(c, 1430, 320, "Планировщик\n(таймер)")
    actor(c, 1430, 120, "Источник СМИ\n(RSS, сайт)")

    report = use_case(c, 540, 920, "Сформировать отчёт")
    custom = use_case(c, 540, 995, "Добавить свой источник", 240)
    no_data = use_case(c, 540, 840, "Сообщить об отсутствии данных", 240)
    query = use_case(c, 950, 990, "Выполнить запрос к базе публикаций")
    analysis = use_case(c, 950, 915, "Оценить тональность и главную роль")
    cleaning = use_case(c, 950, 840, "Удалить дубликаты и случайные публикации")
    export = use_case(c, 540, 745, "Экспортировать отчёт")
    document = use_case(c, 950, 745, "Сформировать документ DOCX, PDF, XLSX")
    archive = use_case(c, 540, 665, "Просмотреть архив отчётов")

    review = use_case(c, 540, 520, "Проанализировать отчёт")
    weight = use_case(c, 950, 560, "Оценить репутационный вес упоминания")
    react = use_case(c, 950, 480, "Зафиксировать реакцию на влиятельное упоминание")

    manage = use_case(c, 540, 330, "Управлять источниками и объектами мониторинга")
    journal = use_case(c, 540, 250, "Просмотреть журнал отладки сбора")
    inspect = use_case(c, 540, 170, "Проверить адрес источника")
    database = use_case(c, 540, 90, "Просмотреть базы данных")
    collect = use_case(c, 950, 300, "Собрать публикации")
    markup = use_case(c, 950, 110, "Определить тему, сущности и тональность")

    for case in (report, export, archive):
        association(c, (165, 850), case)
    association(c, (165, 500), review)
    for case in (manage, journal, inspect, database):
        association(c, (165, 190), case)
    association(c, (1405, 350), collect)
    association(c, (1405, 150), collect)
    association(c, (1405, 140), inspect)

    relation(c, report, query, "include")
    relation(c, report, analysis, "include")
    relation(c, report, cleaning, "include")
    relation(c, custom, report, "extend")
    relation(c, no_data, report, "extend")
    relation(c, export, document, "include")
    relation(c, weight, review, "extend")
    relation(c, react, review, "extend")
    relation(c, collect, markup, "include")
    c.save("uml-1-usecase")


# ------------------------------------------------------------------ последовательности


class Sequence:
    def __init__(self, canvas: Canvas, participants, top, bottom):
        self.c = canvas
        self.x = {}
        self.top = top
        self.bottom = bottom
        for key, (x, label, is_actor) in participants.items():
            self.x[key] = x
            if is_actor:
                actor(canvas, x, top - 40, label)
                head_bottom = top - 92
            else:
                lines = textwrap.wrap(label, 16)
                height = 22 + 15 * len(lines)
                canvas.axis.add_patch(Rectangle((x - 78, top - height), 156, height, facecolor=HEAD, edgecolor=LINE, linewidth=1.1, zorder=4))
                canvas.text(x, top - height / 2, "\n".join(lines), size=9, ha="center", va="center", fontweight="bold", linespacing=1.15)
                head_bottom = top - height
            canvas.line([(x, head_bottom), (x, bottom)], dashed=True, width=0.9, color="#8a8a8a", zorder=1)
        self.number = 0

    def activation(self, who, y_from, y_to):
        x = self.x[who]
        self.c.axis.add_patch(Rectangle((x - 6, y_to), 12, y_from - y_to, facecolor="white", edgecolor=LINE, linewidth=1, zorder=3))

    def message(self, source, target, y, label, kind="sync", numbered=True):
        """kind: sync — вызов, reply — ответ, async — асинхронный вызов."""
        if numbered and kind != "reply":
            self.number += 1
            label = f"{self.number}. {label}"
        x1, x2 = self.x[source], self.x[target]
        shift = 6 if x2 > x1 else -6
        if source == target:
            points = [(x1 + 6, y), (x1 + 50, y), (x1 + 50, y - 22), (x1 + 6, y - 22)]
            self.c.arrow(points, head="filled", label="")
            self.c.text(x1 + 58, y - 11, label, size=8.5, va="center")
            return
        head = {"sync": "filled", "reply": "open", "async": "open"}[kind]
        self.c.arrow([(x1 + shift, y), (x2 - shift, y)], head=head, dashed=kind == "reply")
        self.c.text((x1 + x2) / 2, y + 4, label, size=8.5, ha="center", va="bottom",
                    bbox=dict(boxstyle="round,pad=0.1", facecolor="white", edgecolor="none", alpha=0.85))

    def fragment(self, x1, x2, y_top, y_bottom, operator, guard="", separators=()):
        """Комбинированный фрагмент alt / loop / opt; separators — (y, условие) для ветвей alt."""
        self.c.axis.add_patch(Rectangle((x1, y_bottom), x2 - x1, y_top - y_bottom, facecolor="none", edgecolor=FRAGMENT, linewidth=1.1, zorder=2))
        width = 12 + 8 * len(operator)
        tag = [(x1, y_top), (x1 + width, y_top), (x1 + width, y_top - 14), (x1 + width - 8, y_top - 22), (x1, y_top - 22)]
        self.c.axis.add_patch(Polygon(tag, closed=True, facecolor="white", edgecolor=FRAGMENT, linewidth=1.1, zorder=3))
        self.c.text(x1 + 6, y_top - 11, operator, size=9, va="center", fontweight="bold")
        if guard:
            self.c.text(x1 + width + 8, y_top - 11, f"[{guard}]", size=8.5, va="center", color=MUTED)
        for y, condition in separators:
            self.c.line([(x1, y), (x2, y)], dashed=True, width=1, color=FRAGMENT)
            self.c.text(x1 + 8, y - 11, f"[{condition}]", size=8.5, va="center", color=MUTED)


def sequence_report() -> None:
    c = Canvas(1860, 1560, "Формирование отчёта", "UML: диаграмма последовательности · процесс TO-BE, дорожки «Сотрудник» и «Система»")
    s = Sequence(c, {
        "user": (80, "Сотрудник УСК", True),
        "web": (270, "Веб-интерфейс", False),
        "pages": (470, "Страницы (pages.py)", False),
        "pipeline": (700, "Конвейер отчёта", False),
        "pubdb": (930, "База публикаций", False),
        "nlp": (1150, "NLP-модули", False),
        "repdb": (1380, "База отчётов", False),
        "export": (1610, "Формирование документов", False),
    }, top=1420, bottom=40)

    y = 1290
    s.message("user", "web", y, "Выбрать объект, контекст, период, источники")
    s.message("user", "web", y - 40, "Нажать «Сформировать отчёт»")
    s.message("web", "pages", y - 80, "POST /reports")
    s.activation("pages", y - 85, y - 650)
    s.message("pages", "pipeline", y - 120, "start_report(запрос)")
    s.activation("pipeline", y - 125, y - 520)
    s.message("pipeline", "pubdb", y - 160, "query_publications()")
    s.message("pubdb", "pipeline", y - 195, "публикации", kind="reply")

    s.fragment(380, 1500, y - 220, y - 600, "alt", "публикаций нет", separators=[(y - 320, "публикации найдены")])
    s.message("pipeline", "pages", y - 268, "None", kind="reply")
    s.message("pages", "web", y - 302, "«Данные не найдены»", kind="reply")

    s.fragment(560, 1300, y - 338, y - 440, "loop", "для каждой публикации")
    s.message("pipeline", "nlp", y - 385, "analyze_sentiment(документ, предложения об объекте)")
    s.message("pipeline", "nlp", y - 420, "determine_role(сущности, упоминания)")
    s.message("pipeline", "repdb", y - 465, "сохранить отчёт и снимок выборки")
    s.message("pipeline", "pages", y - 505, "report_id", kind="reply")
    s.message("pages", "web", y - 545, "303: переход на страницу отчёта", kind="reply")
    s.message("pages", "pipeline", y - 585, "finish_report() — фоновая задача", kind="async")

    s.activation("pipeline", y - 590, y - 790)
    s.message("pipeline", "nlp", y - 630, "check_relevance(), find_duplicates()")
    s.message("pipeline", "repdb", y - 670, "удалить дубликаты и случайные публикации")
    s.message("pipeline", "nlp", y - 710, "cluster_publications()")
    s.message("pipeline", "repdb", y - 750, "кластеры, метрики, статус «готов»")
    s.fragment(180, 600, y - 780, y - 885, "loop", "пока статус «обрабатывается»")
    s.message("web", "pages", y - 832, "GET /api/reports/{id}/status")
    s.message("pages", "web", y - 864, "шаги процесса", kind="reply")

    s.message("user", "web", y - 910, "Нажать «Экспортировать отчёт»")
    s.message("web", "pages", y - 950, "POST /reports/{id}/export")
    s.activation("pages", y - 955, y - 1110)
    s.message("pages", "export", y - 990, "export_report(id)")
    s.activation("export", y - 995, y - 1068)
    s.message("export", "repdb", y - 1030, "сохранить DOCX, PDF, XLSX")
    s.message("export", "pages", y - 1063, "готово", kind="reply")
    s.message("pages", "web", y - 1100, "ссылки на документы", kind="reply")
    s.message("user", "web", y - 1145, "Открыть раздел «Анализ отчётов» (руководство)")
    s.message("web", "pages", y - 1185, "POST /reports/{id}/review: вес, влиятельность, реакция")
    s.message("pages", "repdb", y - 1225, "сохранить решения, закрыть процесс")
    c.save("uml-2-sequence-report")


def sequence_collection() -> None:
    c = Canvas(1880, 1640, "Сбор публикаций и журнал отладки", "UML: диаграмма последовательности · как система заходит на сайт и находит упоминания")
    s = Sequence(c, {
        "admin": (70, "Администратор", True),
        "debug": (250, "Отладка сбора (страница)", False),
        "timer": (450, "Планировщик", False),
        "collector": (660, "Модуль сбора", False),
        "site": (870, "Источник СМИ", False),
        "matcher": (1070, "Поиск упоминаний (ObjectMatcher)", False),
        "ingest": (1280, "Обработка при сборе", False),
        "nlp": (1480, "NLP-модули", False),
        "db": (1690, "База публикаций", False),
    }, top=1520, bottom=40)

    y = 1390
    s.message("timer", "collector", y, "collect_all(): сразу при запуске и каждые 30 мин", kind="async")
    s.activation("collector", y - 5, y - 1010)
    s.message("collector", "db", y - 40, "start_run() — новый запуск")

    s.fragment(560, 1800, y - 70, y - 960, "loop", "для каждого активного источника")
    s.message("collector", "site", y - 105, "GET лента RSS")
    s.message("site", "collector", y - 140, "XML: статус, размер, время ответа", kind="reply")
    s.message("collector", "db", y - 180, "события «запрос», «разбор»")

    s.fragment(590, 1780, y - 210, y - 930, "loop", "для каждой записи ленты")
    s.fragment(610, 1760, y - 240, y - 910, "alt", "запись уже в базе", separators=[(y - 320, "новая запись")])
    s.message("collector", "db", y - 280, "событие «пропуск: уже есть в базе»")
    s.message("collector", "matcher", y - 355, "find_mentions(заголовок, анонс)")
    s.message("matcher", "collector", y - 390, "объекты, позиции в тексте", kind="reply")
    s.fragment(630, 1740, y - 415, y - 890, "alt", "упоминаний нет", separators=[(y - 500, "упоминание найдено")])
    s.message("collector", "db", y - 455, "событие «пропуск: упоминаний нет»")
    s.message("collector", "db", y - 540, "событие «найдено» с подсвеченным фрагментом")
    s.message("collector", "site", y - 580, "GET страница статьи")
    s.message("site", "collector", y - 615, "HTML → полный текст (trafilatura)", kind="reply")
    s.message("collector", "ingest", y - 655, "ingest_item(источник, запись)")
    s.activation("ingest", y - 660, y - 815)
    s.message("ingest", "nlp", y - 695, "classify_topic(), extract_entities()")
    s.message("ingest", "nlp", y - 730, "analyze_sentiment()")
    s.message("ingest", "db", y - 770, "публикация и упоминания")
    s.message("ingest", "collector", y - 810, "публикация", kind="reply")
    s.message("collector", "db", y - 855, "событие «сохранено»: тема, тональность")
    s.message("collector", "db", y - 1000, "итоги запуска; старые события удаляются")

    s.message("admin", "debug", y - 1050, "открыть журнал запуска")
    s.fragment(30, 1800, y - 1080, y - 1250, "loop", "каждую секунду, параллельно со сбором, пока запуск не завершён")
    s.message("debug", "db", y - 1125, "GET /api/debug/runs/{id}/events?after=N")
    s.message("db", "debug", y - 1165, "новые события после N", kind="reply")
    s.message("debug", "admin", y - 1205, "строки журнала с подсветкой найденных упоминаний", kind="reply")
    c.save("uml-3-sequence-collection")


# ------------------------------------------------------------------ классы


def class_box(c: Canvas, x, top, width, name, attributes, operations=(), stereotype=""):
    """Класс из трёх отделений. Возвращает границы для привязки связей."""
    name_height = 34 if stereotype else 24
    attr_height = 8 + 14.5 * len(attributes) if attributes else 10
    op_height = 8 + 14.5 * len(operations) if operations else 10
    height = name_height + attr_height + op_height
    bottom = top - height
    c.axis.add_patch(Rectangle((x, bottom), width, height, facecolor=FILL, edgecolor=LINE, linewidth=1.1, zorder=4))
    c.axis.add_patch(Rectangle((x, top - name_height), width, name_height, facecolor=HEAD, edgecolor=LINE, linewidth=1.1, zorder=4))
    if stereotype:
        c.text(x + width / 2, top - 11, f"«{stereotype}»", size=8, ha="center", va="center", color=MUTED)
        c.text(x + width / 2, top - 25, name, size=10, ha="center", va="center", fontweight="bold")
    else:
        c.text(x + width / 2, top - name_height / 2, name, size=10, ha="center", va="center", fontweight="bold")
    line_y = top - name_height
    for index, value in enumerate(attributes):
        c.text(x + 8, line_y - 11 - 14.5 * index, value, size=7.8, va="center", family=MONO)
    line_y -= attr_height
    c.line([(x, line_y), (x + width, line_y)], width=1.1, zorder=5)
    for index, value in enumerate(operations):
        c.text(x + 8, line_y - 11 - 14.5 * index, value, size=7.8, va="center", family=MONO)
    return {"left": x, "right": x + width, "top": top, "bottom": bottom, "cx": x + width / 2, "cy": (top + bottom) / 2}


def multiplicity(c: Canvas, point, value, dx=8, dy=8):
    c.text(point[0] + dx, point[1] + dy, value, size=8.5, ha="left" if dx >= 0 else "right", va="center")


def package(c: Canvas, x, y, width, height, label):
    c.axis.add_patch(Rectangle((x, y + height), 230, 26, facecolor="#eeeeee", edgecolor=BOUNDARY, linewidth=1.1, zorder=1))
    c.text(x + 10, y + height + 13, label, size=9.5, va="center", fontweight="bold")
    c.axis.add_patch(Rectangle((x, y), width, height, facecolor="#fafafa", edgecolor=BOUNDARY, linewidth=1.1, zorder=0))


def class_data_model() -> None:
    c = Canvas(2060, 1340, "Модель данных", "UML: диаграмма классов · две базы данных, связи только через идентификаторы")
    package(c, 30, 60, 1110, 1160, "publications.db")
    package(c, 1180, 60, 850, 1160, "reports.db")

    source = class_box(c, 60, 1180, 320, "Source", [
        "+id: int", "+name: str", "+feed_url: str [0..1]", "+media_type: str", "+level: str",
        "+authority: float", "+is_active: bool", "+is_custom: bool", "+is_synthetic: bool",
        "+last_collected_at: datetime", "+last_status: str",
    ])
    obj = class_box(c, 480, 1180, 300, "MonitoringObject", [
        "+id: int", "+name: str", "+kind: str", "+aliases: list[str]", "+weak_aliases: list[str]",
        "+references: list[str]", "+other_organizations: list[str]", "+note: str",
    ])
    run = class_box(c, 830, 1180, 290, "CollectionRun", [
        "+id: int", "+trigger: str", "+started_at: datetime", "+finished_at: datetime [0..1]",
        "+sources_total: int", "+items_seen: int", "+items_added: int", "+errors: list",
    ])
    publication = class_box(c, 60, 700, 320, "Publication", [
        "+id: int", "+url: str", "+title: str", "+text: str", "+published_at: datetime",
        "+topic: str", "+topic_score: float", "+entities: list", "+tone: str", "+tone_score: float",
        "+is_synthetic: bool",
    ])
    mention = class_box(c, 480, 640, 300, "Mention", ["+strong_count: int", "+weak_count: int"])
    event = class_box(c, 830, 700, 290, "CollectionEvent", [
        "+id: int", "+source_name: str", "+at: datetime", "+stage: str", "+message: str",
        "+title: str", "+url: str", "+details: dict",
    ])

    report = class_box(c, 1210, 1180, 360, "Report", [
        "+id: int", "+object_id: int", "+object_name: str", "+context_name: str", "+date_from: datetime",
        "+date_to: datetime", "+status: str", "+steps: list", "+metrics: dict", "+clusters: list",
        "+review_summary: str",
    ])
    document = class_box(c, 1640, 1180, 360, "ReportDocument", [
        "+format: str", "+filename: str", "+mime: str", "+size: int", "+content: bytes", "+created_at: datetime",
    ])
    snapshot = class_box(c, 1210, 700, 360, "ReportPublication", [
        "+publication_id: int", "+title: str", "+source_name: str", "+topic: str", "+sentiment: str",
        "+sentiment_score: float", "+role: str", "+main_entity: str", "+status: str",
        "+relevance_score: float", "+removal_reason: str", "+reprints: int", "+cluster: int [0..1]",
        "+reputation_weight: int",
    ])
    review = class_box(c, 1640, 700, 360, "MentionReview", ["+weight: int", "+is_influential: bool", "+reaction: str"])

    # Source 1 — 0..* Publication
    c.line([(source["cx"], source["bottom"]), (source["cx"], publication["top"])])
    multiplicity(c, (source["cx"], source["bottom"]), "1", dy=-12)
    multiplicity(c, (source["cx"], publication["top"]), "0..*", dy=12)
    # Издание агрегатора: самоассоциация parent
    c.line([(source["right"], source["top"] - 60), (source["right"] + 30, source["top"] - 60),
            (source["right"] + 30, source["top"] - 120), (source["right"], source["top"] - 120)])
    c.text(source["right"] + 34, source["top"] - 90, "parent\n0..1", size=8, va="center")
    # Publication ◆— 0..* Mention
    left, right = (publication["right"], mention["cy"]), (mention["left"], mention["cy"])
    c.line([left, right])
    c.diamond(left, right)
    multiplicity(c, right, "0..*", dx=-8, dy=10)
    # MonitoringObject 1 — 0..* Mention
    c.line([(obj["cx"], obj["bottom"]), (obj["cx"], mention["top"])])
    multiplicity(c, (obj["cx"], obj["bottom"]), "1", dy=-12)
    multiplicity(c, (obj["cx"], mention["top"]), "0..*", dy=12)
    # CollectionRun ◆— 0..* CollectionEvent
    c.line([(run["cx"], run["bottom"]), (run["cx"], event["top"])])
    c.diamond((run["cx"], run["bottom"]), (run["cx"], event["top"]))
    multiplicity(c, (run["cx"], event["top"]), "0..*", dy=12)

    # Report ◆— 0..* ReportDocument
    left, right = (report["right"], report["top"] - 80), (document["left"], report["top"] - 80)
    c.line([left, right])
    c.diamond(left, right)
    multiplicity(c, right, "0..*", dx=-8, dy=10)
    # Report ◆— 1..* ReportPublication
    c.line([(report["cx"], report["bottom"]), (report["cx"], snapshot["top"])])
    c.diamond((report["cx"], report["bottom"]), (report["cx"], snapshot["top"]))
    multiplicity(c, (report["cx"], snapshot["top"]), "1..*", dy=12)
    # ReportPublication ◆— 0..1 MentionReview
    left, right = (snapshot["right"], review["top"] - 40), (review["left"], review["top"] - 40)
    c.line([left, right])
    c.diamond(left, right)
    multiplicity(c, right, "0..1", dx=-8, dy=10)

    # Снимок публикации и объект отчёта: зависимости между базами по идентификатору
    y_low = 100
    c.arrow([(snapshot["cx"], snapshot["bottom"]), (snapshot["cx"], y_low), (publication["cx"] + 60, y_low),
             (publication["cx"] + 60, publication["bottom"])], dashed=True, label="«снимок» publication_id", at=0.5, offset=(0, 12))
    y_high = 1250
    c.arrow([(report["left"] + 60, report["top"]), (report["left"] + 60, y_high), (obj["cx"], y_high), (obj["cx"], obj["top"])],
            dashed=True, label="object_id", at=0.5, offset=(0, 12))
    c.save("uml-4-class-data")


def class_processing() -> None:
    c = Canvas(2020, 1240, "Классы обработки", "UML: диаграмма классов · сбор, поиск упоминаний, NLP и конвейер отчёта")

    raw = class_box(c, 40, 1150, 290, "RawItem", ["+title: str", "+text: str", "+url: str", "+published_at: datetime", "+publisher: str [0..1]"], stereotype="dataclass")
    feeds = class_box(c, 390, 1150, 330, "collector.feeds", [], [
        "+fetch(url): Response", "+parse_feed(content): list[RawItem]", "+find_feed_url(url): str",
        "+feed_links(html, base): list[str]", "+fetch_article_text(url): str",
    ], stereotype="utility")
    document = class_box(c, 790, 1150, 300, "ParsedDocument", [
        "+title: str", "+text: str", "+sentences: list[str]", "+title_lemmas: list[str]", "+sentence_lemmas: list",
    ], ["+all_lemmas(): list[str]"], stereotype="dataclass")
    matcher = class_box(c, 1160, 1150, 380, "ObjectMatcher", [
        "+object_id: int", "+name: str", "+aliases: list[tuple]", "+weak_aliases: list[tuple]", "+references: list[tuple]",
    ], [
        "+match(doc: ParsedDocument): MentionStats", "+find_spans(text): list[dict]", "+positions(lemmas): list[int]",
        "+other_organization_hits(doc): int",
    ])
    stats = class_box(c, 1610, 1150, 360, "MentionStats", [
        "+strong: int", "+weak: int", "+in_title: bool", "+in_lead: bool", "+named_sentences: list[int]",
        "+target_sentences: list[int]",
    ], ["+total(): int", "+share(): float"], stereotype="dataclass")

    trace = class_box(c, 40, 760, 290, "Trace", ["-session: Session", "-run_id: int", "-source: Source"],
                      ["+__call__(stage, message, …)", "+commit()"])
    service = class_box(c, 390, 760, 330, "collector.service", [], [
        "+collect_all(trigger): CollectionRun", "+start_run(trigger): (int, bool)", "+execute_run(run_id, ids)",
        "+collect_source(id, run_id): SourceResult", "+close_interrupted_runs(): int",
    ], stereotype="utility")
    inspect = class_box(c, 790, 760, 300, "collector.inspect", [], [
        "+inspect_url(url): Inspection", "+mention_evidence(…): dict", "+fragments(text, matchers)",
    ], stereotype="utility")
    inspection = class_box(c, 1160, 760, 380, "Inspection", ["+url: str", "+steps: list[dict]", "+items: list[dict]"],
                           ["+step(stage, message, **details)"], stereotype="dataclass")
    nlp = class_box(c, 1610, 760, 360, "nlp", [], [
        "+classify_topic(title, text)", "+extract_entities(title, text)", "+analyze_sentiment(doc, targets)",
        "+determine_role(entities, stats, m)", "+check_relevance(doc, stats, m)", "+find_duplicates(items)",
        "+cluster_publications(items)",
    ], stereotype="utility")

    request = class_box(c, 40, 360, 290, "ReportRequest", [
        "+object_id: int", "+context_code: str", "+date_from: datetime", "+date_to: datetime",
        "+source_ids: list[int]", "+context_keywords: str",
    ], stereotype="dataclass")
    pipeline = class_box(c, 390, 360, 330, "pipeline.report", [], [
        "+query_publications(session, request)", "+start_report(request): int", "+finish_report(report_id)",
        "+mark_step(report, code, status)",
    ], stereotype="utility")
    sentiment = class_box(c, 1160, 360, 240, "SentimentResult", ["+label: str", "+score: float", "+evidence: list"], stereotype="dataclass")
    role = class_box(c, 1440, 360, 230, "RoleResult", ["+role: str", "+main_entity: str"], stereotype="dataclass")
    relevance = class_box(c, 1710, 360, 260, "RelevanceResult", ["+score: float", "+is_relevant: bool", "+reasons: list[str]"], stereotype="dataclass")

    def use(source, target, points, label):
        c.arrow(points, dashed=True, label=label, size=8, offset=(0, 10))

    use(feeds, raw, [(feeds["left"], feeds["cy"] + 30), (raw["right"], feeds["cy"] + 30)], "«create»")
    use(service, feeds, [(service["cx"], service["top"]), (service["cx"], feeds["bottom"])], "«use»")
    use(service, trace, [(service["left"], trace["cy"]), (trace["right"], trace["cy"])], "«create»")
    use(inspect, feeds, [(inspect["left"] + 30, inspect["top"]), (feeds["right"] - 40, feeds["bottom"])], "«use»")
    use(inspect, matcher, [(inspect["right"] - 40, inspect["top"]), (matcher["left"] + 60, matcher["bottom"])], "«use»")
    use(inspect, inspection, [(inspect["right"], inspection["cy"]), (inspection["left"], inspection["cy"])], "«create»")
    use(matcher, document, [(matcher["left"], document["cy"]), (document["right"], document["cy"])], "«use»")
    use(matcher, stats, [(matcher["right"], stats["cy"] + 20), (stats["left"], stats["cy"] + 20)], "«create»")
    use(nlp, stats, [(nlp["cx"], nlp["top"]), (stats["cx"], stats["bottom"])], "«use»")
    use(pipeline, request, [(pipeline["left"], request["cy"]), (request["right"], request["cy"])], "«use»")
    gap = (inspect["bottom"] + max(request["top"], pipeline["top"])) / 2
    use(pipeline, nlp, [(pipeline["cx"], pipeline["top"]), (pipeline["cx"], gap), (nlp["left"] + 20, gap), (nlp["left"] + 20, nlp["bottom"])], "«use»")
    for target, x in ((sentiment, nlp["left"] + 110), (role, nlp["cx"] + 40), (relevance, nlp["right"] - 30)):
        c.arrow([(x, nlp["bottom"]), (target["cx"], target["top"])], dashed=True)
    c.text(role["cx"] + 70, (nlp["bottom"] + role["top"]) / 2, "«create»", size=8, ha="left", va="center",
           bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none"))
    c.save("uml-5-class-processing")


if __name__ == "__main__":
    use_cases()
    sequence_report()
    sequence_collection()
    class_data_model()
    class_processing()
    print(f"Диаграммы сохранены в {OUTPUT}")
