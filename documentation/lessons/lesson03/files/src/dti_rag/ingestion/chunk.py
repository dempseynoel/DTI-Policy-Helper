"""Section-aware chunking: one chunk per clause, never a fixed token count.

A clause (all of 3.4, "Excess") is the unit because section IDs must stay meaningful for
citations and cross-references, and because near-identical clauses across editions can only
be told apart by their metadata. No overlap between sections: it would copy 3.4's text into
the 3.5 chunk and make citations ambiguous.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from dti_rag.ingestion.parse import BULLET, Line, ParsedDocument
from dti_rag.models import Chunk, ChunkKind, ChunkMetadata

_SECTION = re.compile(r"^Section (\d+) — (.+)$")
_CLAUSE = re.compile(r"^(\d+)\.(\d+) ([A-Z].*)$")
_DEFINITION = re.compile(r"^([A-Z][A-Za-z ]{1,30})\. (.+)$")
_MONEY = re.compile(r"^£[\d,]+$")
_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_\-=]")

DOCUMENT_CONTROL = "Document control"
SUMMARY_HEADING = "Summary of changes in this version"
EXCESS_SECTION = "10"
DEFINITIONS_SECTION = "1"


@dataclass
class _Block:
    section_id: str
    section_group: str
    title: str
    kind: ChunkKind
    lines: list[Line]
    part: str | None = None


def chunk_key(doc_id: str, section_id: str, part: str | None = None) -> str:
    """Search document keys allow only letters, digits, '_', '-' and '='.

    Both the section number ('3.4') and the doc_id ('...-v1.0') contain dots, so the whole key
    is encoded. The readable values stay in their own fields.
    """
    raw = f"{doc_id}__{section_id}" + (f"__{part}" if part else "")
    return _KEY_UNSAFE.sub("_", raw)


def reflow(lines: list[str]) -> str:
    """Join PDF-wrapped lines into prose, keeping each bullet on its own line.

    A new line starts at a bullet, after an explicit break (""), or when prose resumes after
    a bullet that has ended (it closed with '.', ';' or ':' and the next line is capitalised).
    """
    out: list[str] = []
    new_line = True
    for line in lines:
        if not line:
            new_line = True
            continue
        previous = out[-1] if out else ""
        bullet_ended = previous.startswith(BULLET) and previous[-1:] in ".;:" and line[:1].isupper()
        # A one-word line on its own ("Fraud") is a subheading, not wrapped prose.
        subheading = len(previous.split()) == 1 and previous.isalpha()
        if subheading and not new_line:
            out[-1] = f"{previous}:"
        if new_line or line.startswith(BULLET) or bullet_ended or subheading:
            out.append(line)
        else:
            out[-1] = f"{previous} {line}"
        new_line = False
    return "\n".join(out)


def _split_sections(body: list[Line]) -> Iterator[_Block]:
    section_id: str | None = None
    section_title = ""
    current: _Block | None = None

    for line in body:
        section = _SECTION.match(line.text)
        clause = _CLAUSE.match(line.text)
        if section:
            if current:
                yield current
            section_id, section_title = section.group(1), section.group(2)
            kind = ChunkKind.SECTION_INTRO
            if section_id == EXCESS_SECTION:
                kind = ChunkKind.EXCESS_SUMMARY
            current = _Block(section_id, section_id, section_title, kind, [])
        elif clause and clause.group(1) == section_id:
            if current:
                yield current
            clause_id = f"{clause.group(1)}.{clause.group(2)}"
            title = f"{section_title} › {clause.group(3)}"
            current = _Block(clause_id, section_id, title, ChunkKind.CLAUSE, [line])
        elif current:
            current.lines.append(line)
    if current:
        yield current


def _split_definitions(block: _Block) -> Iterator[_Block]:
    """Section 1: the intro prose, then one chunk per defined term."""
    intro: list[Line] = []
    definitions: list[_Block] = []
    in_definitions = False
    for line in block.lines:
        if line.text == "Definitions":
            in_definitions = True
            continue
        match = _DEFINITION.match(line.text) if in_definitions else None
        if match:
            term = match.group(1)
            definitions.append(
                _Block(
                    DEFINITIONS_SECTION,
                    DEFINITIONS_SECTION,
                    f"{block.title} › Definitions › {term}",
                    ChunkKind.DEFINITION,
                    [line],
                    part=term.lower().replace(" ", "-"),
                )
            )
        elif definitions:
            definitions[-1].lines.append(line)
        else:
            intro.append(line)
    if intro:
        yield _Block(block.section_id, block.section_group, block.title, block.kind, intro)
    yield from definitions


def _pair_excess_table(lines: list[str]) -> list[str]:
    """Section 10's table extracts as alternating label / value lines. Pair them up."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line in ("Type of claim", "Excess"):
            i += 1
            continue
        if i + 1 < len(lines) and _MONEY.match(lines[i + 1]) and not _MONEY.match(line):
            out.append(f"{BULLET} {line}: {lines[i + 1]}")
            i += 2
            if i < len(lines) and not (i + 1 < len(lines) and _MONEY.match(lines[i + 1])):
                out.append("")  # the table has ended; what follows is prose
            continue
        out.append(line)
        i += 1
    return out


