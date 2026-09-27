"""Typed search filters, rendered to OData. Pure, and the OData-injection boundary.

Filters are built from typed values only: dates are `date` objects, years are ints, status
is an enum, doc_ids and versions must match their formats. A raw string from a user can
never reach a filter clause. Anything that doesn't validate raises before a request is sent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from dti_rag.models import Status
from dti_rag.search.documents import to_offset

DOC_ID = re.compile(r"^DTI-HOME-PW-\d{4}-v\d+\.\d+$")
VERSION = re.compile(r"^\d+\.\d+$")
SECTION_GROUP = re.compile(r"^(\d{1,2}|Document control)$")


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True)
class SearchFilter:
    doc_ids: tuple[str, ...] = field(default_factory=tuple)
    loss_date: date | None = None
    status: Status | None = None
    edition_year: int | None = None
    version: str | None = None
    section_group: str | None = None

    def __post_init__(self) -> None:
        for doc_id in self.doc_ids:
            if not DOC_ID.match(doc_id):
                raise ValueError(f"not a doc_id: {doc_id!r}")
        if self.loss_date is not None and not isinstance(self.loss_date, date):
            raise ValueError("loss_date must be a date")
        if self.status is not None and not isinstance(self.status, Status):
            raise ValueError("status must be a Status")
        if self.edition_year is not None and (
            not isinstance(self.edition_year, int) or not 1900 < self.edition_year < 2200
        ):
            raise ValueError(f"not a year: {self.edition_year!r}")
        if self.version is not None and not VERSION.match(self.version):
            raise ValueError(f"not a version: {self.version!r}")
        if self.section_group is not None and not SECTION_GROUP.match(self.section_group):
            raise ValueError(f"not a section: {self.section_group!r}")

    def to_odata(self) -> str | None:
        clauses: list[str] = []
        if len(self.doc_ids) == 1:
            clauses.append(f"doc_id eq {_quote(self.doc_ids[0])}")
        elif self.doc_ids:
            clauses.append(f"search.in(doc_id, {_quote(','.join(self.doc_ids))}, ',')")
        if self.loss_date is not None:
            # Dates are stored at midnight UTC and queries are normalised to midnight, so
            # both boundary days are inclusive (SCHEMA.md).
            when = to_offset(self.loss_date)
            clauses.append(f"effective_from le {when} and effective_to ge {when}")
        if self.status is not None:
            clauses.append(f"status eq {_quote(self.status.value)}")
        if self.edition_year is not None:
            clauses.append(f"edition_year eq {self.edition_year}")
        if self.version is not None:
            clauses.append(f"version eq {_quote(self.version)}")
        if self.section_group is not None:
            clauses.append(f"section_group eq {_quote(self.section_group)}")
        return " and ".join(clauses) or None


def by_date(loss_date: date) -> SearchFilter:
    return SearchFilter(loss_date=loss_date)


def by_doc(doc_id: str) -> SearchFilter:
    return SearchFilter(doc_ids=(doc_id,))


def current() -> SearchFilter:
    return SearchFilter(status=Status.CURRENT)


def by_year(year: int) -> SearchFilter:
    return SearchFilter(edition_year=year)
