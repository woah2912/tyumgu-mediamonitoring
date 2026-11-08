"""Строит C4-диаграммы системы: уровни контекста, контейнеров и компонентов.

Запуск из корня проекта: python docs/c4/build_diagrams.py
Результат: файлы .png и .svg рядом со скриптом.
"""
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

OUTPUT = Path(__file__).parent

PERSON = "#08427b"
SYSTEM = "#1168bd"
CONTAINER = "#438dd5"
COMPONENT = "#85bbf0"
EXTERNAL = "#8a8a8a"
INK = "#2b2b2b"
LINE = "#5a5a5a"


class Diagram:
    def __init__(self, width: float, height: float, title: str, subtitle: str):
        self.figure, self.axis = plt.subplots(figsize=(width / 100, height / 100))
        self.axis.set_xlim(0, width)
        self.axis.set_ylim(0, height)
        self.axis.axis("off")
        self.axis.text(30, height - 28, title, fontsize=17, fontweight="bold", color=INK, va="top")
        self.axis.text(30, height - 62, subtitle, fontsize=11, color="#5a5a5a", va="top")

    def _caption(self, x, y, width, height, name, kind, description, color, ink, wrap):
        center = x + width / 2
        lines = textwrap.wrap(description, wrap) if description else []
        total = 25 + 19 + 16 * len(lines)
        top = y + height / 2 + total / 2
        self.axis.text(center, top, name, ha="center", va="top", fontsize=11, fontweight="bold", color=ink, zorder=5)
        self.axis.text(center, top - 24, f"[{kind}]", ha="center", va="top", fontsize=8, color=ink, zorder=5)
        for index, line in enumerate(lines):
            self.axis.text(center, top - 43 - index * 16, line, ha="center", va="top", fontsize=8.5, color=ink, zorder=5)

    def box(self, x, y, width, height, name, kind, description="", color=SYSTEM, ink="white", wrap=36):
        self.axis.add_patch(
            FancyBboxPatch(
                (x, y), width, height, boxstyle="round,pad=0,rounding_size=10", facecolor=color,
                edgecolor="none", zorder=3,
            )
        )
        self._caption(x, y, width, height, name, kind, description, color, ink, wrap)

    def person(self, x, y, width, height, name, description, wrap=34):
        center = x + width / 2
        self.axis.add_patch(Circle((center, y + height + 22), 26, facecolor=PERSON, edgecolor="none", zorder=3))
        self.box(x, y, width, height, name, "Человек", description, PERSON, wrap=wrap)

    def database(self, x, y, width, height, name, kind, description="", color=CONTAINER, ink="white", wrap=34):
        rim = 26
        self.axis.add_patch(Rectangle((x, y + rim / 2), width, height - rim, facecolor=color, edgecolor="none", zorder=3))
        self.axis.add_patch(Ellipse((x + width / 2, y + rim / 2), width, rim, facecolor=color, edgecolor="none", zorder=3))
        self.axis.add_patch(Ellipse((x + width / 2, y + height - rim / 2), width, rim, facecolor=color, edgecolor="white", linewidth=1, zorder=4))
        self._caption(x, y - 8, width, height, name, kind, description, color, ink, wrap)

    def boundary(self, x, y, width, height, label):
        self.axis.add_patch(
            FancyBboxPatch(
                (x, y), width, height, boxstyle="round,pad=0,rounding_size=8", facecolor="none",
                edgecolor="#7a7a7a", linewidth=1.2, linestyle=(0, (6, 4)), zorder=1,
            )
        )
        self.axis.text(x + 14, y + 12, label, fontsize=10, fontweight="bold", color="#5a5a5a", va="bottom", zorder=2)

    def arrow(self, start, end, label="", tech="", at=0.5, offset=(0, 0), curve=0.0, dashed=True, via=()):
        if via:
            # Ломаная: промежуточные отрезки линией, стрелка на последнем.
            points = [start, *via]
            xs, ys = zip(*points)
            self.axis.plot(xs, ys, color=LINE, linewidth=1.1, linestyle=(0, (5, 3)) if dashed else "-", zorder=2)
            label_start, label_end = via[0], via[1] if len(via) > 1 else end
            start = via[-1]
        else:
            label_start, label_end = start, end
        self.axis.add_patch(
            FancyArrowPatch(
                start, end, arrowstyle="-|>", mutation_scale=13, color=LINE, linewidth=1.1,
                linestyle=(0, (5, 3)) if dashed else "-", shrinkA=0, shrinkB=0, zorder=2,
                connectionstyle=f"arc3,rad={curve}",
            )
        )
        if label:
            text = label + (f"\n[{tech}]" if tech else "")
            x = label_start[0] + (label_end[0] - label_start[0]) * at + offset[0]
            y = label_start[1] + (label_end[1] - label_start[1]) * at + offset[1]
            self.axis.text(
                x, y, text, ha="center", va="center", fontsize=8, color=INK, zorder=6, linespacing=1.15,
                bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none", alpha=0.93),
            )

    def legend(self, x, y, items):
        for index, (color, label) in enumerate(items):
            left = x + index * 190
            self.axis.add_patch(FancyBboxPatch((left, y), 22, 14, boxstyle="round,pad=0,rounding_size=3", facecolor=color, edgecolor="none"))
            self.axis.text(left + 30, y + 7, label, fontsize=8.5, color=INK, va="center")

    def save(self, name: str):
        self.figure.savefig(OUTPUT / f"{name}.png", dpi=170, facecolor="white", bbox_inches="tight", pad_inches=0.15)
        self.figure.savefig(OUTPUT / f"{name}.svg", facecolor="white", bbox_inches="tight", pad_inches=0.15)
        plt.close(self.figure)


