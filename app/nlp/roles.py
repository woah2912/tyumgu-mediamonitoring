"""Определение главной роли: кто главный герой публикации и какова роль объекта."""
from dataclasses import dataclass

from app.nlp.objects import MentionStats, ObjectMatcher
from app.nlp.text import lemmatize

_ACTOR_TYPES = {"ORG", "PER"}


@dataclass
class RoleResult:
    role: str          # main | secondary | episodic
    main_entity: str   # название главного объекта публикации


def _prominence(count: int, in_title: bool, in_lead: bool = False) -> float:
    return count + (3.0 if in_title else 0.0) + (1.0 if in_lead else 0.0)


def _belongs_to_object(name: str, matcher: ObjectMatcher) -> bool:
    return " ".join(lemmatize(name)) in matcher.alias_texts


def determine_role(entities: list[dict], stats: MentionStats, matcher: ObjectMatcher) -> RoleResult:
    object_score = _prominence(stats.total, stats.in_title, stats.in_lead)

    best_name, best_score = matcher.name, -1.0
    for entity in entities:
        if entity["type"] not in _ACTOR_TYPES or _belongs_to_object(entity["name"], matcher):
            continue
        score = _prominence(entity["count"], entity["in_title"])
        if score > best_score:
            best_name, best_score = entity["name"], score

    object_leads = object_score >= best_score
    main_entity = matcher.name if object_leads else best_name

    if object_leads and (stats.in_title or stats.in_lead) and stats.total >= 2:
        role = "main"
    elif stats.in_title and not stats.total_sentences:
        role = "main"  # есть только заголовок, и объект в нём
    elif stats.in_title and stats.total >= 2:
        role = "main"
    elif stats.total == 1 and not stats.in_title and not stats.in_lead:
        role = "episodic"
    elif stats.total == 1 and stats.share < 0.2:
        role = "episodic"
    else:
        role = "secondary"
    return RoleResult(role=role, main_entity=main_entity)
