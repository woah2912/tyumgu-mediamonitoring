"""Тематическая кластеризация выборки отчёта.

Новости об одном вузе короткие и делят общую лексику, поэтому TF-IDF и LSA дают на
них слабое разделение. Документ здесь описывается средним вектором слов Navec
с весами TF-IDF и близостью к темам справочника. Кластеры всё равно строятся без
учителя и могут находить темы, которых в справочнике нет.
Число кластеров подбирается по силуэтному коэффициенту.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize

from app.nlp.ner import embedding
from app.nlp.topics import OTHER, TOPIC_NAMES

MIN_FOR_CLUSTERING = 6
MAX_CLUSTERS = 12
RANDOM_STATE = 42
TERMS_IN_LABEL = 5
_VECTOR_SIZE = 300
# Слова, общие для всех новостей о вузе: как признаки не мешают, но подпись не объясняют.
_GENERIC_TERMS = {"университет", "вуз", "тюмгу", "тюменский", "государственный", "госуниверситет", "тюмень", "студент", "область", "сотрудник"}


@dataclass
class ClusterInput:
    id: int
    title: str
    lemmas: list[str]
    topic: str
    topic_scores: list[float]


def _single_cluster(items: list[ClusterInput]) -> tuple[dict[int, int], list[dict]]:
    counts = Counter(word for item in items for word in item.lemmas if word not in _GENERIC_TERMS)
    terms = [word for word, _ in counts.most_common(TERMS_IN_LABEL)]
    summary = {
        "id": 0,
        "name": _cluster_name(items),
        "terms": terms,
        "size": len(items),
        "example": items[0].title,
    }
    return {item.id: 0 for item in items}, [summary]


def _cluster_name(items: list[ClusterInput]) -> str:
    """Название кластера — самая частая тема, а «Прочее» только если других нет."""
    counts = Counter(item.topic for item in items if item.topic != OTHER)
    return TOPIC_NAMES[counts.most_common(1)[0][0] if counts else OTHER]


def _top_terms(weights: np.ndarray, terms: np.ndarray) -> list[str]:
    ordered = (str(term) for term in terms[weights.argsort()[::-1]])
    return [term for term in ordered if term not in _GENERIC_TERMS][:TERMS_IN_LABEL]


def _centered(matrix: np.ndarray) -> np.ndarray:
    return normalize(matrix - matrix.mean(axis=0))


def _features(tfidf, terms: np.ndarray, items: list[ClusterInput]) -> np.ndarray:
    navec = embedding()
    word_vectors = np.stack([navec[word] if word in navec else np.zeros(_VECTOR_SIZE) for word in terms])
    documents = _centered(np.asarray(tfidf @ word_vectors))
    topics = _centered(np.array([item.topic_scores for item in items]))
    return normalize(np.hstack([documents, topics]))


def cluster_publications(items: list[ClusterInput]) -> tuple[dict[int, int], list[dict]]:
    """Возвращает {id публикации: номер кластера} и описание кластеров."""
    if not items:
        return {}, []
    if len(items) < MIN_FOR_CLUSTERING:
        return _single_cluster(items)

    documents = [" ".join(item.lemmas) for item in items]
    vectorizer = TfidfVectorizer(token_pattern=r"\S+", min_df=2, max_df=0.6, sublinear_tf=True)
    try:
        tfidf = vectorizer.fit_transform(documents)
    except ValueError:  # после фильтров частоты не осталось ни одного признака
        return _single_cluster(items)

    terms = np.array(vectorizer.get_feature_names_out())
    features = _features(tfidf, terms, items)

    best_labels, best_score = None, -1.0
    for count in range(2, min(MAX_CLUSTERS, len(items) // 2) + 1):
        labels = KMeans(count, n_init=10, random_state=RANDOM_STATE).fit_predict(features)
        score = silhouette_score(features, labels, metric="cosine")
        if score > best_score:
            best_labels, best_score = labels, score

    summaries: list[dict] = []
    assignment: dict[int, int] = {}
    for new_id, (label, size) in enumerate(Counter(best_labels.tolist()).most_common()):
        members = np.where(best_labels == label)[0]
        weights = np.asarray(tfidf[members].mean(axis=0)).ravel()
        center = features[members].mean(axis=0)
        representative = members[int(np.argmax(features[members] @ center))]
        summaries.append(
            {
                "id": new_id,
                "name": _cluster_name([items[index] for index in members]),
                "terms": _top_terms(weights, terms),
                "size": int(size),
                "example": items[representative].title,
            }
        )
        for index in members:
            assignment[items[index].id] = new_id
    return assignment, summaries
