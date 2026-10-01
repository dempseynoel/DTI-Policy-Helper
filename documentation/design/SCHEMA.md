# Schema and policies

The contract for every chunk, every index (dev, test and prod alike) and every answer. On this corpus **the metadata schema is the product**: vector similarity can't tell the five editions apart; metadata can.

Nothing here varies by environment. A change to this file is a schema change: it bumps `SCHEMA_VERSION` in `src/dti_rag/search/schema.py` (Lesson 04) and ships like code.

---

## 1. Chunk metadata

Every chunk carries every field. Implemented as `ChunkMetadata` in `src/dti_rag/models.py` (Lesson 03) and as the index fields in `src/dti_rag/search/schema.py` (Lesson 04).

| Field | Type | Index behaviour | Why it exists |
|---|---|---|---|
| `id` | string | key | `<doc_id>__<section_id>[__<part>]`, with every character outside `[A-Za-z0-9_-=]` replaced by `_` |
| `content` | string | searchable (English analyzer) | The clause text, with a one-line edition header |
| `contentVector` | 3072 × single | vector (HNSW + vectorizer) | Dense retrieval |
| `doc_id` | string | filterable, facetable | The join key across PDFs, CSVs, QA bank and citations. Never normalised |
| `edition_year` | int | filterable, facetable, sortable | "The 2024 edition" |
| `version` | string | filterable | 2023 `1.0` vs `1.1`. A string: you need equality, not ordering |
| `status` | string | filterable, facetable | `ARCHIVED` / `SUPERSEDED` / `CURRENT` |
| `effective_from` | DateTimeOffset | filterable, sortable | Loss-date range filters |
| `effective_to` | DateTimeOffset | filterable, sortable | Loss-date range filters |
| `supersedes` | string | retrievable | Change history (DTI-023) |
| `superseded_by` | string | retrievable | Change history |
| `section_id` | string | filterable | `"3.4"`, `"8"`, `"Document control"`. Meaningful only with `doc_id` |
| `section_group` | string | filterable | The top-level section: `"3"` for `3.4`. Cross-reference following retrieves a whole section by it (Lesson 08) |
| `section_title` | string | searchable | `"Escape of water and escape of fuel › Excess"`. The semantic ranker's title field |
| `chunk_kind` | string | filterable | `document_control`, `definition`, `section_intro`, `clause`, `excess_summary` |
| `page` | int | retrievable | Citations a human can check |
| `metadata_json` | string | retrievable only | The metadata as JSON, for framework interop (LlamaIndex requires it, Lesson 09) |

### Normalisation decisions

