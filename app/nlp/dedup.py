"""Поиск дубликатов и перепечаток внутри выборки."""
from dataclasses import dataclass
from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app import rules


@dataclass
class DedupItem:
    id: int
    lemmas: list[str]
    published_at: datetime
    authority: float


def _shingles(lemmas: list[str], size: int = 3) -> set[tuple[str, ...]]:
    return {tuple(lemmas[index : index + size]) for index in range(len(lemmas) - size + 1)}


def _jaccard(first: set, second: set) -> float:
    union = first | second
    return len(first & second) / len(union) if union else 0.0


def find_duplicates(items: list[DedupItem]) -> dict[int, int]:
    """Возвращает {id дубликата: id оригинала}.

    Оригинал — самая ранняя публикация группы, при равенстве дат — из более
    авторитетного источника. Группы собираются транзитивно: если B перепечатал A,
    а C перепечатал B, все три считаются одним инфоповодом.
    """
    if len(items) < 2:
        return {}

    documents = [" ".join(item.lemmas) for item in items]
    matrix = TfidfVectorizer(token_pattern=r"\S+", sublinear_tf=True).fit_transform(documents)
    similarity = cosine_similarity(matrix)
    shingles = [_shingles(item.lemmas) for item in items]

    parent = list(range(len(items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            if similarity[left, right] < rules.DUPLICATE_COSINE:
                continue
            days = abs((items[left].published_at - items[right].published_at).days)
            if days > rules.DUPLICATE_WINDOW_DAYS:
                continue
            if _jaccard(shingles[left], shingles[right]) >= rules.DUPLICATE_SHINGLE_JACCARD:
                parent[find(left)] = find(right)

    groups: dict[int, list[int]] = {}
    for index in range(len(items)):
        groups.setdefault(find(index), []).append(index)

    duplicates: dict[int, int] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda index: (items[index].published_at, -items[index].authority))
        original = items[members[0]].id
        for index in members[1:]:
            duplicates[items[index].id] = original
    return duplicates
