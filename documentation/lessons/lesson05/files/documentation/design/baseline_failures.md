# Baseline failures

The naive pipeline (`src/dti_rag/retrieval/baseline.py`): embed → vector top-5, no filters →
stuff → generate at temperature 0. The control group for every later comparison.

**Run:** `make baseline ENV=dev` · raw output: `evaluation/baselines/naive-baseline-dev.json`

| | |
|---|---|
| Date | ____ |
| app_env | dev |
| `chat` model / version (read at run time) | ____ |
| `embed` model / version | ____ |
| Index manifest sha256 | ____ |
| Throttled responses | ____ |

## The five mechanisms

Fill the "Baseline gave" and "Gold retrieved?" columns from your run. The expected failures
are what this corpus is built to produce; if yours differ, say why.

| QA ID | Category | Expected | Baseline gave | Gold retrieved? | Mechanism |
|---|---|---|---|---|---|
| DTI-004 | temporal_disambiguation | £300 | ____ | ____ | Recency bias across five near-identical 3.4 clauses; the loss date isn't in any chunk |
| DTI-003 | single_fact_lookup | 48 knots | ____ | ____ | Minority value outvoted: four editions say 47 |
| DTI-008 | version_ambiguity | both £500 (v1.0) and £600 (v1.1) | ____ | ____ | Genuine ambiguity collapsed into one confident figure |
| DTI-014 | clause_existence | Reserved / not offered before 2024 | ____ | ____ | Cover described without edition scope |
| DTI-024 | abstention_out_of_corpus | a refusal | ____ | ____ | Retrieval confidence became answer confidence |

## Every question

Paste the table `run_baseline.py` printed.

## Summary

- Pass rate by category: ____
- Retrieval failures (gold doc never arrived): ____ of ____ failures → fixed in Lessons 06–07
- Generation failures (gold doc arrived, answer still wrong): ____ of ____ → Lesson 08
- A pass to be suspicious of: ____ (for example DTI-010: right figure, no "earlier editions
  differ" caveat)
