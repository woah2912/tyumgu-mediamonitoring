"""Базовая обработка текста: предложения, токены, леммы."""
import html
import re
from dataclasses import dataclass
from functools import lru_cache

import pymorphy3
from razdel import sentenize

_morph = pymorphy3.MorphAnalyzer()
_WORD = re.compile(r"[а-яёa-z0-9]+(?:-[а-яёa-z0-9]+)*", re.IGNORECASE)

STOPWORDS = frozenset(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне
    было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до
    вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя
    их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого
    какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно
    при наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве
    три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда
    конечно всю между это который также свой весь наш ваш сказать заявить отметить рассказать сообщить
    год время новый также однако кроме например являться стать мочь очень самый
    """.split()
)


@lru_cache(maxsize=300_000)
def lemma(word: str) -> str:
    return _morph.parse(word.lower().replace("ё", "е"))[0].normal_form.replace("ё", "е")


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def word_spans(text: str) -> list[tuple[int, int, str]]:
    """Слова с позициями в исходном тексте и леммами: нужны для подсветки находок."""
    return [(match.start(), match.end(), lemma(match.group())) for match in _WORD.finditer(text)]


def lemmatize(text: str) -> list[str]:
    return [lemma(word) for word in words(text)]


def content_lemmas(text: str) -> list[str]:
    """Леммы без служебных слов и чисел — для тематики, кластеров и дубликатов."""
    return [item for item in lemmatize(text) if len(item) > 2 and item not in STOPWORDS and not item.isdigit()]


def split_sentences(text: str) -> list[str]:
    return [item.text.strip() for item in sentenize(text) if item.text.strip()]


@dataclass
class ParsedDocument:
    title: str
    text: str
    sentences: list[str]
    title_lemmas: list[str]
    sentence_lemmas: list[list[str]]

    @property
    def all_lemmas(self) -> list[str]:
        result = list(self.title_lemmas)
        for sentence in self.sentence_lemmas:
            result.extend(sentence)
        return result

    @property
    def full_text(self) -> str:
        return f"{self.title}. {self.text}"


def parse_document(title: str, text: str) -> ParsedDocument:
    # Агрегаторы присылают заголовок вместо текста: второй раз его считать нельзя.
    sentences = [] if text.strip() == title.strip() else split_sentences(text)
    return ParsedDocument(
        title=title,
        text=text,
        sentences=sentences,
        title_lemmas=lemmatize(title),
        sentence_lemmas=[lemmatize(sentence) for sentence in sentences],
    )


def clean_text(text: str) -> str:
    # Сначала разбираем сущности: в лентах теги бывают записаны как &lt;a&gt;.
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    text = text.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()