def context() -> None:
    d = Diagram(1400, 900, "Система медиамониторинга ТюмГУ", "Уровень 1 C4: контекст системы")

    d.person(170, 640, 360, 120, "Сотрудник УСК", "Настраивает запрос, изучает отчёт и экспортирует документ")
    d.person(870, 640, 360, 120, "Руководство УСК", "Анализирует документ, оценивает негатив и решает, нужна ли реакция")
    d.box(420, 330, 560, 150, "Система медиамониторинга ТюмГУ", "Программная система",
          "Собирает упоминания из СМИ, определяет тему, сущности и тональность, очищает выборку и формирует отчёты", wrap=54)
    d.box(40, 70, 360, 120, "СМИ", "Внешняя система", "Федеральные и региональные издания с RSS-лентами", EXTERNAL)
    d.box(520, 70, 360, 120, "Google Новости", "Внешняя система", "Поиск упоминаний ТюмГУ по всем изданиям через RSS", EXTERNAL)
    d.box(1000, 70, 360, 120, "Hugging Face Hub", "Внешняя система", "Хранилище нейросетевой модели тональности", EXTERNAL)

    d.arrow((350, 640), (560, 480), "Задаёт объект, контекст, период\nи источники, экспортирует отчёт", "HTTP", at=0.48, offset=(-60, 0))
    d.arrow((1050, 640), (840, 480), "Изучает документы, оценивает вес\nупоминаний, фиксирует реакцию", "HTTP", at=0.48, offset=(60, 0))
    d.arrow((540, 330), (220, 190), "Забирает публикации", "RSS, HTTPS", at=0.5, offset=(-50, 8))
    d.arrow((700, 330), (700, 190), "Ищет упоминания", "RSS, HTTPS")
    d.arrow((860, 330), (1180, 190), "Один раз скачивает модель", "HTTPS", at=0.5, offset=(60, 8))

    d.legend(40, 20, [(PERSON, "Пользователь"), (SYSTEM, "Наша система"), (EXTERNAL, "Внешняя система")])
    d.save("c4-1-context")


