"""Извлечение именованных сущностей (Natasha / Slovnet)."""
from functools import lru_cache

import app.nlp  # noqa: F401  подставляет pymorphy3 до импорта Natasha
from natasha import Doc, MorphVocab, NewsEmbedding, NewsMorphTagger, NewsNERTagger, Segmenter

ENTITY_LABELS = {"PER": "Персоны", "ORG": "Организации", "LOC": "Локации"}


@lru_cache(maxsize=1)
def embedding():
    """Векторы слов Navec; используются и в тематической классификации."""
    return NewsEmbedding()


@lru_cache(maxsize=1)
def _models():
    return Segmenter(), MorphVocab(), NewsMorphTagger(embedding()), NewsNERTagger(embedding())


def extract_entities(title: str, text: str) -> list[dict]:
    """Возвращает сущности с числом упоминаний и признаком «есть в заголовке»."""
    segmenter, morph_vocab, morph_tagger, ner_tagger = _models()
    prefix = f"{title}. "
    document = Doc(prefix + text)
    document.segment(segmenter)
    document.tag_morph(morph_tagger)
    document.tag_ner(ner_tagger)

    found: dict[tuple[str, str], dict] = {}
    for span in document.spans:
        span.normalize(morph_vocab)
        normal = (span.normal or span.text).strip()
        if len(normal) < 2:
            continue
        key = (span.type, normal.lower())
        entry = found.setdefault(key, {"type": span.type, "name": normal, "count": 0, "in_title": False, "first": span.start})
        entry["count"] += 1
        entry["in_title"] = entry["in_title"] or span.start < len(prefix)
    return sorted(found.values(), key=lambda item: item["first"])
