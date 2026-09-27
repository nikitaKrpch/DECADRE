"""Server-side French lemmatization and rule matching for the writer."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import spacy


DEFAULT_RULES = Path(__file__).resolve().parent / "rules.json"
_WORD = re.compile(r"[\wÀ-ÖØ-öø-ÿ]+(?:['’]|\*)?", re.UNICODE)
_ELISION_LEMMAS = {
    "c'": "ce",
    "d'": "de",
    "j'": "je",
    "l'": "le",
    "m'": "me",
    "n'": "ne",
    "qu'": "que",
    "s'": "se",
    "t'": "te",
}


@lru_cache(maxsize=1)
def load_nlp():
    """Load the French model once per worker process."""
    return spacy.load("fr_core_news_sm")


def load_rules(path: Path = DEFAULT_RULES) -> list[dict[str, Any]]:
    """Load the shared rules generated from Rule_Review.xlsx."""
    return json.loads(path.read_text(encoding="utf-8"))


def _lemma(value: str) -> str:
    value = value.lower().strip().replace("’", "'")
    value = "".join(character for character in unicodedata.normalize("NFD", value) if unicodedata.category(character) != "Mn")
    return _ELISION_LEMMAS.get(value, value)


def _pattern_tokens(pattern: str) -> list[str]:
    return [_lemma(match.group()) for match in _WORD.finditer(pattern)]


def _matches(pattern_token: str, text_token: str) -> bool:
    if pattern_token.endswith("*"):
        return text_token.startswith(pattern_token[:-1])
    if pattern_token == text_token:
        return True
    if pattern_token.endswith("al"):
        stem = pattern_token[:-2]
        return text_token in {pattern_token + "s", pattern_token + "e", pattern_token + "es", stem + "aux"}
    if pattern_token.endswith("er"):
        stem = pattern_token[:-2]
        return text_token in {
            stem + ending
            for ending in ("e", "es", "ent", "er", "era", "erait", "ait", "ais", "ai", "ant", "ons", "ez")
        }
    return text_token in {pattern_token + "s", pattern_token + "e", pattern_token + "es", pattern_token + "x"}


def _quote_ranges(text: str) -> list[tuple[int, int]]:
    ranges = []
    opener = None
    start = -1
    pairs = {"«": "»", "“": "”", '"': '"'}
    for index, character in enumerate(text):
        if opener is None and character in pairs:
            opener = pairs[character]
            start = index
        elif opener is not None and character == opener:
            ranges.append((start, index + 1))
            opener = None
            start = -1
    if start != -1:
        ranges.append((start, len(text)))
    return ranges


def _in_quote(ranges: list[tuple[int, int]], position: int) -> bool:
    return any(start <= position < end for start, end in ranges)


def find_issues(text: str, rules: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Lemmatize text and return UI-compatible issues with original spans."""
    if not isinstance(text, str) or not text:
        return []

    rules = load_rules() if rules is None else rules
    document = load_nlp()(text)
    tokens = [token for token in document if not token.is_space and not token.is_punct]
    token_forms = [(_lemma(token.lemma_), _lemma(token.text)) for token in tokens]
    quotes = _quote_ranges(text)
    found = []

    for rule in rules:
        for pattern in rule.get("patterns", []):
            pattern_tokens = _pattern_tokens(str(pattern))
            if not pattern_tokens or len(pattern_tokens) > len(tokens):
                continue
            for start_index in range(len(tokens) - len(pattern_tokens) + 1):
                end_index = start_index + len(pattern_tokens)
                if not all(
                    any(_matches(expected, actual) for actual in token_forms[index])
                    for expected, index in zip(pattern_tokens, range(start_index, end_index))
                ):
                    continue
                start = tokens[start_index].idx
                end = tokens[end_index - 1].idx + len(tokens[end_index - 1].text)
                found.append(
                    {
                        "key": f"{rule.get('id', '')}:{start}",
                        "ruleId": rule.get("id", ""),
                        "start": start,
                        "end": end,
                        "match": text[start:end],
                        "severity": "hint" if rule.get("severity") == "hint" else "strong",
                        "replacements": rule.get("replacements", []),
                        "reason": rule.get("reason", ""),
                        "source": rule.get("source", ""),
                        "category": rule.get("category", ""),
                        "inQuote": _in_quote(quotes, start),
                        "origin": "rules",
                    }
                )

    found.sort(key=lambda issue: (issue["start"], -(issue["end"] - issue["start"])))
    output = []
    last_end = -1
    for issue in found:
        if issue["start"] >= last_end:
            output.append(issue)
            last_end = issue["end"]
    return output
