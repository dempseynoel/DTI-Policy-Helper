"""The user turn is untrusted. The retrieved wording is not (it's our own documents).

Minimum viable input handling. The real defence is the output check in figures.py, which
holds however the model was manipulated.
"""

from __future__ import annotations

import re
import unicodedata

MAX_QUESTION_CHARS = 2000
_DELIMITER = re.compile(r"</?\s*question\s*>", re.IGNORECASE)


class RejectedInput(ValueError):
    pass


def clean_question(text: str) -> str:
    """Normalise, strip control characters, cap the length, and neutralise the <question>
    delimiter so pasted text can't close it and pose as instructions."""
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = _DELIMITER.sub("", text).strip()
    if not text:
        raise RejectedInput("the question is empty")
    if len(text) > MAX_QUESTION_CHARS:
        raise RejectedInput(
            f"the question is longer than {MAX_QUESTION_CHARS} characters; "
            "paste only what's needed to find the clause"
        )
    return text
