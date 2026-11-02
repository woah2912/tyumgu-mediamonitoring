"""Классификатор релевантности: публикация действительно про объект или случайна.

Это прозрачная балльная модель, а не обучаемая: на реальных данных разметки нет,
а единое правило можно объяснить и проверить. Каждый признак даёт баллы или штраф,
публикация с итогом ниже порога считается случайной, причины показываются в отчёте.
"""
import re
from dataclasses import dataclass, field

from app import rules
from app.nlp.objects import MentionStats, ObjectMatcher
from app.nlp.text import ParsedDocument

_ANNOUNCEMENT_STRONG = {"анонс", "афиша"}
_ANNOUNCEMENT_WEAK = {"приглашать", "приглашение", "состояться", "регистрация", "вход", "билет", "расписание"}

# Слова перед названием, превращающие объект в ориентир на местности: «возле ТюмГУ».
_LANDMARK = {"возле", "напротив", "рядом", "неподалеку", "недалеко", "мимо"}
_LANDMARK_WINDOW = 4
# Единственное число: «выпускник ТюмГУ возглавил…» — про человека, «выпускники» — про вуз.
_BIOGRAPHY = re.compile(r"\b(выпускни(к|ца)(а|у|е|ом|ей)?|окончил\w*|закончил\w*)\b", re.IGNORECASE)


@dataclass
class RelevanceResult:
    score: float
    is_relevant: bool
    reasons: list[str] = field(default_factory=list)


def _is_announcement(document: ParsedDocument) -> bool:
    lemmas = set(document.title_lemmas)
    for sentence in document.sentence_lemmas:
        lemmas.update(sentence)
    if lemmas & _ANNOUNCEMENT_STRONG:
        return True
    return len(lemmas & _ANNOUNCEMENT_WEAK) >= 2


def _named_contexts(document: ParsedDocument, stats: MentionStats) -> list[tuple[str, list[str]]]:
    """Заголовок и предложения, где объект назван прямо: текст и леммы."""
    contexts = [(document.title, document.title_lemmas)] if stats.in_title else []
    contexts += [(document.sentences[index], document.sentence_lemmas[index]) for index in stats.named_sentences]
    return contexts


def _is_landmark(lemmas: list[str], matcher: ObjectMatcher) -> bool:
    return any(
        _LANDMARK & set(lemmas[max(0, position - _LANDMARK_WINDOW) : position])
        for position in matcher.positions(lemmas)
    )


def check_relevance(document: ParsedDocument, stats: MentionStats, matcher: ObjectMatcher) -> RelevanceResult:
    score = rules.RELEVANCE_BASE_STRONG if stats.strong else rules.RELEVANCE_BASE_WEAK
    reasons: list[str] = []

    if stats.in_title:
        score += rules.RELEVANCE_TITLE
    if stats.in_lead:
        score += rules.RELEVANCE_LEAD
    score += min(rules.RELEVANCE_PER_MENTION * max(stats.total - 1, 0), rules.RELEVANCE_MENTION_CAP)
    score += min(rules.RELEVANCE_SHARE_FACTOR * stats.share, rules.RELEVANCE_SHARE_CAP)

    if _is_announcement(document):
        score -= rules.PENALTY_ANNOUNCEMENT
        reasons.append("анонс мероприятия")

    other_hits = matcher.other_organization_hits(document)
    if other_hits and (not stats.strong or other_hits > stats.strong):
        score -= rules.PENALTY_OTHER_ORGANIZATION
        reasons.append("речь идёт о другой организации")

    if stats.total <= 3:
        contexts = _named_contexts(document, stats)
        if contexts and all(_is_landmark(lemmas, matcher) for _, lemmas in contexts):
            score = min(score, rules.RELEVANCE_INCIDENTAL_CAP)
            reasons.append("объект упомянут как ориентир на местности")
        elif contexts and all(_BIOGRAPHY.search(text) for text, _ in contexts):
            score = min(score, rules.RELEVANCE_INCIDENTAL_CAP)
            reasons.append("упоминание только в биографии персоны")
        elif contexts and all(text.count(",") >= 3 for text, _ in contexts):
            score -= rules.PENALTY_LIST_MENTION
            reasons.append("объект упомянут в перечислении")

    score = round(max(0.0, min(score, 1.0)), 3)
    return RelevanceResult(score=score, is_relevant=score >= rules.RELEVANCE_THRESHOLD, reasons=reasons)
