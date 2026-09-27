"""Extract text from one policy-wording PDF and clean it.

Handles the extraction artefacts found in the real files:

1. A running footer on every page after the cover. Harvested for its status (a cross-check),
   then removed.
2. Bullets extracted as a lone "–" line, divorced from their text. Rejoined.
3. The contents page repeating every "Section N — Title" heading. Pages 1–3 (cover, document
   control, contents) are never searched for section starts.
4. Sections spanning page breaks. The body is one list of lines, each tagged with its page.
5. The 2023 v1.1 footer extracting as "Status: SUPERSEDEDEffective 1 July 2023".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pymupdf

from dti_rag.models import Status

BODY_FIRST_PAGE = 4  # 1 = cover, 2 = document control, 3 = contents
BULLET = "–"

_FOOTER_PATTERNS = [
    re.compile(r"^DAVIDSTOWN INSURANCE$"),
    re.compile(r"^HomeShield Home Insurance\s+—\s+\d{4} Edition$"),
    re.compile(r"^DTI-HOME-PW-\S+\s+\|\s+Version .*\|\s+Status:"),
    re.compile(r"^Effective \d{1,2} [A-Z][a-z]+ \d{4}$"),
    re.compile(r"^Page \d+ of \d+$"),
]
# Non-greedy, and stops before a glued-on "Effective": "SUPERSEDEDEffective" -> "SUPERSEDED".
_FOOTER_STATUS = re.compile(r"Status:\s*([A-Z]+?)(?=Effective|\s*$)")
_END_OF_WORDING = re.compile(r"^End of policy wording\.")

CONTROL_FIELDS = (
    "Document reference",
    "Product",
    "Edition year",
    "Version",
    "Status",
    "Date published",
    "Effective from",
    "Effective to",
    "Supersedes",
    "Superseded by",
)


@dataclass(frozen=True)
class Line:
    text: str
    page: int


@dataclass
class ParsedDocument:
    doc_id: str
    edition_year: int
    version: str
    status: Status
    published: date
    effective_from: date
    effective_to: date
    supersedes: str | None
    superseded_by: str | None
    footer_status: str
    control_fields: dict[str, str]
    control_notes: list[str]  # the prose and change summary on the control page
    body: list[Line] = field(default_factory=list)


def parse_long_date(text: str) -> date:
    """'1 January 2024' -> date(2024, 1, 1)."""
    return datetime.strptime(text.strip(), "%d %B %Y").date()


def _is_footer(line: str) -> bool:
    return any(p.match(line) for p in _FOOTER_PATTERNS)


def rejoin_bullets(lines: list[str]) -> list[str]:
    """['–', 'a fixed water tank...'] -> ['– a fixed water tank...']."""
    out: list[str] = []
    pending_bullet = False
    for line in lines:
        if line == BULLET:
            pending_bullet = True
            continue
        out.append(f"{BULLET} {line}" if pending_bullet else line)
        pending_bullet = False
    return out


def _page_lines(page: pymupdf.Page) -> list[str]:
    return [ln.strip() for ln in page.get_text().splitlines() if ln.strip()]


def _footer_status(pages: list[list[str]]) -> str:
    for lines in pages:
        for line in lines:
            match = _FOOTER_STATUS.search(line) if line.startswith("DTI-HOME-PW-") else None
            if match:
                return match.group(1)
    raise ValueError("no footer status found")


def _parse_control_page(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    fields: dict[str, str] = {}
    notes_start = 0
    for i, line in enumerate(lines):
        if line in CONTROL_FIELDS and i + 1 < len(lines) and line not in fields:
            fields[line] = lines[i + 1]
            notes_start = i + 2
    missing = [f for f in CONTROL_FIELDS if f not in fields]
    if missing:
        raise ValueError(f"document control page is missing {missing}")
    notes = [ln for ln in lines[notes_start:] if not _is_footer(ln)]
    return fields, rejoin_bullets(notes)


def parse_pdf(path: Path) -> ParsedDocument:
    with pymupdf.open(path) as pdf:
        pages = [_page_lines(page) for page in pdf]

    fields, notes = _parse_control_page(pages[1])
    superseded_by = fields["Superseded by"]
    doc = ParsedDocument(
        doc_id=fields["Document reference"],
        edition_year=int(fields["Edition year"]),
        version=fields["Version"],
        status=Status(fields["Status"].upper()),
        published=parse_long_date(fields["Date published"]),
        effective_from=parse_long_date(fields["Effective from"]),
        effective_to=parse_long_date(fields["Effective to"]),
        supersedes=fields["Supersedes"] or None,
        superseded_by=None if superseded_by.startswith("None") else superseded_by,
        footer_status=_footer_status(pages[1:]),
        control_fields=fields,
        control_notes=notes,
    )

    for page_number, lines in enumerate(pages, start=1):
        if page_number < BODY_FIRST_PAGE:
            continue
        kept = [ln for ln in lines if not _is_footer(ln) and not _END_OF_WORDING.match(ln)]
        doc.body.extend(Line(text, page_number) for text in kept)

    # Rejoin bullets across the whole body: a bullet glyph can end one page and its text
    # start the next.
    joined: list[Line] = []
    pending: Line | None = None
    for line in doc.body:
        if line.text == BULLET:
            pending = line
            continue
        joined.append(Line(f"{BULLET} {line.text}", pending.page) if pending else line)
        pending = None
    doc.body = joined
    return doc
