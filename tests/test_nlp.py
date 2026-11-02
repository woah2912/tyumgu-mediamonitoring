from datetime import datetime

import pytest

from app import metrics
from app.nlp.clustering import ClusterInput, cluster_publications
from app.nlp.dedup import DedupItem, find_duplicates
from app.nlp.ner import extract_entities
from app.nlp.objects import ObjectMatcher
from app.nlp.relevance import check_relevance
from app.nlp.roles import determine_role
from app.nlp.sentiment import analyze_sentiment
from app.nlp.text import content_lemmas, parse_document
from app.nlp.topics import classify_topic
from app.seed import OBJECTS


@pytest.fixture(scope="module")
def matcher():
    item = OBJECTS[0]
    return ObjectMatcher(
        1, item["name"], item["aliases"], item["weak_aliases"], item["references"], item["other_organizations"]
    )


def stats_for(matcher, title, text):
    document = parse_document(title, text)
    return document, matcher.match(document)


@pytest.mark.parametrize(
    "phrase",
    ["Тюменского государственного университета", "Тюменском госуниверситете", "ТюмГУ", "тюмгу", "UTMN"],
)
def test_object_is_found_in_any_form(matcher, phrase):
    _, stats = stats_for(matcher, "Новость дня", f"Событие произошло при участии {phrase}.")
    assert stats.strong == 1


def test_university_word_counts_only_after_object_is_named(matcher):
    _, unnamed = stats_for(matcher, "Новость", "Университет открыл новый курс.")
    assert unnamed.total == 0 and unnamed.target_sentences == []

    _, named = stats_for(matcher, "Новость", "ТюмГУ открыл курс. В городе дождь. Университет доволен.")
    assert named.target_sentences == [0, 2]


@pytest.mark.parametrize(
    "title, text, label",
    [
        ("Студенты ТюмГУ победили на олимпиаде", "Команда заняла первое место и получила награду.", "positive"),
        ("Прокуратура выявила нарушения в ТюмГУ", "Возбуждено уголовное дело, идут обыски.", "negative"),
        ("ТюмГУ опубликовал расписание", "Занятия начнутся в понедельник в обычном режиме.", "neutral"),
    ],
)
def test_sentiment_labels(title, text, label):
    assert analyze_sentiment(parse_document(title, text)).label == label


def test_negation_changes_sentiment():
    plain = analyze_sentiment(parse_document("Проверка", "В работе вуза выявлены нарушения."))
    negated = analyze_sentiment(parse_document("Проверка", "Нарушений не выявлено."))
    assert plain.score < 0 <= negated.score


def test_sentiment_focuses_on_object_sentences():
    document = parse_document("Новости города", "В городе произошла авария и пожар. ТюмГУ открыл новую лабораторию.")
    assert analyze_sentiment(document, [1]).score > analyze_sentiment(document).score


def test_sentiment_evidence_explains_score_without_repeats():
    result = analyze_sentiment(parse_document("Скандал в вузе", "Скандал вызвал возмущение."))
    words = [item["word"] for item in result.evidence]
    assert "скандал" in words and len(words) == len(set(words))


def test_relevance_keeps_publication_about_object(matcher):
    document, stats = stats_for(matcher, "ТюмГУ открыл лабораторию", "Тюменский государственный университет открыл лабораторию.")
    assert check_relevance(document, stats, matcher).is_relevant


def test_relevance_keeps_expert_comment(matcher):
    text = "Эксперты обсудили рынок. Профессор ТюмГУ пояснил ситуацию. Обзор выйдет в ноябре."
    document, stats = stats_for(matcher, "Обзор рынка", text)
    assert check_relevance(document, stats, matcher).is_relevant


@pytest.mark.parametrize(
    "title, text, reason",
    [
        ("Анонс: день открытых дверей в ТюмГУ", "Приглашаем школьников. Регистрация на сайте.", "анонс"),
        ("На улице возле ТюмГУ перекроют движение", "Автобусы пойдут в объезд.", "ориентир"),
        ("Выпускник ТюмГУ открыл кофейню", "Он окончил ТюмГУ и уехал в Москву.", "биограф"),
        ("Тюменский вуз готовит буровиков", "Индустриальный университет запустил программу.", "другой организации"),
    ],
)
def test_relevance_removes_random_publications(matcher, title, text, reason):
    document, stats = stats_for(matcher, title, text)
    result = check_relevance(document, stats, matcher)
    assert not result.is_relevant
    assert any(reason in item for item in result.reasons)


