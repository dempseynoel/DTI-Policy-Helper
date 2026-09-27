# Lesson 02 — Read the corpus like an adversary; design the metadata schema

**Objective:** understand exactly how this corpus defeats naive RAG, and design the metadata
schema and the three policies that beat it.

**Deliverables:**

- `documentation/design/SCHEMA.md`: the metadata schema, the three policies, the known traps
- `scripts/build_corpus_map.py` → `documentation/design/corpus_map.md`

> The most important lesson in the path. On this corpus **the metadata schema is the
> product**; everything from Lesson 04 on is implementation.
>
> **Try this lesson before opening `files/`.** Write your own `SCHEMA.md` and hunt for the
> traps yourself, then compare. The provided `SCHEMA.md` lists traps you're meant to find.

---

## The central problem, stated precisely

DTI-004: *"A customer's kitchen flooded on 15 March 2024 when a dishwasher supply hose
burst. What excess applies?"* The answer is £300. Here's clause 3.4 in all five editions:

| Edition | Section 3.4 |
|---|---|
| 2022 | "The standard excess for an escape of water claim is **£250**." |
| 2023 v1.0 | "The standard excess for an escape of water claim is **£250**." |
| 2023 v1.1 | "The standard excess for an escape of water claim is **£250**." |
| 2024 | "The standard excess for an escape of water claim is **£300**." |
| 2025 | "The standard excess for an escape of water claim is **£350**." |

Those strings are ~98% identical, so their embeddings are so close that the order between
them is **noise**. No embedding model, dimension count or reranker fixes that. **The
distinguishing fact (this clause was in force 1 January–31 December 2024) isn't in the clause
text at all.** It's on the document-control page.

The fix isn't better search. It's **putting the distinguishing information into filterable
metadata, and filtering on it before you search.**

### Why "just add the year to the chunk text" doesn't work

1. **Dates aren't years.** "15 March 2024" needs a range comparison against
   `effective_from`/`effective_to`, and embeddings don't do arithmetic. Both 2023 editions
   say "2023".
2. **It's soft.** A similarity nudge can be outvoted; a filter can't.
3. **It doesn't help the minority value.** DTI-003 asks for 2022's storm threshold (48 knots)
   when four editions say 47. A nudge leaves four distractors in the candidate set; a filter
   removes them.

Keep an edition header in the chunk text anyway (Lesson 03 does). It's cheap and helps the
reranker, but it's not the mechanism.

---

## The corpus map

Run the provided script rather than copying the table:

```bash
python scripts/build_corpus_map.py > documentation/design/corpus_map.md
```

It prints the editions and their effective ranges, every fact that changes (bold where it
changes), when each clause first appears, and the table-vs-wording conflicts.

The ranges are contiguous and non-overlapping, so **a loss date maps to exactly one
edition**. Your whole retrieval strategy rests on that property, and Lesson 07 verifies it in
code rather than trusting a table.

**30 June / 1 July 2023 is the most important boundary in the corpus**: the only place one
calendar year splits into two editions, and the reason a year filter isn't enough.

Read the "what changes where" table next to the clause-existence table. **Every fact changes
at a different point.** There's no "2024 was the big change" shortcut; only per-fact,
per-edition lookup works.

---

## The traps, and what each one teaches

### Trap 1 — DTI-014: the table contradicts the wording

The fact matrix records `he_limit = 1000` for 2022, 2023 v1.0 and 2023 v1.1. The 2022 PDF's
Section 8 says:

> **Section 8 — Reserved.** This section number is reserved and is not in use in this edition
> of the wording. Home emergency cover is not offered under this edition.

The table is **wrong**. A system that trusts it tells a handler a 2022 policyholder has
£1,000 of home-emergency cover that was never sold. That's why source-of-truth is policy #1.

**The same trap, undocumented:** `fuel_limit = 2000` against 2022, where `escape_of_fuel =
False` and the 2022 wording has no escape-of-fuel clause (its 3.6 is the claims process).
Handle the class, not the instance: **a limit means nothing unless its clause exists in that
edition's wording.** The corpus-map script's conflict section finds both.

### Trap 2 — DTI-013: the section number is a decoy

