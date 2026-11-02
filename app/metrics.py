"""Единые метрики отчёта."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app import rules
from app.nlp.topics import TOPIC_NAMES

WEEKLY_FROM_DAYS = 45
TOP_SOURCES = 10
TOP_ENTITIES = 10


def impact(item) -> float:
    """Вклад публикации в медиаиндекс: авторитет × роль × тональность."""
    return item.source_authority * rules.ROLE_WEIGHT[item.role] * rules.TONE_WEIGHT[item.sentiment]


def reputation_weight(authority: float, role: str, score: float, reprints: int) -> int:
    """Системная оценка веса негативного упоминания, 0–100."""
    reach = min(reprints, rules.REPUTATION_REPRINTS_CAP) / rules.REPUTATION_REPRINTS_CAP
    weight = (
        rules.REPUTATION_AUTHORITY * authority
        + rules.REPUTATION_ROLE * rules.ROLE_WEIGHT[role]
        + rules.REPUTATION_STRENGTH * min(abs(score), 1.0)
        + rules.REPUTATION_REPRINTS * reach
    )
    return round(min(weight, 100))


def _sentiment_counts(items) -> dict[str, int]:
    counts = Counter(item.sentiment for item in items)
    return {key: counts.get(key, 0) for key in rules.SENTIMENT_LABELS}


def _group_breakdown(items, key, label) -> list[dict]:
    groups = defaultdict(list)
    for item in items:
        groups[key(item)].append(item)
    rows = [{"code": code, "name": label(code), "count": len(group), **_sentiment_counts(group)} for code, group in groups.items()]
    return sorted(rows, key=lambda row: (-row["count"], row["name"]))


def _timeline(items, date_from: datetime, date_to: datetime) -> dict:
    span = (date_to - date_from).days + 1
    weekly = span > WEEKLY_FROM_DAYS
    step = 7 if weekly else 1

    def bucket(moment: datetime) -> datetime:
        return date_from + timedelta(days=((moment - date_from).days // step) * step)

    grouped = defaultdict(list)
    for item in items:
        grouped[bucket(item.published_at)].append(item)

    points = []
    moment = bucket(date_from)
    while moment <= date_to:
        points.append({"date": moment.strftime("%Y-%m-%d"), "label": moment.strftime("%d.%m"), **_sentiment_counts(grouped[moment])})
        moment += timedelta(days=step)
    return {"step": "week" if weekly else "day", "points": points}


def _top_entities(items) -> dict[str, list[dict]]:
    counters = defaultdict(Counter)
    for item in items:
        for entity in item.entities:
            counters[entity["type"]][entity["name"]] += 1
    return {
        kind: [{"name": name, "count": count} for name, count in counter.most_common(TOP_ENTITIES)]
        for kind, counter in counters.items()
    }


def compute_metrics(items, date_from: datetime, date_to: datetime) -> dict:
    """items — все публикации снимка отчёта; расчёт идёт по очищенной выборке."""
    kept = [item for item in items if item.status == "relevant"]
    sentiment = _sentiment_counts(kept)
    total = len(kept)
    negative = [item for item in kept if item.sentiment == "negative"]
    influential = [item for item in negative if item.reputation_weight >= rules.INFLUENTIAL_FROM]

    return {
        "found": len(items),
        "kept": total,
        "removed_duplicates": sum(1 for item in items if item.status == "duplicate"),
        "removed_random": sum(1 for item in items if item.status == "random"),
        "sentiment": sentiment,
        "tone_index": round((sentiment["positive"] - sentiment["negative"]) / total * 100, 1) if total else 0.0,
        "media_index": round(sum(impact(item) for item in kept), 1),
        "roles": _group_breakdown(kept, lambda item: item.role, lambda code: rules.ROLE_LABELS[code]),
        "main_role_share": round(sum(1 for item in kept if item.role == "main") / total * 100, 1) if total else 0.0,
        "levels": _group_breakdown(kept, lambda item: item.source_level, lambda code: rules.LEVEL_LABELS.get(code, code)),
        "sources": _group_breakdown(kept, lambda item: item.source_name, str)[:TOP_SOURCES],
        "topics": _group_breakdown(kept, lambda item: item.topic, lambda code: TOPIC_NAMES.get(code, code)),
        "timeline": _timeline(kept, date_from, date_to),
        "entities": _top_entities(kept),
        "main_entities": [
            {"name": name, "count": count}
            for name, count in Counter(item.main_entity for item in kept if item.main_entity).most_common(TOP_ENTITIES)
        ],
        "negative": len(negative),
        "influential": len(influential),
    }


def build_conclusions(metrics: dict, object_name: str) -> list[str]:
    """Краткие выводы для страницы отчёта и документа."""
    total = metrics["kept"]
    if not total:
        return ["После очистки в выборке не осталось публикаций."]
    sentiment = metrics["sentiment"]
    conclusions = [
        f"Публикаций об объекте «{object_name}» в очищенной выборке: {total}. "
        f"Позитивных {sentiment['positive']}, нейтральных {sentiment['neutral']}, негативных {sentiment['negative']}."
    ]
    index = metrics["tone_index"]
    balance = "положительный" if index > 10 else "отрицательный" if index < -10 else "близкий к нейтральному"
    conclusions.append(f"Индекс тональности равен {index:+.1f}: баланс упоминаний {balance}.")
    if metrics["topics"]:
        top = metrics["topics"][0]
        conclusions.append(f"Самая заметная тема — «{top['name']}»: публикаций {top['count']}.")
    most_negative = max(row["negative"] for row in metrics["topics"])
    if most_negative:
        names = [f"«{row['name']}»" for row in metrics["topics"] if row["negative"] == most_negative]
        where = f"в теме {names[0]}" if len(names) == 1 else f"в темах {', '.join(names)}"
        conclusions.append(f"Больше всего негатива {where}: негативных публикаций {most_negative}.")
    if metrics["influential"]:
        conclusions.append(
            f"Влиятельных негативных упоминаний: {metrics['influential']}. Руководству нужно оценить их и принять решение о реакции."
        )
    elif metrics["negative"]:
        conclusions.append("Негативные упоминания есть, но ни одно не достигает порога влиятельности.")
    else:
        conclusions.append("Негативных упоминаний в выборке нет.")
    return conclusions