def test_number_with_word_around_is_not_a_landmark(matcher):
    title, text = "Выставка в городе", "Около 600 студентов ТюмГУ посетили выставку."
    document, stats = stats_for(matcher, title, text)
    assert check_relevance(document, stats, matcher).is_relevant


def test_main_role(matcher):
    title, text = "ТюмГУ вошёл в рейтинг", "Тюменский госуниверситет улучшил позиции. Ректор ТюмГУ поблагодарил коллектив."
    document, stats = stats_for(matcher, title, text)
    result = determine_role(extract_entities(title, text), stats, matcher)
    assert result.role == "main" and result.main_entity == "ТюмГУ"


def test_episodic_role_names_other_main_entity(matcher):
    title = "Газпром нефть расширяет добычу"
    text = "Компания Газпром нефть открыла месторождение. Газпром нефть вложит миллиарды. Комментарий дал профессор ТюмГУ. Работы начнутся весной."
    document, stats = stats_for(matcher, title, text)
    result = determine_role(extract_entities(title, text), stats, matcher)
    assert result.role == "episodic" and "Газпром" in result.main_entity


def test_entities_are_normalized_and_counted():
    entities = extract_entities("Встреча в Тюмени", "Губернатор Иван Петров приехал в Тюмень. Иван Петров выступил.")
    by_name = {item["name"]: item for item in entities}
    assert by_name["Иван Петров"]["type"] == "PER" and by_name["Иван Петров"]["count"] == 2
    assert by_name["Тюмень"]["type"] == "LOC" and by_name["Тюмень"]["in_title"]


@pytest.mark.parametrize(
    "title, text, topic",
    [
        ("Учёные получили патент", "Исследование опубликовано в научном журнале.", "science"),
        ("Итоги приёмной кампании", "Абитуриенты подали заявления, балл ЕГЭ вырос.", "admission"),
        ("Прокуратура начала проверку", "Выявлены нарушения, произошла утечка данных.", "incidents"),
    ],
)
def test_topic_classification(title, text, topic):
    assert classify_topic(title, text)[0] == topic


def test_reprint_is_found_and_earliest_is_original():
    text = "Прокуратура выявила нарушения при закупке лабораторного оборудования, контракты заключены с завышением цен."
    items = [
        DedupItem(2, content_lemmas(text + " Вуз сотрудничает с проверяющими."), datetime(2026, 9, 2), 0.6),
        DedupItem(1, content_lemmas(text), datetime(2026, 9, 1), 1.0),
        DedupItem(3, content_lemmas("Студенты выиграли шахматный турнир среди вузов округа."), datetime(2026, 9, 1), 0.3),
    ]
    assert find_duplicates(items) == {2: 1}


def test_same_text_a_month_later_is_not_a_duplicate():
    lemmas = content_lemmas("Университет объявил набор на программу магистратуры по экологии и климату.")
    items = [DedupItem(1, lemmas, datetime(2026, 8, 1), 1.0), DedupItem(2, lemmas, datetime(2026, 10, 1), 1.0)]
    assert find_duplicates(items) == {}


def test_clustering_small_selection_is_one_cluster():
    items = [ClusterInput(index, f"Новость {index}", ["слово", "тема"], "science", [0.0] * 10) for index in range(3)]
    assignment, clusters = cluster_publications(items)
    assert set(assignment.values()) == {0} and clusters[0]["size"] == 3
    assert cluster_publications([]) == ({}, [])


def test_conclusions_name_all_topics_with_equal_negative():
    data = {
        "kept": 81,
        "sentiment": {"positive": 23, "neutral": 45, "negative": 13},
        "tone_index": 12.3,
        "topics": [
            {"name": "Наука", "count": 30, "negative": 5},
            {"name": "Кампус", "count": 20, "negative": 5},
            {"name": "Прочее", "count": 31, "negative": 3},
        ],
        "influential": 0,
        "negative": 13,
    }
    text = " ".join(metrics.build_conclusions(data, "ТюмГУ"))
    assert "«Наука», «Кампус»: негативных публикаций 5" in text
    assert "81 публикаций" not in text


def test_reputation_weight_grows_with_authority_and_reprints():
    small = metrics.reputation_weight(0.3, "episodic", -0.3, 0)
    large = metrics.reputation_weight(1.0, "main", -0.9, 3)
    assert small < 60 <= large <= 100
