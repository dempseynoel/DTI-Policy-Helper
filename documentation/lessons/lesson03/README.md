# Lesson 03 — Parse and chunk the PDFs, section-aware and deterministic

**Objective:** turn five PDFs into clean, clause-level chunks that each carry the full Lesson 02 metadata, byte-identically on every run.

**Deliverables:**

- `src/dti_rag/ingestion/` (`parse.py`, `chunk.py`, `__main__.py`) and `models.py`
- `artifacts/chunks.jsonl` + `artifacts/chunks.sha256`: `make chunks`
- `tests/unit/test_chunking.py`: the sanity checks, as tests (24 more tests; 35 in total)

---

## Why chunking decides your ceiling

Every later lesson works on what comes out of this one. If the storm definition and the excess clause share a chunk, no reranker separates them. If "Section 8 — Reserved" is dropped as boilerplate, DTI-014 is permanently unanswerable. If section IDs are wrong, Lesson 08's cross-references have nothing to follow.

**Chunking bugs present as retrieval bugs.** Teams spend a week tuning retrieval when the fix was in the parser. Check this lesson's output harder than feels necessary.

---

## Parse: start simple

The PDFs are born-digital and clean, so **PyMuPDF** handles them in a few lines.

Separately, run **one** PDF through **Azure Document Intelligence (Layout)** in a notebook against your dev Foundry resource, and compare the effort, output structure and cost. Real claims documents *are* scanned (a loss adjuster's report, a photographed schedule), and you want to have felt the difference before you have to choose under pressure. It's a dev-only experiment: keep it out of `ingestion/`.

### What the real files contain

| Pages | 2022, 2023 v1.0 | 2023 v1.1, 2024, 2025 |
|---|---|---|
| 1 | Cover (no footer) | Cover (no footer) |
| 2 | Document control + "Summary of changes" | same |
| 3 | Contents | same |
| 4–end | Sections 1–10 (9 pages in total) | Sections 1–10 (10 pages in total) |

| § | Title | Clauses |
|---|---|---|
| 1 | About your policy and definitions | Intro + definitions (Home, Buildings, …, Storm, Flood, Unoccupied; Flood Re from 2025) |
| 2 | Making a claim | Prose + "Fraud" |
| 3 | Escape of water *(and escape of fuel, 2023+)* | 3.1–3.6 (2022); 3.1–3.7 (2023+) |
| 4 | Storm, flood and weather | 4.1–4.6 |
| 5 | Fire, lightning and explosion | 5.1–5.6 |
| 6 | Theft and malicious damage | 6.1–6.7 |
| 7 | Accidental damage (optional) | 7.1–7.5; 7.1–7.6 in 2025 (EV charging points at 7.4) |
| 8 | **Reserved** (2022, 2023) / Home emergency (2024+) | none / 8.1–8.3 |
| 9 | General exclusions | 9.1–9.7 (2022); 9.1–9.8 (2023+, renumbered) |
| 10 | Excess summary | Table + trailing prose |

### Five extraction artefacts you'll actually hit (all handled in `parse.py`)

1. **A running footer on every page after the cover.** `DAVIDSTOWN INSURANCE / HomeShield Home Insurance — 2025 Edition / DTI-HOME-PW-2025-v1.0 | Version 1.0 | Status: CURRENT / Effective … / Page 4 of 10`. Left in, it pollutes every chunk and BM25. But it contains the status, so **harvest it as a cross-check, then strip it.**
2. **Bullets extract as a lone `–` line**, divorced from their text. Rejoined, including when the glyph ends one page and the text starts the next.
3. **The contents page repeats every section heading.** A naive `^Section \d+` split finds each heading twice. Pages 1–3 are never searched for section starts.
4. **Sections span page breaks.** The body is one list of lines, each tagged with its page, so chunking works on the concatenated document and still knows each chunk's page.
5. **`Status: SUPERSEDEDEffective 1 July 2023`.** The 2023 v1.1 footer loses a space. A naive regex parses the status as `SUPERSEDEDEFFECTIVE` for exactly one edition. The non-greedy pattern stops at `Effective`, and the parsed status is validated against the control page before anything is written.

---

## Chunk on section boundaries, never token counts

The generic instinct, "1000 tokens, 200 overlap", is wrong here. **A chunk is a clause** (all of 3.4, "Excess"), because:

- `section_id` stays meaningful for citations, cross-references and `gold_sections` scoring;
- near-identical clauses across editions stay distinguishable **by their metadata**;
- the reworded storm clause (2022 vs later) survives paraphrase as one unit;
- "Reserved" Section 8 is captured **as** Reserved.

### The special cases in `chunk.py`

| Case | Handling |
|---|---|
| Section 8 when Reserved | Two lines, no clauses. It is **not** empty: its text is the answer to DTI-014. Kept as `section_id = "8"`. There is no minimum-length filter |
| Section 1 definitions | One chunk per defined term (DTI-003 and DTI-007 need a single definition). All keep `section_id = "1"`; the id gets a suffix (`…__1__storm`) |
| Section 10 table | Extracts as alternating label / value lines. Paired at parse time into `– Escape of water (standard): £350`. It's a `gold_section` for five QA items: don't make the LLM guess the pairing |
| Page 2 | One chunk, `section_id = "Document control"`: the fields, the applicability prose, then the change summary. Evidence, not authority |
| Section intros | Text between a section heading and its first clause (Section 9's "These exclusions apply across every section…") gets its own chunk |
| Wrapped lines | Reflowed into prose; bullets stay on their own lines; prose that resumes after a list starts a new line |

**No overlap between sections.** Overlap would copy 3.4's text into the 3.5 chunk, so the excess figure would match two chunks with different `section_id`s, and citations would become unreliable.

**Each chunk's content starts with an edition header**: `HomeShield policy wording DTI-HOME-PW-2024-v1.0 (2024 edition, version 1.0). Section 3.4: Escape of water and escape of fuel › Excess.` That's the "garnish" from Lesson 02: it helps BM25 and the reranker, and it isn't how editions are selected.

### Chunk IDs

Stable and deterministic, so re-runs update the index rather than duplicate it: `<doc_id>__<section_id>[__<part>]`. **Azure AI Search keys allow only letters, digits, `_`, `-` and `=`**, and both `3.4` *and* the doc_id (`…-v1.0`) contain dots. So **every** illegal character is replaced: `DTI-HOME-PW-2024-v1_0__3_4`. The readable values stay in their own fields.

---

## Determinism is an environment requirement

Chunking knows nothing about environments: no settings, no Azure calls, no `APP_ENV`. PDFs in, `chunks.jsonl` out, identical every run: files in sorted order, JSON keys sorted, no timestamps. `make chunks` prints the SHA-256 and writes it to `artifacts/chunks.sha256`.

Why that matters: in Lesson 13 the pipeline builds `chunks.jsonl` **once per commit** and loads the same file into dev, then test, then prod. Non-deterministic chunking would mean "passed the eval in test" was on a slightly different corpus from prod's, with no way to prove otherwise. The index manifest (Lesson 04) and every scorecard (Lesson 10) record the hash.

---

## Build it

```bash
documentation/lessons/apply_lesson.sh 03
uv sync                      # adds pymupdf (the `ingest` extra)
make chunks                  # wrote artifacts/chunks.jsonl (269 chunks) sha256=…
make test
```

Expect **51 / 53 / 53 / 55 / 57** chunks for 2022 / 2023 v1.0 / 2023 v1.1 / 2024 / 2025. The counts rise as clauses are added (escape of fuel, communicable disease, home emergency, EV charging, Flood Re). A wild outlier means a heading regex failed on one file.

### The sanity checks, as tests (`tests/unit/test_chunking.py`)

1. Every edition is chunked, with comparable counts.
2. `edition_year == 2024 and section_id == "3.4"` is **exactly one** chunk, and it says £300.
3. Section 8 exists in all five editions: "not offered" in three, Home emergency in two.
4. 2022's 3.6 is the claims process; 2023's 3.6 is escape of fuel.
5. 2022's 9.6 is "how exclusions interact"; 2023's 9.6 is communicable disease.
6. No footer text survives; no lone bullets survive; no phantom sections.
7. The excess table is paired; the storm definition is its own chunk.
8. Parsed status matches the footer **and** the fact matrix (catches `SUPERSEDEDEffective`).
9. **The fact matrix's edition-registry columns match every PDF's control page.** This is the one part of the CSV the router trusts (Lesson 07), and it's verified here.
10. Every chunk id is a legal Search key.
11. Two runs produce byte-identical output.

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `src/dti_rag/models.py` | new | `Status`, `ChunkKind`, `ChunkMetadata`, `Chunk` |
| `src/dti_rag/ingestion/__init__.py` | new | The package |
| `src/dti_rag/ingestion/parse.py` | new | PDF → cleaned lines tagged with pages; control-page fields; footer status |
| `src/dti_rag/ingestion/chunk.py` | new | Lines → clause-level chunks with metadata and legal keys |
| `src/dti_rag/ingestion/__main__.py` | new | `python -m dti_rag.ingestion`: validates and writes the artefact and its hash |
| `tests/unit/test_chunking.py` | new | The sanity checks |
| `pyproject.toml` | changed | `ingest` extra (PyMuPDF), included in `dev` |
| `Makefile` | changed | `make chunks` |

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
│   │   ├── corpus_map.md
│   │   └── SCHEMA.md
│   └── lessons/  (this course)
├── infra/  (Terraform: modules/environment, shared, dev, test, prod)
├── scripts/
│   ├── build_corpus_map.py
│   └── smoke_test.py
├── src/
│   └── dti_rag/
│       ├── ingestion/
│       │   ├── __init__.py  ★ new
│       │   ├── __main__.py  ★ new
│       │   ├── chunk.py  ★ new
│       │   └── parse.py  ★ new
│       ├── __init__.py
│       ├── clients.py
│       ├── config.py
│       ├── constants.py
│       └── models.py  ★ new
├── tests/
│   └── unit/
│       ├── test_chunking.py  ★ new
│       └── test_config.py
├── .gitignore
├── Makefile  ✎ changed
├── .pre-commit-config.yaml
├── pyproject.toml  ✎ changed
├── .python-version
├── README.md
└── uv.lock  ◇ generated
```

`★ new` in this lesson · `✎ changed` in this lesson · `◇ generated` by running the code (git-ignored or produced by you) · unmarked: unchanged from earlier lessons

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Heading regex without skipping the contents page | Phantom sections from the table of contents |
| Dropping short sections | Section 8 Reserved disappears; DTI-014 unanswerable |
| Chunking page by page | Sections split at page breaks |
| Footers left in the content | Every chunk carries boilerplate; BM25 degraded |
| Overlap across section boundaries | Ambiguous citations, duplicate hits |
| Status parsed from the footer without validation | `SUPERSEDEDEffective` in 2023 v1.1 |
| Encoding only the section's dot in the key | The doc_id's dot still makes the key illegal |
| Excess table left as alternating lines | The label/figure pairing is lost for five QA items |
| Timestamps or unordered iteration in the output | Can't prove test and prod hold the same corpus |

## Done when

`make chunks` produces 269 chunks with a stable SHA-256, `make test` passes (35 tests), and you can explain each special case in `chunk.py` without reading it.

## Check yourself

1. Why is overlap *between* sections harmful here when it's standard practice elsewhere?
2. What breaks downstream if Section 8 Reserved is dropped?
3. 2022 has 51 chunks and 2025 has 57. Bug or expected? How do you tell?
4. Why keep the Search key separate from `section_id`?
5. Section 1 holds every definition. Argue both sides of splitting it, then commit.
6. The footer contains the status. Why parse it, *and* not trust it?
7. Why does environment separation depend on chunking being deterministic?

---

**Next:** [Lesson 04 — Build and load the Azure AI Search index](../lesson04/README.md)
