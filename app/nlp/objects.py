"""Поиск упоминаний объекта мониторинга с учётом падежей.

Псевдонимы делятся на сильные («ТюмГУ») и слабые («тюменский вуз» — так могут
назвать и другой вуз). Ссылки вроде «университет» считаются упоминанием только
там, где объект уже назван: они нужны, чтобы найти предложения про него.
"""
from dataclasses import dataclass, field

from app.nlp.text import ParsedDocument, lemmatize, word_spans

LEAD_SENTENCES = 2


@dataclass
class MentionStats:
    strong: int = 0
    weak: int = 0
    in_title: bool = False
    in_lead: bool = False
    named_sentences: list[int] = field(default_factory=list)
    target_sentences: list[int] = field(default_factory=list)
    total_sentences: int = 0

    @property
    def total(self) -> int:
        return self.strong + self.weak

    @property
    def share(self) -> float:
        return len(self.named_sentences) / self.total_sentences if self.total_sentences else 0.0


def _count(sequence: list[str], pattern: tuple[str, ...]) -> int:
    size = len(pattern)
    return sum(1 for start in range(len(sequence) - size + 1) if tuple(sequence[start : start + size]) == pattern)


class ObjectMatcher:
    def __init__(self, object_id, name, aliases=(), weak_aliases=(), references=(), other_organizations=()):
        self.object_id = object_id
        self.name = name
        self.aliases = [tuple(lemmatize(item)) for item in aliases]
        self.weak_aliases = [tuple(lemmatize(item)) for item in weak_aliases]
        self.references = [tuple(lemmatize(item)) for item in references]
        self.other_organizations = [tuple(lemmatize(item)) for item in other_organizations]
        self.alias_texts = {" ".join(item) for item in self.aliases + self.weak_aliases}

    @classmethod
    def from_model(cls, item) -> "ObjectMatcher":
        return cls(item.id, item.name, item.aliases, item.weak_aliases, item.references, item.other_organizations)

    def match(self, document: ParsedDocument) -> MentionStats:
        stats = MentionStats(total_sentences=len(document.sentence_lemmas))
        strong_title = sum(_count(document.title_lemmas, item) for item in self.aliases)
        weak_title = sum(_count(document.title_lemmas, item) for item in self.weak_aliases)
        stats.strong = strong_title
        stats.weak = weak_title
        stats.in_title = bool(strong_title or weak_title)

        named: list[int] = []
        for index, sentence in enumerate(document.sentence_lemmas):
            strong = sum(_count(sentence, item) for item in self.aliases)
            weak = sum(_count(sentence, item) for item in self.weak_aliases)
            stats.strong += strong
            stats.weak += weak
            if strong or weak:
                named.append(index)
                if index < LEAD_SENTENCES:
                    stats.in_lead = True

        stats.named_sentences = named
        targets = set(named)
        if stats.total:
            # Если объект назван, «университет» и «вуз» дальше по тексту — про него же.
            for index, sentence in enumerate(document.sentence_lemmas):
                if any(_count(sentence, item) for item in self.references):
                    targets.add(index)
        stats.target_sentences = sorted(targets)
        return stats

    def positions(self, lemmas: list[str]) -> list[int]:
        """Индексы, с которых в списке лемм начинается название объекта."""
        return [
            start
            for pattern in self.aliases + self.weak_aliases
            for start in range(len(lemmas) - len(pattern) + 1)
            if tuple(lemmas[start : start + len(pattern)]) == pattern
        ]

    def find_spans(self, text: str) -> list[dict]:
        """Где в исходном тексте стоит название объекта: позиции символов и сила псевдонима."""
        tokens = word_spans(text)
        lemmas = [token[2] for token in tokens]
        spans = []
        for strength, patterns in (("strong", self.aliases), ("weak", self.weak_aliases)):
            for pattern in patterns:
                for start in self._starts(lemmas, pattern):
                    spans.append({"start": tokens[start][0], "end": tokens[start + len(pattern) - 1][1], "strength": strength})
        return sorted(spans, key=lambda span: span["start"])

    @staticmethod
    def _starts(lemmas: list[str], pattern: tuple[str, ...]) -> list[int]:
        size = len(pattern)
        return [start for start in range(len(lemmas) - size + 1) if tuple(lemmas[start : start + size]) == pattern]

    def other_organization_hits(self, document: ParsedDocument) -> int:
        lemmas = document.all_lemmas
        return sum(_count(lemmas, item) for item in self.other_organizations)