def containers() -> None:
    d = Diagram(1400, 1140, "Система медиамониторинга ТюмГУ", "Уровень 2 C4: контейнеры")

    d.person(170, 880, 320, 110, "Сотрудник УСК", "Настраивает запрос и экспортирует отчёт")
    d.person(570, 880, 320, 110, "Руководство УСК", "Анализирует документ и реагирует")

    d.boundary(40, 40, 1000, 780, "Система медиамониторинга ТюмГУ")
    d.box(320, 630, 420, 130, "Веб-интерфейс", "Контейнер: HTML, CSS, JavaScript, Chart.js",
          "Форма запроса, страница отчёта с графиками, раздел руководства и справочники", CONTAINER, wrap=46)
    d.box(280, 340, 500, 150, "Сервер приложения", "Контейнер: Python, FastAPI, Uvicorn",
          "Страницы и JSON API, плановый сбор, NLP-обработка, расчёт метрик и формирование документов", CONTAINER, wrap=54)
    d.database(90, 90, 410, 150, "База публикаций", "Контейнер: SQLite, SQLAlchemy",
               "Источники, объекты мониторинга, публикации с разметкой, журнал сбора", wrap=46)
    d.database(570, 90, 410, 150, "База отчётов", "Контейнер: SQLite, SQLAlchemy",
               "Отчёты, снимки выборок, файлы DOCX, PDF и XLSX, решения руководства", wrap=46)

    d.box(1090, 500, 280, 120, "СМИ и Google Новости", "Внешняя система", "Публикации в RSS-лентах", EXTERNAL, wrap=30)
    d.box(1090, 230, 280, 120, "Hugging Face Hub", "Внешняя система", "Модель rubert-tiny2", EXTERNAL, wrap=30)

    d.arrow((330, 880), (450, 760), "Работает с отчётами", "браузер", offset=(-62, 0))
    d.arrow((730, 880), (610, 760), "Анализирует отчёты", "браузер", offset=(62, 0))
    d.arrow((530, 630), (530, 490), "Страницы, формы, статус обработки", "HTTP, JSON")
    d.arrow((400, 340), (295, 240), "Сохраняет и отбирает\nпубликации", "SQL", offset=(-72, 4))
    d.arrow((660, 340), (775, 240), "Сохраняет отчёты\nи документы", "SQL", offset=(68, 4))
    d.arrow((780, 450), (1090, 545), "Собирает публикации", "RSS, HTTPS", at=0.5, offset=(0, 18))
    d.arrow((780, 390), (1090, 300), "Скачивает модель\nпри первом запуске", "HTTPS", at=0.5, offset=(0, -20))

    d.legend(40, 4, [(PERSON, "Пользователь"), (CONTAINER, "Контейнер"), (EXTERNAL, "Внешняя система")])
    d.save("c4-2-containers")