| Edition | 3.6 is… |
|---|---|
| 2022 | Claims process |
| 2023 onwards | Escape of oil or fuel |

**And it happens twice.** Section 9 is renumbered too: 2022 has 9.1–9.7 with "how
exclusions interact" at **9.6**; from 2023, 9.6 is the new communicable-disease exclusion and
the interaction rule moves to **9.7** (the clause DTI-017 and DTI-018 depend on). So
`section_id` only means something **paired with `doc_id`**, everywhere: filters, citations,
cross-references, evaluators.

### Trap 3 — DTI-022: the authoritative-looking incomplete summary

Page 2 of the 2025 edition lists eight changes. It omits four real ones: outbuildings
(£1,500 → £2,000), emergency repairs (£750 → £1,000), the accidental-damage excess (£150 →
£200) and the home-emergency limit (£1,000 → £1,500). A retriever ranks that summary first
and a generator trusts it. Full credit needs **a diff of the wording**.

**The mirror image, also undocumented:** the 2024 summary announces a new "matching items,
pairs and sets" basis of settlement **that appears nowhere in the 2024 wording.** A summary
can omit real changes *and* assert changes that don't exist. The wording wins both ways.

### Trap 4 — DTI-024: a strong retrieval hit that doesn't contain the answer

*"What was the standard excess under the 2021 edition, DTI-HOME-PW-2021-v1.0?"* That document
reference appears verbatim on the 2022 control page (as what 2022 supersedes). Retrieval
scores it highly; a naive generator finds £250 nearby and answers. The 2021 wording isn't
held, so the right answer is a refusal. **Retrieval confidence is not answer confidence.**

### Trap 5 — the current edition has expired

The CURRENT edition's `effective_to` is **31 December 2025**. A loss dated in 2026 falls
inside no held edition. "Current" is a status, not a date range: the system must say no held
edition was in force, not silently apply 2025.

---

## The metadata schema

Every chunk carries every field. Lesson 03 implements it as `ChunkMetadata`, and Lesson 04 as
the index fields. The full table is in `SCHEMA.md`; the decisions that matter:

| Field | Type | Why |
|---|---|---|
| `doc_id` | string, filterable | The join key everywhere |
| `edition_year`, `version` | int, string | "The 2024 edition"; 2023 v1.0 vs v1.1. `version` is a string: you need equality, not ordering |
| `status` | string, filterable | "Current", without keyword matching |
| `effective_from`, `effective_to` | **DateTimeOffset** | Loss-date range filters. A string silently compares wrongly |
| `section_id` | string | `"3.4"`, `"8"`, `"Document control"`: only meaningful with `doc_id` |
| `section_group` | string | The top-level section (`"3"` for 3.4), so Lesson 08 can retrieve a whole section when a clause says "assessed under Section 3" |
| `section_title`, `chunk_kind`, `page` | | The reranker's title; what kind of text it is; citations a human can check |

### Decisions to make now, because they're painful later

- **`status` is upper case** (`CURRENT`). The cover page says `Current`, the footer and CSV
  say `CURRENT`, and OData equality is case-sensitive: `status eq 'Current'` returns nothing,
  silently.
- **Dates are midnight UTC, and queries use dates, never times.** Then
  `effective_to ge 2023-06-30T00:00:00Z` includes 30 June. Test both boundary days.
