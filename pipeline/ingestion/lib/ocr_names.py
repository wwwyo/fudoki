"""Exact, declared corrections for extracted names; never rewrite raw OCR."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def _key(name: str) -> str:
    return "".join(unicodedata.normalize("NFKC", name).split())


@dataclass(frozen=True)
class NameRule:
    id: str
    observed_name: str
    corrected_name: str
    reason: str


@dataclass(frozen=True)
class NameDictionary:
    sha256: str
    rules: tuple[NameRule, ...]

    def __post_init__(self) -> None:
        keys: set[str] = set()
        ids: set[str] = set()
        for rule in self.rules:
            if not all(isinstance(value, str) and value.strip() for value in
                       (rule.id, rule.observed_name, rule.corrected_name, rule.reason)):
                raise ValueError("Name rules require nonempty id, names and reason")
            key = _key(rule.observed_name)
            # A name dictionary must not turn a printed amount into another value.
            if not any(char.isalpha() for char in key):
                raise ValueError("A name rule must contain a letter")
            if key in keys or rule.id in ids:
                raise ValueError("Duplicate rule id or normalized observed name")
            keys.add(key)
            ids.add(rule.id)


def load_name_dictionary(path: Path) -> NameDictionary:
    """Load a versioned, caller-selected dictionary. No fuzzy/substring rules."""
    body = Path(path).read_bytes()
    data = json.loads(body)
    if data.get("schema_version") != 1 or data.get("normalization") != "NFKC_REMOVE_WHITESPACE":
        raise ValueError("Unsupported name dictionary schema or normalization")
    return NameDictionary(
        hashlib.sha256(body).hexdigest(),
        tuple(NameRule(**entry) for entry in data["rules"]),
    )


def correct_name(raw_name: str, dictionary: NameDictionary) -> dict:
    """Correct a whole logical name once; keep raw text and the applied rule."""
    if not isinstance(raw_name, str):
        raise TypeError("raw_name must be a string")
    rule = next((rule for rule in dictionary.rules if _key(rule.observed_name) == _key(raw_name)), None)
    return {
        "raw_name": raw_name,
        "corrected_name": rule.corrected_name if rule else raw_name,
        "rule_id": rule.id if rule else None,
        "reason": rule.reason if rule else None,
        "dictionary_sha256": dictionary.sha256,
        "normalization": "NFKC_REMOVE_WHITESPACE",
    }


def correct_name_preserving_layout(raw_name: str, dictionary: NameDictionary) -> dict:
    """Match a whole logical name and preserve spacing when glyphs align.

    The caller owns separation of printed numbers from a confirmed name field.
    Length-changing rules return the declared complete name; they do not guess
    insertion positions inside the original wrapped label.
    """
    result = correct_name(raw_name, dictionary)
    if result['rule_id'] is None:
        return {**result, 'layout_policy': 'unchanged'}
    corrected = _key(result['corrected_name'])
    characters = [char for char in raw_name if not char.isspace()]
    if (len(characters) != len(corrected)
            or any(len(unicodedata.normalize('NFKC', char)) != 1 for char in characters)):
        return {**result, 'layout_policy': 'declared-name-length-change'}
    replacements = iter(corrected)
    output = []
    for char in raw_name:
        if char.isspace():
            output.append(char)
        else:
            replacement = next(replacements)
            output.append(char if unicodedata.normalize('NFKC', char) == replacement else replacement)
    return {**result, 'corrected_name': ''.join(output), 'layout_policy': 'preserve-whitespace-and-unchanged-glyphs'}
