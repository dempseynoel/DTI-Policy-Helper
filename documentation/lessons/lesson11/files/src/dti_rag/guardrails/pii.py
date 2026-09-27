"""Redact personal data before anything is logged.

Claims context contains names, addresses, contact details and sometimes health information.
The audit log (Lesson 13) is a personal-data store: redact first, log second.

Pattern-based redaction catches structured identifiers. It cannot find names. For real
claims data, add Azure AI Language PII detection (on the same Foundry resource) and record
the decision in GUARDRAILS.md.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    (
        "NI_NUMBER",
        re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.IGNORECASE),
    ),
    ("PHONE", re.compile(r"(?:\+44\s?|\b0)(?:\d\s?){9,10}\b")),
    ("POSTCODE", re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b", re.IGNORECASE)),
    ("REFERENCE", re.compile(r"\b[A-Z]{2,4}-?\d{6,10}\b")),
]


def redact(text: str) -> str:
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    return text
