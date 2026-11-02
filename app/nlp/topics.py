"""Тематическая классификация публикации по справочнику тем.

Обучающей разметки по реальным СМИ нет, поэтому тема определяется без обучения.
Каждое слово текста сравнивается с опорными словами темы через векторы Navec:
так тема узнаётся и по словам, которых нет в опорном списке.
"""
from functools import lru_cache
from math import sqrt

import numpy as np

from app.nlp.ner import embedding
from app.nlp.text import content_lemmas, lemma

OTHER = "other"
MIN_SCORE = 0.01
SIMILARITY_FLOOR = 0.5
TITLE_REPEATS = 2

TOPICS: dict[str, tuple[str, str]] = {
    "science": ("Наука и исследования", "наука ученый исследование научный открытие журнал эксперимент экспедиция патент биолог физик химик историк климат мерзлота диссертация аспирант технология разработка"),
    "education": ("Образование и программы", "образование образовательный магистратура бакалавриат курс обучение учебный лекция семинар педагог учитель дисциплина методика"),
    "admission": ("Приёмная кампания", "абитуриент приемный поступление поступить зачисление зачислить егэ балл первокурсник набор конкурс бюджетный"),
    "international": ("Международное сотрудничество", "международный иностранный зарубежный делегация посольство китай индия казахстан меморандум обмен виза страна"),
    "student_life": ("Студенческая жизнь", "студенческий фестиваль соревнование спорт сборная творчество клуб стройотряд квн турнир хакатон первенство шахматы волейбол столовая студсовет"),
    "social": ("Социальные инициативы", "волонтер социальный благотворительность просвещение просветительский экология акция донор пенсионер инклюзия лекторий ветеран приют"),
    "ratings": ("Рейтинги и развитие", "рейтинг приоритет стратегия позиция показатель конкурентоспособность топ"),
    "campus": ("Кампус и инфраструктура", "кампус здание строительство стройка ремонт библиотека инфраструктура аудитория реконструкция коворкинг застройщик фасад"),
    "management": ("Управление, кадры и финансы", "ректор проректор назначить совет бюджет зарплата кадры увольнение стипендия выплата надбавка профсоюз попечительский ставка"),
    "incidents": ("Конфликты и происшествия", "скандал прокуратура нарушение пожар авария суд сбой утечка плагиат забастовка эвакуация отравление драка полиция задымление"),
}

TOPIC_NAMES = {code: name for code, (name, _) in TOPICS.items()}
TOPIC_NAMES[OTHER] = "Прочее"


def _unit(word: str) -> np.ndarray:
    vector = embedding()[word]
    return vector / np.linalg.norm(vector)


@lru_cache(maxsize=1)
def _seed_matrices() -> dict[str, np.ndarray]:
    navec = embedding()
    matrices = {}
    for code, (_, seeds) in TOPICS.items():
        known = [word for word in {lemma(item) for item in seeds.split()} if word in navec]
        matrices[code] = np.stack([_unit(word) for word in known])
    return matrices


def topic_scores(title: str, text: str) -> dict[str, float]:
    """Близость текста к каждой теме. Заголовок весит вдвое больше текста."""
    navec = embedding()
    lemmas = [word for word in content_lemmas(title) * TITLE_REPEATS + content_lemmas(text) if word in navec]
    if not lemmas:
        return {code: 0.0 for code in TOPICS}
    document = np.stack([_unit(word) for word in lemmas])
    scores = {}
    for code, seeds in _seed_matrices().items():
        closeness = np.clip((document @ seeds.T).max(axis=1) - SIMILARITY_FLOOR, 0.0, None)
        scores[code] = round(float((closeness**2).sum()) / sqrt(len(lemmas)), 4)
    return scores


def classify_topic(title: str, text: str) -> tuple[str, float]:
    scores = topic_scores(title, text)
    best = max(scores, key=scores.get)
    if scores[best] < MIN_SCORE:
        return OTHER, scores[best]
    return best, scores[best]
