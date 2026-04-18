"""Meal-text normalization.

The free-text field in the CSV looks like:
    "Ate a sandwich with ham, cheese, and mustard for lunch."
    "Drank a cappuccino after lunch."

The API works best with short food phrases ("sandwich with ham cheese mustard",
"cappuccino"), so we strip verbs and time-of-day context. The normalized form
is ALSO the cache key, which is why we want it to be aggressive and stable:
small wording differences ("Had a..." vs "Ate a...") should collapse to the
same key and share one API call.

This module is intentionally regex-only (no NLP) — "good enough" per the
assignment — but is structured so it can be swapped for a smarter parser
(spaCy, LLM) without touching callers.
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
    """Clean a free-text meal description into a stable query string.

    The output is used both as the API query and as the cache key, so two
    semantically equivalent inputs MUST produce the same output.
    """
    if not raw_text:
        return ""

    text = raw_text.strip().lower()

    text = _LEADING_RE.sub("", text).strip()
    text = _TRAILING_RE.sub("", text).strip()

    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()

    return text


if __name__ == "__main__":
    samples = [
        "Had a grilled chicken breast with quinoa for lunch.",
        "Drank a cappuccino after lunch.",
        "Ate a sandwich with ham, cheese, and mustard for lunch.",
        "Drank water throughout the day.",
        "A pasta primavera for dinner.",
        "Drank a hot cup of mulled wine on a cold evening.",
    ]
    for s in samples:
        print(f"{s!r:70s} -> {normalize_meal_text(s)!r}")
