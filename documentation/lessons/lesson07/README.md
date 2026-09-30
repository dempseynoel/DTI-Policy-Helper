# Lesson 07 — The query-understanding layer: dates, freshness, ambiguity, abstention

**Objective:** decide *which editions are in scope and what mode to answer in* before retrieving, with the decision made in deterministic, testable code.

**Deliverables:**

- `src/dti_rag/query/editions.py`: the edition registry; `resolve_by_date` and friends
- `src/dti_rag/query/extract.py`: LLM extraction of facts (never decisions)
- `src/dti_rag/query/router.py`: `route(question) → Route(mode, editions, reason, notes)`
- `tests/unit/test_editions.py`, `tests/unit/test_router.py` (offline) and `tests/integration/test_router_llm.py` (live)

---

## Why routing is the highest-leverage layer

Lesson 06 gave you a retriever that returns exactly the right chunks, **if** you hand it the right filter. Hand it the wrong one and it returns perfectly retrieved, perfectly ranked, **wrong-edition** results, confidently and without error. Everything downstream then works correctly on the wrong premise.

> **Filters only help if you set them correctly.** The router is where correctness is decided; everything after it is execution.

The router's second job is what separates this from a demo: **deciding whether to answer at all.** Some questions need a question back; some need a refusal. Making that a first-class decision, rather than hoping the generator hedges, is what makes it safe for a claims handler.

---

## Three modes

| Mode | When | Response |
|---|---|---|
| `answer` | The editions in scope are determined | A cited answer from those editions (one pass per edition, Lesson 08) |
| `ask` | A bare year with two editions (2023) | Each edition's value with its dates, then a request for the loss date |
| `abstain` | Out of corpus, out of scope, or no edition in force | Why, plus the nearest relevant clause |

Explicit modes make behaviour measurable (Lesson 10): `ambiguous` items must `ask`, `answerable: false` items must `abstain`, and answerable items must *not* abstain.

---

## The split: the LLM extracts, code decides

```
    LLM (fuzzy, unbounded input)              deterministic code (exact, tested)
    ───────────────────────────               ──────────────────────────────────
    "flooded on 15 March 2024"   ──►  loss_date="2024-03-15"  ──►  registry.resolve_by_date
    "the second 2023 edition"    ──►  {year: 2023, version: "1.1"}        │
    "DTI-HOME-PW-2021-v1.0"      ──►  referenced_doc_ids                  ▼
    "does it cover my car?"      ──►  scope="other_insurance"      decide() ──► Route
```

**LLM structured output handles extraction** (`extract.py`). Natural language is unbounded; you can't regex every phrasing of a date.

**Pure code handles resolution** (`editions.py`, `router.decide()`). Which edition governs a date has exactly one right answer, must be identical every time, and must be testable offline. Ask a model "which edition covers 15 March 2024?" and it's usually right, and occasionally, untestably, wrong.

> **Use the LLM to turn language into structure. Use code to turn structure into decisions.** The moment a decision has exactly one defensible answer, it belongs in code.

### The extraction schema (`extract.py`)

| Field | Meaning |
|---|---|
| `loss_date` | ISO date of loss or discovery. **Not** a duration ("running for 18 days", DTI-017) or an interval ("80 hours apart", DTI-015) |
| `named_editions` | `[{year, version}]`: "the 2024 edition" → `{2024, null}`; "the second 2023 edition" → `{2023, "1.1"}` |
| `referenced_doc_ids` | Document references quoted in the question |
| `question_type` | `lookup`, `existence_or_history` ("is X excluded?", "has X ever changed?") or `comparison` ("what changed between…") |
| `scope` | `home_policy`, `other_insurance` or `unrelated` |

Design notes:

- **Every field may be empty, and empty is the safe default.** A spurious extraction (a filter matching nothing, a false abstention) costs more than a missed one, which falls through to the freshness default.
- **Never ask the model for the filter, the edition, or "is this ambiguous?".** Ask for facts; derive decisions in code.
- **Strict structured outputs** (`chat.completions.parse` with a Pydantic model). No field has a default value, because strict mode requires every field; `Extraction.empty()` is the explicit fallback.
- The question is wrapped in `<question>` tags and declared to be data. That's the first of the injection defences (Lesson 11).

### The edition registry (`editions.py`)

Pure functions over the **edition columns** of the fact matrix (doc_id, year, version, status, dates). Those columns are verified against every PDF's control page by a Lesson 03 test. The fact columns, where the DTI-014 trap lives, are never read.

