"""Оценка тональности по единой шкале «позитив — нейтрально — негатив».

Гибрид двух источников:
* словарь с правилами отрицания и усиления знает лексику репутационных новостей
  («прокуратура выявила нарушения», «получили грант»), которую общая модель
  считает нейтральной;
* модель rubert-tiny2 понимает общий смысл и обобщает на слова вне словаря.

Если модель недоступна (нет интернета при первом запуске, не установлен torch),
система работает только на словаре и указывает это в отчёте.
"""
import logging
import math
from dataclasses import dataclass, field
from functools import lru_cache

from app import config, rules
from app.nlp import lexicon
from app.nlp.text import ParsedDocument, lemma, lemmatize

logger = logging.getLogger(__name__)

TITLE_WEIGHT = 2.0
BACKGROUND_WEIGHT = 0.25
LEXICON_SCALE = 2.5
MODEL_TEXT_LIMIT = 900
EVIDENCE_LIMIT = 8


@dataclass
class SentimentResult:
    label: str
    score: float
    evidence: list[dict] = field(default_factory=list)


def _build_lexicon() -> dict[str, float]:
    table: dict[str, float] = {}
    groups = [
        (lexicon.POSITIVE_MILD, lexicon.WEIGHT_MILD),
        (lexicon.NEGATIVE_MILD, -lexicon.WEIGHT_MILD),
        (lexicon.POSITIVE_STRONG, lexicon.WEIGHT_STRONG),
        (lexicon.NEGATIVE_STRONG, -lexicon.WEIGHT_STRONG),
    ]
    for words, weight in groups:
        for word in words.split():
            table[lemma(word)] = weight
    return table


_LEXICON = _build_lexicon()
_PHRASES = {tuple(lemmatize(key)): value for key, value in lexicon.PHRASES.items()}
_MAX_PHRASE = max(len(key) for key in _PHRASES)


def score_lemmas(lemmas: list[str]) -> tuple[float, list[dict]]:
    """Сумма весов предложения с учётом отрицаний и усилителей."""
    total = 0.0
    evidence: list[dict] = []
    index = 0
    while index < len(lemmas):
        weight, size = None, 1
        for length in range(_MAX_PHRASE, 1, -1):
            value = _PHRASES.get(tuple(lemmas[index : index + length]))
            if value is not None:
                weight, size = value, length
                break
        if weight is None:
            weight = _LEXICON.get(lemmas[index])
        if weight is not None:
            before = lemmas[max(0, index - 2) : index]
            after = lemmas[index + size : index + size + 1]  # «нарушений не выявлено»
            if any(item in lexicon.NEGATORS for item in before + after):
                # «не выявили нарушений» — слабый плюс, «не получили» — обычный минус.
                weight = -weight * 0.5
            elif any(item in lexicon.INTENSIFIERS for item in before):
                weight *= 1.5
            total += weight
            evidence.append({"word": " ".join(lemmas[index : index + size]), "weight": round(weight, 2)})
        index += size
    return total, evidence


def _lexicon_score(document: ParsedDocument, targets: list[int] | None) -> tuple[float, list[dict]]:
    target_set = set(targets) if targets else None
    title_score, evidence = score_lemmas(document.title_lemmas)
    total = title_score * TITLE_WEIGHT
    weight_sum = TITLE_WEIGHT
    for index, lemmas in enumerate(document.sentence_lemmas):
        value, found = score_lemmas(lemmas)
        factor = 1.0 if target_set is None or index in target_set else BACKGROUND_WEIGHT
        total += value * factor
        weight_sum += factor
        evidence.extend(found if factor == 1.0 else [])
    return math.tanh(total / (LEXICON_SCALE * math.sqrt(weight_sum))), evidence


@lru_cache(maxsize=1)
def _model():
    if not config.USE_TRANSFORMER:
        return None
    try:
        from transformers import pipeline

        return pipeline("text-classification", model=config.SENTIMENT_MODEL, top_k=None, truncation=True, max_length=512)
    except Exception as error:
        logger.warning("Модель тональности недоступна, работаем на словаре: %s", error)
        return None


def _model_score(document: ParsedDocument, targets: list[int] | None) -> float | None:
    classifier = _model()
    if classifier is None:
        return None
    sentences = document.sentences if not targets else [document.sentences[index] for index in targets]
    prompt = f"{document.title}. {' '.join(sentences)}"[:MODEL_TEXT_LIMIT]
    scores = {item["label"].lower(): item["score"] for item in classifier(prompt)[0]}
    return scores.get("positive", 0.0) - scores.get("negative", 0.0)


def method_name() -> str:
    if _model() is None:
        return "Тональный словарь (нейросетевая модель недоступна)"
    return f"Гибрид: тональный словарь и модель {config.SENTIMENT_MODEL}"


def label_for(score: float) -> str:
    if score >= rules.SENTIMENT_POSITIVE_FROM:
        return "positive"
    if score <= rules.SENTIMENT_NEGATIVE_TO:
        return "negative"
    return "neutral"


def analyze_sentiment(document: ParsedDocument, targets: list[int] | None = None) -> SentimentResult:
    """targets — номера предложений про объект; без них оценивается весь текст."""
    lexical, evidence = _lexicon_score(document, targets)
    model = _model_score(document, targets)
    if model is None:
        score = lexical
    else:
        score = rules.SENTIMENT_LEXICON_SHARE * lexical + rules.SENTIMENT_MODEL_SHARE * model
    unique = {item["word"]: item for item in sorted(evidence, key=lambda item: abs(item["weight"]))}
    strongest = sorted(unique.values(), key=lambda item: -abs(item["weight"]))
    return SentimentResult(label=label_for(score), score=round(score, 3), evidence=strongest[:EVIDENCE_LIMIT])
