# DavidsTown HomeShield — RAG evaluation bank (25 questions)

Ground truth derived from the five HomeShield policy wording PDFs (`data/policy_documents/`) and cross-checked against `data/fact_matrix/editions_fact_matrix.csv` and `fact_lookup_long.csv`. Every answer is traceable to a named document and section. Used for scoring only, never for answering.

Files: `dti_rag_qa_bank.jsonl` (one record per question, canonical; `evaluation/qa_bank.py` reads it) and `dti_rag_qa_bank.csv` (same content flattened, list fields joined with `; `).

## Schema

| Field | Meaning |
|---|---|
| `id` | Stable identifier, `DTI-001` to `DTI-025` |
| `category` | Failure mode being probed (see below) |
| `difficulty` | easy / medium / hard |
| `question` | The query as a user would phrase it |
| `answer` | Reference answer, including reasoning where the answer is edition-dependent |
| `gold_doc_ids` | Document(s) that must appear in the retrieved set |
| `gold_sections` | Section numbers that carry the answer, for chunk-level scoring |
| `fact_keys` | Column names in the CSVs, so answers can be re-derived programmatically |
| `must_include` | Substrings a correct generation should contain |
| `must_not_include` | Distractor values that indicate the wrong edition was used |
| `ambiguous` | True where the correct behaviour is to ask back or return multiple values |
| `answerable` | False where the correct behaviour is abstention |
| `query_date` | Loss date implied by the question, ISO format, for metadata-filter experiments |
| `expected_behaviour` | What a good system does, and the characteristic failure |
| `tests` | One-line statement of what the item measures |

## Category spread

temporal_disambiguation 4 · single_fact_lookup 3 · clause_existence 3 · multi_hop_numeric 3 · version_ambiguity 2 · freshness_default 2 · cross_section 2 · paraphrase_robustness 2 · cross_edition_comparison 2 · abstention_out_of_corpus 1 · abstention_out_of_scope 1

Difficulty: 3 easy, 12 medium, 10 hard.

## Suggested scoring

Score retrieval and generation separately, otherwise a correct answer from the wrong chunk looks like a pass.

1. **Retrieval** — recall@k against `gold_doc_ids`, plus a stricter section-level hit against `gold_sections`. For items with a `query_date`, run twice: with and without a metadata pre-filter (`effective_from <= query_date <= effective_to`). The gap between the two is the single most informative number this bank produces.
2. **Generation** — `must_include` as a cheap regex gate, `must_not_include` as a contamination check, then an LLM judge against `answer` for the reasoning-heavy items (DTI-014, 015, 017, 018, 022).
3. **Behavioural** — the two `ambiguous` items (DTI-008, 009) fail if a single value is returned, even the right one. The two `answerable: false` items (DTI-024, 025) fail on any confident figure.

## Deliberate traps

- **DTI-014** — the fact matrix records a home emergency limit of £1,000 against 2022 and 2023 even though Section 8 is Reserved in those editions. Tests whether structured metadata is allowed to override the source wording.
- **DTI-022** — the 2025 change summary is incomplete; four real changes are absent from it. Tests whether the system diffs the wording or trusts a summary chunk.
- **DTI-013** — Section 3.6 is the claims-process clause in 2022 and the escape of fuel clause from 2023, so the section number itself is a decoy.
- **DTI-024** — the out-of-corpus 2021 reference appears verbatim in the 2022 control page and will retrieve strongly.
