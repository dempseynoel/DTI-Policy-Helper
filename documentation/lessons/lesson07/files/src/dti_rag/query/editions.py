"""The edition registry: which editions are held, and which one governs a given date.

Pure, deterministic, offline. A decision with exactly one defensible answer belongs in code,
not in a model.

Reads only the edition columns of the fact matrix (doc_id, year, version, status, dates).
Those columns are verified against every PDF's document-control page by a Lesson 03 test;
the fact columns, which carry the DTI-014 trap, are never read here.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from dti_rag.config import REPO_ROOT
from dti_rag.models import Status

EDITIONS_CSV = REPO_ROOT / "data" / "fact_matrix" / "editions_fact_matrix.csv"


class NoEditionInForce(LookupError):
    """The date falls outside every edition the corpus holds."""


@dataclass(frozen=True, order=True)
class Edition:
    effective_from: date
    effective_to: date
    doc_id: str
    edition_year: int
    version: str
    status: Status
    supersedes: str | None

    def covers(self, day: date) -> bool:
        return self.effective_from <= day <= self.effective_to

    @property
    def label(self) -> str:
        return f"{self.edition_year} edition v{self.version} ({self.doc_id})"

    @property
    def in_force(self) -> str:
        return f"in force {_long(self.effective_from)} to {_long(self.effective_to)}"


def _long(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def _parse(text: str) -> date:
    return datetime.strptime(text.strip(), "%d %B %Y").date()


class EditionRegistry:
    def __init__(self, editions: list[Edition]):
        self.editions = sorted(editions)
        self._validate()

    def _validate(self) -> None:
        """Contiguous and non-overlapping: a date maps to at most one edition."""
        for earlier, later in zip(self.editions, self.editions[1:], strict=False):
            if later.effective_from != earlier.effective_to + timedelta(days=1):
                raise ValueError(f"gap or overlap between {earlier.doc_id} and {later.doc_id}")
        if [e.status for e in self.editions].count(Status.CURRENT) != 1:
            raise ValueError("exactly one edition must be CURRENT")

    def resolve_by_date(self, day: date) -> Edition:
        matches = [e for e in self.editions if e.covers(day)]
        if len(matches) != 1:
            raise NoEditionInForce(f"no held edition was in force on {day.isoformat()}")
        return matches[0]

    def resolve_by_year(self, year: int) -> list[Edition]:
        return [e for e in self.editions if e.edition_year == year]

    def resolve_version(self, year: int, version: str) -> Edition | None:
        return next(
            (e for e in self.resolve_by_year(year) if e.version == version),
            None,
        )

    def by_doc_id(self, doc_id: str) -> Edition | None:
        return next((e for e in self.editions if e.doc_id == doc_id), None)

    def superseding(self, doc_id: str) -> Edition | None:
        """The held edition that says it supersedes doc_id (2022 supersedes the 2021 edition)."""
        return next((e for e in self.editions if e.supersedes == doc_id), None)

    def current(self) -> Edition:
        return next(e for e in self.editions if e.status == Status.CURRENT)

    @property
    def held_range(self) -> str:
        return (
            f"{_long(self.editions[0].effective_from)} to {_long(self.editions[-1].effective_to)}"
        )


def is_ambiguous(editions: list[Edition]) -> bool:
    """The conservative pre-retrieval flag: more than one edition in scope for one question.

    Whether they actually disagree on the fact asked about can only be known after retrieval
    (police notification is 24 hours in both 2023 editions). Generation in `ask` mode says so
    when they agree; Lesson 09's graph re-checks after retrieval.
    """
    return len(editions) > 1


def load_registry(path: Path = EDITIONS_CSV) -> EditionRegistry:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return EditionRegistry(
        [
            Edition(
                effective_from=_parse(r["effective_from"]),
                effective_to=_parse(r["effective_to"]),
                doc_id=r["doc_id"],
                edition_year=int(r["edition_year"]),
                version=r["version"],
                status=Status(r["status"]),
                supersedes=r["supersedes"] or None,
            )
            for r in rows
        ]
    )


@lru_cache(maxsize=1)
def registry() -> EditionRegistry:
    return load_registry()
