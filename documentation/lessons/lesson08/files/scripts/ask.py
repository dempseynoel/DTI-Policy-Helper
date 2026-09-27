"""Ask the pipeline one question and see everything it decided.

make ask ENV=dev Q="A kitchen flooded on 15 March 2024. What excess applies?"
"""

from __future__ import annotations

import sys

from dti_rag.pipeline import answer


def main() -> None:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        sys.exit('usage: python scripts/ask.py "your question"')
    result = answer(question)
    a = result.answer
    print(f"mode:     {a.mode}")
    print(f"editions: {', '.join(a.governing_editions) or '—'}")
    print(f"why:      {a.edition_reason}")
    for r in result.retrievals:
        print(f"searched: {r.filter}  ->  {[c.section_id for c in r.chunks]}")
    print(f"\n{a.text}\n")
    for c in a.citations:
        print(f'  [{c.doc_id} §{c.section_id} p.{c.page}] "{c.quoted_text}"')
    for calc in a.calculations:
        print(f"  calc: {calc.expression} = {calc.result} ({'ok' if calc.verified else 'WRONG'})")
    for w in a.warnings:
        print(f"  warning: {w}")


if __name__ == "__main__":
    main()