- `resolve_by_date(d)` → exactly one edition, or `NoEditionInForce`
- `resolve_by_year(y)` → a list (2023 returns two); `resolve_version(y, v)`
- `by_doc_id`, `superseding` (2022 supersedes the 2021 edition), `current()`
- On load, it **validates** that ranges are contiguous and non-overlapping, and that exactly one edition is CURRENT. The property the whole design rests on is checked, not assumed.

---

## `decide()`: the edition-selection policy, executed

In order (`router.py`):

1. **Out of scope** (`scope != home_policy`) → `abstain`, with the current edition in scope so generation can cite the nearest clause (DTI-025 wants 6.5 cited).
2. **A document named but not held** → `abstain`, with the edition that supersedes it in scope (DTI-024 → 2022's control page). **A set-membership check, no LLM judgement**: the scariest failure in the corpus is caught deterministically. `route()` also regex-scans the question for document references, so this doesn't depend on the model noticing them. A named *year* that isn't held (2021) → `abstain` too.
3. **A loss date** → the edition in force → `answer`. The reason says why: *"The loss date (15 March 2024) falls within 2024 edition v1.0, in force 1 January 2024 to 31 December 2024."* **A date outside every edition** (e.g. 2026: the current edition expired on 31 December
   2025) → `abstain`, not a silent fallback to "current".
4. **Named editions** → those editions. A bare year with two editions → `ask`, with both ranges in the reason (DTI-008, DTI-009). Several named editions (DTI-015's 2024 and 2025; DTI-017's "second 2023" and 2024) → `answer`, one pass per edition.
5. **`existence_or_history` or `comparison`, with nothing named** → every held edition (DTI-012, 013, 014, 023).
6. **Nothing temporal** → the current edition, `answer`, **plus a note for generation**: "state that earlier editions may differ". The caveat is part of the correct answer (DTI-010's `expected_behaviour` says so).

`Route.filters()` returns **one `doc_id` filter per edition**. The router resolves the date in code and hands `retrieve()` an exact edition, so retrieval for different editions never mixes. The date-range filter from Lesson 06 remains in the integration tests as a cross-check that the index and the registry agree.

### The subtlety: two editions in scope isn't always ambiguous

For DTI-006 (burglary discovered 3 May 2023), the date resolves to exactly one edition, so it's not ambiguous even though 2023 has two. And where both editions are in scope, if they *agree* (police notification is 24 hours in both 2023 editions), there's nothing to ask.

So ambiguity is properly: **several editions in scope AND they disagree on the fact asked about.** Disagreement can only be known after retrieval, so the router raises a conservative `ask`, and Lesson 09 adds the post-retrieval check that downgrades it when the editions word the clause identically. `is_ambiguous()` is the pre-retrieval half.

**Don't over-abstain.** Lesson 10 scores both directions: a router that abstains whenever it's unsure passes DTI-024/025 and fails half the bank. `test_a_plain_lookup_does_not_over_abstain` exists for a reason.

---

## Run it

```bash
documentation/lessons/apply_lesson.sh 07
make test                           # decide() and the registry, offline: 25 new tests
make test-integration ENV=dev       # the LLM half against your `chat` deployment
```

---

## Environments

`query/` never reads `APP_ENV`. If you catch yourself wanting it there, something that should be data has become behaviour.

What *does* vary is the model behind extraction. **Structured-output behaviour is a property of the model version**: a new version can extract "3 May 2023" differently, or start filling a field it used to leave empty. So **a model upgrade is a router change**: it goes dev → test → prod behind the eval gate, like code. The integration tests run in test against the version prod uses.

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `src/dti_rag/query/__init__.py` | new | The package |
| `src/dti_rag/query/editions.py` | new | The registry; date/year/version resolution; validated on load |
| `src/dti_rag/query/extract.py` | new | Versioned extraction prompt; strict structured output |
| `src/dti_rag/query/router.py` | new | `Mode`, `Route`, `decide()` (pure), `route()` |
| `tests/unit/test_editions.py` | new | Both 2023 boundary days; out-of-range dates; gaps rejected |
| `tests/unit/test_router.py` | new | decide() for DTI-004, 006, 008, 010, 012, 015, 017, 024, 025, a 2026 date, bad dates |
| `tests/integration/test_router_llm.py` | new | The real model: dates, durations, modes |

## Project structure at the end of this lesson

```text
DTI-Policy-Helper/
├── artifacts/
│   ├── chunks.jsonl  ◇ generated
│   └── chunks.sha256  ◇ generated
├── data/
│   ├── fact_matrix/  (editions_fact_matrix.csv, fact_lookup_long.csv: convenience data)
│   ├── policy_documents/  (the 5 policy wording PDFs: authoritative)
│   └── question_answers/  (dti_rag_qa_bank.jsonl and .csv, README.md: ground truth for scoring)
├── deploy/
│   ├── dev.env  ◇ generated
│   └── environments.yaml
├── documentation/
│   ├── design/
│   │   ├── baseline_failures.md
│   │   ├── corpus_map.md
│   │   └── SCHEMA.md
│   └── lessons/  (this course)
├── evaluation/
│   ├── baselines/
│   │   └── naive-baseline-dev.json  ◇ generated
│   ├── __init__.py
│   ├── checks.py
│   ├── qa_bank.py
│   ├── rows.py
│   ├── run_baseline.py
│   └── runmeta.py
├── infra/  (Terraform: modules/environment, shared, dev, test, prod)
├── scripts/
│   ├── experiments/
│   │   └── integrated_vectorization.py
│   ├── build_corpus_map.py
│   ├── compare_filters.py
│   ├── measure_retrieval.py
│   └── smoke_test.py
├── src/
│   └── dti_rag/
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── __main__.py
│       │   ├── chunk.py
│       │   └── parse.py
│       ├── query/
│       │   ├── __init__.py  ★ new
│       │   ├── editions.py  ★ new
│       │   ├── extract.py  ★ new
│       │   └── router.py  ★ new
│       ├── retrieval/
│       │   ├── __init__.py
│       │   ├── baseline.py
│       │   ├── filters.py
│       │   ├── results.py
│       │   └── retrieve.py
│       ├── search/
│       │   ├── __init__.py
│       │   ├── documents.py
│       │   ├── loader.py
│       │   ├── manifest.py
│       │   └── schema.py
│       ├── __init__.py
│       ├── clients.py
│       ├── config.py
│       ├── constants.py
│       ├── models.py
│       └── runinfo.py
├── tests/
│   ├── integration/
│   │   ├── conftest.py
│   │   ├── test_retrieve.py
│   │   └── test_router_llm.py  ★ new
│   └── unit/
│       ├── test_checks.py
│       ├── test_chunking.py
│       ├── test_config.py
│       ├── test_editions.py  ★ new
│       ├── test_filters.py
│       ├── test_router.py  ★ new
│       └── test_search_schema.py
├── .gitignore
├── Makefile
├── .pre-commit-config.yaml
├── pyproject.toml
├── .python-version
├── README.md
└── uv.lock  ◇ generated
```

`★ new` in this lesson · `✎ changed` in this lesson · `◇ generated` by running the code (git-ignored or produced by you) · unmarked: unchanged from earlier lessons

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Asking the LLM which edition governs | Non-deterministic, untestable, occasionally wrong |
| Extracting durations as dates | A filter that matches nothing |
| "Two editions in scope" treated as ambiguous | DTI-006 asks instead of answering |
| Losing the freshness caveat before generation | DTI-010 partial failure |
| Treating "current" as "in force on any date" | A 2026 loss answered from the 2025 edition |
| Over-abstaining when unsure | Passes 2 questions, fails many |
| A flat refusal without the nearest clause | DTI-025 wants 6.5 cited |
| Unvalidated extraction reaching a filter | OData injection |
| The router querying the index | Untestable, and Lesson 09's graph has no clean node |
| Upgrading `chat` in one environment "just to try it" | Extraction differs between test and prod; the gate proves nothing |

## Done when

- DTI-008 routes to `ask` with both 2023 ranges in the reason
- DTI-010 routes to the current edition **with** the freshness note
- DTI-024 and DTI-025 route to `abstain`; a 2026 loss date routes to `abstain`
- DTI-006 routes to `answer` (v1.0) despite 2023 having two editions
- `tests/unit/test_editions.py` covers 30 June and 1 July 2023 explicitly

## Check yourself

1. Why does date → edition resolution belong in code rather than the LLM?
2. Two editions are in scope. Is that ambiguous? What else do you need to know?
3. How does the router catch DTI-024 without LLM judgement?
4. Why is a flat refusal the wrong answer to DTI-025?
5. What's the cost asymmetry between a spurious extraction and a missed one, and how does it shape the schema?
6. Where does untrusted text become typed values, and why does that location matter?

---

**Next:** [Lesson 08 — Grounded generation](../lesson08/README.md)