- **Unnumbered content**: page 2 is `section_id = "Document control"` (the exact string the
  QA bank's `gold_sections` uses), Section 10's table is `"10"`, and the cover and contents
  pages aren't chunked.
- **Section 1's definitions** are one chunk each, all with `section_id = "1"`.

---

## The three policies

These start as prose here and become router logic (Lesson 07), prompt rules (Lesson 08), code
checks (Lesson 11) and evaluators (Lesson 10). They're written out in full in `SCHEMA.md`:

1. **Source of truth.** The wording is authoritative; the CSVs are convenience data. A limit
   means nothing without its clause. Reserved = not offered. *(One narrow, verified exception:
   the edition-registry columns drive date resolution, and Lesson 03 tests them against every
   PDF.)*
2. **Edition selection.** Loss date → the edition in force (outside every range → abstain).
   Named edition → that edition. Bare 2023 → ambiguous: both values, both ranges, ask for the
   date. Nothing temporal → current, **plus "earlier editions differ"**. "Does X exist / has
   it changed" → every edition. Always say which edition and why.
3. **Abstention.** Not in the wording → say so. An edition not held can't be answered from
   its neighbour; an out-of-scope subject (motor) gets the nearest clause cited and a
   decline. Abstention is a **successful** outcome.

---

## Environments

`SCHEMA.md` is the contract for **all three** indexes. Nothing in it varies by environment:
no "extra debug field in dev", no looser types in test. A schema change ships like code: a
new `SCHEMA_VERSION` (Lesson 04), built in dev, then built by the pipeline in test and prod.
Nobody edits an index definition in the portal.

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `scripts/build_corpus_map.py` | new | Derives the corpus map and the table-vs-wording conflicts from the fact matrix |
| `documentation/design/corpus_map.md` | new | Its output, committed |
| `documentation/design/SCHEMA.md` | new | Schema, normalisation decisions, the three policies, known traps |

## Project structure at the end of this lesson

```text
DTI-Policy-Helper/
├── data/
│   ├── fact_matrix/  (editions_fact_matrix.csv, fact_lookup_long.csv: convenience data)
│   ├── policy_documents/  (the 5 policy wording PDFs: authoritative)
│   └── question_answers/  (dti_rag_qa_bank.jsonl and .csv, README.md: ground truth for scoring)
├── deploy/
│   ├── dev.env  ◇ generated
│   └── environments.yaml
├── documentation/
│   ├── design/
│   │   ├── corpus_map.md  ★ new
│   │   └── SCHEMA.md  ★ new
│   └── lessons/  (this course)
├── infra/  (Terraform: modules/environment, shared, dev, test, prod)
├── scripts/
│   ├── build_corpus_map.py  ★ new
│   └── smoke_test.py
├── src/
│   └── dti_rag/
│       ├── __init__.py
│       ├── clients.py
│       ├── config.py
│       └── constants.py
├── tests/
│   └── unit/
│       └── test_config.py
├── .gitignore
├── Makefile
├── .pre-commit-config.yaml
├── pyproject.toml
├── .python-version
└── README.md
```

`★ new` in this lesson · `✎ changed` in this lesson · `◇ generated` by running the code (git-ignored or produced by you) · unmarked: unchanged from earlier lessons

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Treating the CSVs as ground truth for answers | You ship the DTI-014 bug |
| `section_id` without `doc_id` | 2022's 3.6 answers a 2023 fuel question; 2022's 9.6 cited as communicable disease |
| Dates stored as strings | Range filters silently wrong |
| `status` case mismatch | Zero results, no error |
| Year filter where a date filter is needed | The 2023 v1.0/v1.1 split is invisible |
| Trusting a change summary, either way | DTI-022 loses four changes; 2024 gains one that doesn't exist |
| Dropping "Reserved" sections as empty | DTI-014 becomes unanswerable |
| Treating "current" as "in force today" | A 2026 loss answered from the 2025 edition |

## Done when

You can state, from memory and without hedging, **why naive top-k vector search returns the
wrong excess for a dated 2024 claim**, and why a better embedding model wouldn't fix it. And
`SCHEMA.md` lists both table-vs-wording conflicts.

## Check yourself

1. Why doesn't prepending "2024 edition:" to every chunk solve DTI-004?
2. `section_id eq '3.6'`: what comes back, and why is it a bug? Name the second place in the
   corpus where the same thing happens.
3. Which fact changes at 2023 v1.1 and nowhere else? (Read the v1.1 change summary: it gives
   the motivation, which is worth citing in an answer.)
4. DTI-024 retrieves a chunk containing the exact string `DTI-HOME-PW-2021-v1.0`. Why is that
   a reason to abstain?
5. You store `effective_from` as `"1 January 2024"`. Give a concrete query that now returns
   the wrong edition.
6. A loss happened on 1 February 2026. What should the system say, and why?

---

**Next:** [Lesson 03 — Parse and chunk the PDFs](../lesson03/README.md)
