"""Единые метрики и правила отбора (функция 7 таблицы 4).

Все пороги и веса собраны здесь, чтобы результат не зависел от сотрудника,
а правила можно было показать в документе отчёта.
"""

# --- Тональность ---
# Итоговая оценка лежит в диапазоне [-1; 1].
SENTIMENT_POSITIVE_FROM = 0.12
SENTIMENT_NEGATIVE_TO = -0.12
# Доля словаря и нейросети в гибридной оценке.
SENTIMENT_LEXICON_SHARE = 0.65
SENTIMENT_MODEL_SHARE = 0.35

SENTIMENT_LABELS = {"positive": "Позитив", "neutral": "Нейтрально", "negative": "Негатив"}

# --- Роль объекта в публикации ---
ROLE_LABELS = {"main": "Главная", "secondary": "Второстепенная", "episodic": "Эпизодическая"}

# --- Уровни источников ---
LEVEL_LABELS = {"federal": "Федеральный", "regional": "Региональный", "local": "Местный"}
LEVEL_AUTHORITY = {"federal": 1.0, "regional": 0.6, "local": 0.3}
# Издания из агрегаторов считаются региональными, кроме известных федеральных.
FEDERAL_PUBLISHERS = {
    "ТАСС", "РИА Новости", "Интерфакс", "РБК", "Коммерсантъ", "Ведомости", "Известия", "Российская газета",
    "Lenta.ru", "Газета.Ru", "Forbes.ru", "Комсомольская правда", "Аргументы и Факты", "Московский комсомолец",
}

# --- Медиаиндекс: сумма A × R × T по очищенной выборке ---
ROLE_WEIGHT = {"main": 1.0, "secondary": 0.6, "episodic": 0.3}
TONE_WEIGHT = {"positive": 1.0, "neutral": 0.25, "negative": -1.0}

# --- Релевантность ---
RELEVANCE_THRESHOLD = 0.35
RELEVANCE_BASE_STRONG = 0.35     # объект назван однозначно («ТюмГУ»)
RELEVANCE_BASE_WEAK = 0.15       # только слабый псевдоним («тюменский вуз»)
RELEVANCE_TITLE = 0.25
RELEVANCE_LEAD = 0.15
RELEVANCE_PER_MENTION = 0.05
RELEVANCE_MENTION_CAP = 0.20
RELEVANCE_SHARE_FACTOR = 0.40
RELEVANCE_SHARE_CAP = 0.15
PENALTY_ANNOUNCEMENT = 0.60
PENALTY_OTHER_ORGANIZATION = 0.45
PENALTY_LIST_MENTION = 0.25
RELEVANCE_INCIDENTAL_CAP = 0.20  # ориентир на местности или биография: объект не герой текста

# --- Дубликаты ---
DUPLICATE_COSINE = 0.62          # близость TF-IDF векторов
DUPLICATE_SHINGLE_JACCARD = 0.30 # пересечение трёхсловных шинглов
DUPLICATE_WINDOW_DAYS = 7        # перепечатки ищем в пределах недели

# --- Репутационный вес негативного упоминания, 0–100 ---
REPUTATION_AUTHORITY = 45
REPUTATION_ROLE = 25
REPUTATION_STRENGTH = 20
REPUTATION_REPRINTS = 10
REPUTATION_REPRINTS_CAP = 3
INFLUENTIAL_FROM = 60
