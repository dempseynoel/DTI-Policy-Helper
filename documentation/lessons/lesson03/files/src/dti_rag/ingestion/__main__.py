"""Build artifacts/chunks.jsonl from the policy PDFs.

    python -m dti_rag.ingestion            (or: make chunks)

Deterministic by construction: files in sorted order, keys sorted, no timestamps. Running it
twice produces a byte-identical file, and the SHA-256 printed at the end identifies the
corpus in every index manifest (Lesson 04) and scorecard (Lesson 10).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from dti_rag.ingestion.chunk import chunk_document
from dti_rag.ingestion.parse import ParsedDocument, parse_pdf
from dti_rag.models import Chunk

ROOT = Path(__file__).resolve().parents[3]
PDF_DIR = ROOT / "data" / "policy_documents"
OUT = ROOT / "artifacts" / "chunks.jsonl"


def validate(doc: ParsedDocument) -> None:
    """Parsed metadata must agree with itself before anything is written."""
    if doc.footer_status != doc.status.value:
        raise ValueError(
            f"{doc.doc_id}: control page says {doc.status}, footer says {doc.footer_status}"
        )
    if doc.effective_from > doc.effective_to:
        raise ValueError(f"{doc.doc_id}: effective_from is after effective_to")


def build_chunks(pdf_dir: Path = PDF_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(pdf_dir.glob("*.pdf")):
        doc = parse_pdf(path)
        validate(doc)
        chunks.extend(chunk_document(doc))
    ids = [c.id for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate chunk ids")
    return chunks


def serialise(chunks: list[Chunk]) -> bytes:
    lines = [
        json.dumps(c.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) for c in chunks
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    data = serialise(build_chunks())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    args.out.with_suffix(".sha256").write_text(sha + "\n")
    count = data.count(b"\n")
    print(f"wrote {args.out} ({count} chunks) sha256={sha}")


if __name__ == "__main__":
    main()
