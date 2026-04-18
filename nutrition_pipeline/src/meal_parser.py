"""Deterministic normalization of free-text meal descriptions.

The CSV contains phrases like "Ate a sandwich with ham, cheese, and mustard
for lunch." The nutrition API works best with the food phrase alone
("sandwich with ham cheese mustard"), so we strip leading verbs and trailing
meal-context phrases.

The normalized output is also the cache key, so it must be stable: small
wording differences ("Had a..." vs "Ate a...") should collapse to the same
key and share one API call.

Regex-only by design ("good enough" per the assignment); structured so it
can be swapped for an NLP/LLM parser without touching callers.
"""

from __future__ import annotations

import re

_LEADING_PATTERNS = [
    r"had an ",
    r"had a ",
    r"ate an ",
    r"ate a ",
    r"drank an ",
    r"drank a ",
    r"had ",
    r"ate ",
    r"drank ",
]

_TRAILING_PATTERNS = [
    r"as a starter for dinner",
    r"alongside my breakfast",
    r"after my morning jog",
    r"on a cold evening",
    r"throughout the day",
    r"when i woke up",
    r"after my workout",
    r"in the afternoon",
    r"in the morning",
    r"in the evening",
    r"during dinner",
    r"after dinner",
    r"after lunch",
    r"for breakfast",
    r"at breakfast",
    r"with dinner",
    r"with lunch",
    r"for dinner",
    r"for lunch",
    r"at dinner",
    r"at lunch",
    r"at noon",
]

_LEADING_RE = re.compile(r"^(?:" + "|".join(_LEADING_PATTERNS) + r")", re.IGNORECASE)
_TRAILING_RE = re.compile(r"(?:" + "|".join(_TRAILING_PATTERNS) + r")\s*\.?\s*$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_meal_text(raw_text: str) -> str:
    """Reduce a free-text meal description to a stable query / cache key."""
    if not raw_text:
        return ""

    text = raw_text.strip().lower()
    text = text.replace("&", " and ")

    text = _LEADING_RE.sub("", text).strip()
    text = _TRAILING_RE.sub("", text).strip()

    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()

    return text