- **`status` is upper case**: `CURRENT`, `SUPERSEDED`, `ARCHIVED`. The cover page says `Current`, the footer says `CURRENT`, the CSV says `CURRENT`. OData string equality is case-sensitive, so `status eq 'Current'` silently returns nothing. Normalised at ingestion.
- **`version` is a string** (`"1.0"`, `"1.1"`).
- **Dates are midnight UTC.** `effective_from` and `effective_to` are stored as `YYYY-MM-DDT00:00:00Z`. Queries only ever filter on a **date** (never a time), also normalised to midnight, so `effective_to ge 2023-06-30T00:00:00Z` includes 30 June. Both boundary days (30 June and 1 July 2023) are unit-tested (Lessons 06 and 07).
- **Unnumbered content**: page 2 is `section_id = "Document control"` (matching the QA bank's `gold_sections`), Section 10's table is `"10"`, and the cover and contents pages aren't chunked.
- **Section 1 definitions** are split one definition per chunk (Storm, Unoccupied, Flood, Flood Re, ...). Every one keeps `section_id = "1"`, so it matches the QA bank, and gets a part suffix on its `id`. DTI-003 and DTI-007 need a single definition retrievable on its own.
- **Section 8 when Reserved** is a real chunk, `section_id = "8"`, whose text says the cover is not offered. It must never be dropped by a minimum-length rule.

---

## 2. The three policies

These become router logic (Lesson 07), prompt rules (Lesson 08), code checks (Lesson 11) and evaluators (Lesson 10).

### Source-of-truth policy

> **The policy wording PDF is authoritative.** The CSVs are convenience and evaluation data. Where they disagree, the wording is right.
>
> A numeric limit means nothing unless the clause it limits exists in that edition's wording. A section marked **Reserved** is a positive statement that the cover is **not offered**.
>
> One narrow exception, verified rather than trusted: the edition registry columns of the fact matrix (`doc_id`, year, version, status, effective dates, supersedes) drive date-to-edition resolution. A unit test (Lesson 03) proves they match every PDF's document-control page.

### Edition-selection policy

> - **Loss date given:** the edition where `effective_from ≤ date ≤ effective_to`. Exactly one qualifies. Never select by recency.
> - **Loss date outside every held edition** (before 2022, or after 31 December 2025): abstain. Say which editions are held and their ranges.
> - **Edition named:** that edition. A bare year that maps to two editions (2023) is **ambiguous**: return both values with their effective ranges and ask for the loss date. Returning one value is a failure even when that value is right.
> - **A named edition not held** (2021): abstain.
> - **Nothing temporal:** default to `status = CURRENT` **and say earlier editions differ**. The caveat is part of the correct answer.
> - **"Does X exist / when did X change":** every held edition, answered per edition.
> - Always return the governing edition **and the reason it was chosen**.

### Abstention policy

> If the answer isn't in the retrieved wording, say so.
>
> - A document referenced but not held (the 2021 edition) can't be answered from a neighbouring edition.
> - A subject the wording doesn't cover (motor) is out of scope. Cite the nearest relevant clause and decline. Don't answer from general insurance knowledge.
> - Abstention is a **successful** outcome and is scored as one.

---

## 3. Corpus map

Generated: see [`corpus_map.md`](corpus_map.md) (`uv run python scripts/build_corpus_map.py`).

The ranges are contiguous and non-overlapping, so a loss date maps to exactly one edition. **30 June / 1 July 2023** is the only mid-year boundary, and the reason a year filter isn't enough.

---

## 4. Known traps

| Trap | Where | Consequence if missed |
|---|---|---|
| Table says `he_limit = £1,000` for 2022–2023; Section 8 is **Reserved** there | DTI-014 | Reports cover that was never sold |
| Table says `fuel_limit = £2,000` for 2022; no escape-of-fuel clause exists in 2022 | Same class, undocumented | Same harm |
| `3.6` is the claims process in 2022 and escape of fuel from 2023 | DTI-013 | A section filter across editions returns two different clauses |
| Section 9 is renumbered: 2022 has 9.1–9.7 with "how exclusions interact" at **9.6**; from 2023 communicable disease is 9.6 and the interaction rule moves to **9.7** | DTI-012, DTI-017, DTI-018 | Citing "9.7" for 2022 cites claim limits |
| The 2025 change summary omits four changes (outbuildings, emergency repairs, AD excess, home-emergency limit) | DTI-022 | A summary quoted as complete |
| The 2024 change summary announces a "matching items, pairs and sets" basis of settlement that **appears nowhere in the 2024 wording** | Not in the QA bank | A summary asserting wording that doesn't exist. The wording wins |
| `DTI-HOME-PW-2021-v1.0` appears verbatim on the 2022 control page | DTI-024 | Strong retrieval hit, no answer in it |
| The 2023 v1.1 footer extracts as `Status: SUPERSEDEDEffective 1 July 2023` | Ingestion | Status parsed as `SUPERSEDEDEFFECTIVE`; filter matches nothing |
| The CURRENT edition's `effective_to` is 31 Dec 2025, which has passed | Router | A loss date in 2026 has no governing edition in the corpus. Abstain; don't fall back to "current" |
