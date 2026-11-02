"""Графики для документов отчёта в той же цветовой схеме, что и веб-интерфейс."""
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app import rules  # noqa: E402

COLORS = {"positive": "#2a78d6", "neutral": "#b5b4ac", "negative": "#e34948"}
INK = "#52514e"
GRID = "#e1e0d9"
SERIES = list(rules.SENTIMENT_LABELS)

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def _render(figure) -> bytes:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return buffer.getvalue()


def _legend(axis) -> None:
    axis.legend(
        handles=[plt.Rectangle((0, 0), 1, 1, color=COLORS[key]) for key in SERIES],
        labels=[rules.SENTIMENT_LABELS[key] for key in SERIES],
        frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.13), handlelength=1, handleheight=1,
    )


def timeline_chart(metrics: dict) -> bytes:
    points = metrics["timeline"]["points"]
    figure, axis = plt.subplots(figsize=(9.2, 3.4))
    positions = range(len(points))
    bottom = [0] * len(points)
    for key in SERIES:
        values = [point[key] for point in points]
        axis.bar(positions, values, bottom=bottom, color=COLORS[key], width=0.62, edgecolor="white", linewidth=1)
        bottom = [left + right for left, right in zip(bottom, values)]
    step = max(1, len(points) // 13)
    axis.set_xticks(list(positions)[::step], [point["label"] for point in points][::step])
    axis.yaxis.get_major_locator().set_params(integer=True)
    axis.grid(axis="y", color=GRID, linewidth=0.7)
    axis.set_axisbelow(True)
    _legend(axis)
    return _render(figure)


def _stacked_rows(rows: list[dict], width: float = 7.2) -> bytes:
    rows = list(reversed(rows))
    figure, axis = plt.subplots(figsize=(width, max(1.5, 0.36 * len(rows) + 0.7)))
    left = [0] * len(rows)
    for key in SERIES:
        values = [row[key] for row in rows]
        axis.barh(range(len(rows)), values, left=left, color=COLORS[key], height=0.58, edgecolor="white", linewidth=1)
        left = [first + second for first, second in zip(left, values)]
    axis.set_yticks(range(len(rows)), [row["name"] for row in rows])
    axis.xaxis.get_major_locator().set_params(integer=True)
    axis.grid(axis="x", color=GRID, linewidth=0.7)
    axis.set_axisbelow(True)
    for index, total in enumerate(left):
        axis.text(total + 0.1, index, str(total), va="center", fontsize=8, color=INK)
    _legend(axis)
    return _render(figure)


def topics_chart(metrics: dict) -> bytes:
    return _stacked_rows(metrics["topics"])


def sources_chart(metrics: dict) -> bytes:
    return _stacked_rows(metrics["sources"])