def components() -> None:
    d = Diagram(2190, 1430, "Сервер приложения", "Уровень 3 C4: компоненты")

    width, height = 340, 120
    d.box(930, 1260, 340, 90, "Веб-интерфейс", "Контейнер: HTML, JavaScript", "Формы и страница отчёта", CONTAINER)

    d.boundary(380, 30, 1420, 1170, "Сервер приложения (FastAPI)")
    d.boundary(415, 75, 1350, 195, "NLP-модули")

    d.box(420, 1040, width, height, "Отладка и просмотр БД", "Компонент: app/web/admin.py", "Журнал сбора, проверка адреса, таблицы обеих баз", COMPONENT, INK, wrap=38)
    d.box(860, 1040, width, height, "Страницы", "Компонент: app/web/pages.py", "Форма запроса, отчёт, анализ руководства, справочники", COMPONENT, INK, wrap=38)
    d.box(1300, 1040, width, height, "JSON API", "Компонент: app/web/api.py", "Статус обработки и данные таблиц", COMPONENT, INK, wrap=38)

    d.box(420, 780, width, height, "Модуль сбора", "Компонент: feedparser, httpx, trafilatura", "Плановый и ручной сбор, свои источники, полный текст", COMPONENT, INK, wrap=38)
    d.box(900, 780, width, height, "Конвейер отчёта", "Компонент: app/pipeline/report.py", "Шаги дорожки «Система» из BPMN TO-BE", COMPONENT, INK, wrap=38)
    d.box(1420, 860, width, height, "Формирование документов", "Компонент: python-docx, ReportLab", "Единый шаблон и файлы DOCX, PDF, XLSX", COMPONENT, INK, wrap=38)

    d.box(420, 520, width, height, "Обработка при сборе", "Компонент: app/pipeline/ingest.py", "Разметка новой публикации и индекс упоминаний", COMPONENT, INK, wrap=38)
    d.box(1420, 520, width, height, "Метрики и правила", "Компонент: app/metrics.py, app/rules.py", "Индекс тональности, медиаиндекс, вес упоминаний", COMPONENT, INK, wrap=38)

    y, step, small = 118, 334, 320
    d.box(431, y, small, height, "Темы и кластеры", "Компонент: Navec, scikit-learn", "Классификация по справочнику и кластеризация", COMPONENT, INK, wrap=36)
    d.box(431 + step, y, small, height, "Сущности и роль", "Компонент: Natasha, Slovnet", "Персоны, организации, локации, главная роль", COMPONENT, INK, wrap=36)
    d.box(431 + step * 2, y, small, height, "Тональность", "Компонент: словарь и rubert-tiny2", "Гибридная оценка по единой шкале", COMPONENT, INK, wrap=36)
    d.box(431 + step * 3, y, small, height, "Отбор публикаций", "Компонент: scikit-learn, правила", "Релевантность, дубликаты, случайные публикации", COMPONENT, INK, wrap=36)

    d.box(30, 790, 300, 100, "СМИ и Google Новости", "Внешняя система", "RSS-ленты", EXTERNAL, wrap=30)
    d.database(30, 510, 300, 140, "База публикаций", "Контейнер: SQLite", "", wrap=30)
    d.database(1850, 620, 300, 140, "База отчётов", "Контейнер: SQLite", "", wrap=30)

    d.arrow((940, 1290), (700, 1160), "Отладка, базы данных", "HTTP", at=0.3, offset=(-100, 8))
    d.arrow((1030, 1260), (1030, 1160), "Запрос, экспорт,\nрешения", "HTTP", at=0.72, offset=(0, 0))
    d.arrow((1220, 1260), (1420, 1160), "Опрос статуса и данные", "JSON", at=0.7, offset=(112, 6))

    d.arrow((560, 1040), (560, 900), "Журнал отладки,\nпроверка адреса", offset=(-4, 0))
    d.arrow((420, 1075), (320, 650), "Читает таблицы", "SQL", at=0.25, offset=(-50, 0))
    d.arrow((760, 1150), (2100, 760), "Читает таблицы", "SQL", at=0.8, via=((760, 1225), (2100, 1225)), offset=(0, 14))
    d.arrow((900, 1040), (700, 900), "Свои источники,\nзапуск сбора", offset=(10, 26))
    d.arrow((1040, 1040), (1060, 900), "Запускает\nобработку", at=0.5, offset=(50, 0))
    d.arrow((1200, 1080), (1500, 980), "Команда экспорта", at=0.35, offset=(-10, -22))

    d.arrow((420, 840), (330, 840), "Забирает\nленты", "RSS", offset=(0, 62))
    d.arrow((590, 780), (590, 640), "Новые записи", at=0.16)
    d.arrow((420, 580), (330, 580), "Сохраняет", "SQL", offset=(0, -56))
    d.arrow((590, 520), (590, 270), "Тема, сущности,\nобщая тональность")

    d.arrow((900, 805), (330, 640), "Отбирает", "SQL", at=0.13, offset=(0, 26))
    d.arrow((1070, 780), (1070, 270), "Тональность к объекту, главная роль,\nочистка выборки, кластеры")
    d.arrow((1240, 800), (1420, 640), "Показатели", offset=(34, 16))
    d.arrow((1240, 850), (1850, 720), "Сохраняет снимок", "SQL", at=0.5, offset=(0, -26))

    d.arrow((1760, 900), (1910, 760), "Сохраняет\nфайлы", "SQL", offset=(-72, -12))
    d.arrow((1640, 1090), (1960, 760), "Читает", "SQL", offset=(30, 20))

    d.legend(30, 2, [(CONTAINER, "Контейнер"), (COMPONENT, "Компонент"), (EXTERNAL, "Внешняя система")])
    d.save("c4-3-components")


if __name__ == "__main__":
    context()
    containers()
    components()
    print(f"Диаграммы сохранены в {OUTPUT}")