def _header(doc: ParsedDocument, section_id: str, title: str) -> str:
    where = "Document control" if section_id == DOCUMENT_CONTROL else f"Section {section_id}"
    return (
        f"HomeShield policy wording {doc.doc_id} ({doc.edition_year} edition, "
        f"version {doc.version}). {where}: {title}."
    )


def _metadata(doc: ParsedDocument, block: _Block) -> ChunkMetadata:
    return ChunkMetadata(
        doc_id=doc.doc_id,
        edition_year=doc.edition_year,
        version=doc.version,
        status=doc.status,
        effective_from=doc.effective_from,
        effective_to=doc.effective_to,
        supersedes=doc.supersedes,
        superseded_by=doc.superseded_by,
        section_id=block.section_id,
        section_group=block.section_group,
        section_title=block.title,
        chunk_kind=block.kind,
        page=block.lines[0].page,
    )


def _control_chunk(doc: ParsedDocument) -> Chunk:
    title = "Document control and summary of changes"
    fields = "\n".join(f"{k}: {v}" for k, v in doc.control_fields.items())
    # Every edition's control page has the same shape: applicability prose, then the change
    # summary. The summary is evidence, not authority: 2025's omits four real changes.
    index = doc.control_notes.index(SUMMARY_HEADING)
    prose = reflow(doc.control_notes[:index])
    summary = f"{SUMMARY_HEADING}:\n" + reflow(doc.control_notes[index + 1 :])
    content = "\n".join([_header(doc, DOCUMENT_CONTROL, title), fields, prose, summary])
    block = _Block(
        DOCUMENT_CONTROL, DOCUMENT_CONTROL, title, ChunkKind.DOCUMENT_CONTROL, [Line("", 2)]
    )
    return Chunk(
        id=chunk_key(doc.doc_id, DOCUMENT_CONTROL), content=content, metadata=_metadata(doc, block)
    )


def chunk_document(doc: ParsedDocument) -> list[Chunk]:
    chunks = [_control_chunk(doc)]
    for block in _split_sections(doc.body):
        blocks = _split_definitions(block) if block.section_id == DEFINITIONS_SECTION else [block]
        for b in blocks:
            texts = [ln.text for ln in b.lines]
            if b.kind == ChunkKind.CLAUSE:
                texts = texts[1:]  # the "3.4 Excess" heading is already in the header
            if b.kind == ChunkKind.EXCESS_SUMMARY:
                texts = _pair_excess_table(texts)
            body = reflow(texts)
            if not body:
                continue  # a heading with no text of its own, e.g. Section 3 before 3.1
            content = f"{_header(doc, b.section_id, b.title)}\n{body}"
            chunks.append(
                Chunk(
                    id=chunk_key(doc.doc_id, b.section_id, b.part),
                    content=content,
                    metadata=_metadata(doc, b),
                )
            )
    return chunks
