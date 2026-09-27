# Lesson 02 — Read the corpus like an adversary; design the metadata schema

**Objective:** understand exactly how this corpus defeats naive RAG, and design the metadata
schema that beats it.

**Deliverable:** `Documentation/design/SCHEMA.md` — the metadata schema, the three policies,
and a corpus map.

> This is the most important lesson in the path. On this corpus **the metadata schema *is*
> the product.** Everything from Lesson 4 onwards is implementation detail by comparison.

---

## The central problem, stated precisely

Take DTI-004: *"A customer's kitchen flooded on 15 March 2024 when a dishwasher supply hose
burst. What excess applies?"*

The answer is £300. Here is the relevant sentence from all five editions:

| Edition | Section 3.4 text |
|---|---|
| 2022 | "The standard excess for an escape of water claim is **£250**." |
| 2023 v1.0 | "The standard excess for an escape of water claim is **£250**." |
| 2023 v1.1 | "The standard excess for an escape of water claim is **£250**." |
| 2024 | "The standard excess for an escape of water claim is **£300**." |
| 2025 | "The standard excess for an escape of water claim is **£350**." |

Now think about what an embedding model does with those five strings. They are ~98%
lexically identical. Their embeddings will be so close together that the ordering between
them is essentially **noise** — determined by tokenizer quirks around "£250" vs "£300",
not by anything meaningful.

So: you cannot retrieve the right one by similarity. Not with a better embedding model, not
with more dimensions, not with a reranker. **The distinguishing information — that this
clause was in force from 1 Jan to 31 Dec 2024 — does not appear in the clause text at all.**
It lives on the document's control page.

That's the whole lesson. The fix isn't better search; it's **putting the distinguishing
information into filterable metadata and filtering on it before you search.**

### Why "just add the year to the chunk text" doesn't work

A reasonable first instinct: prepend "2024 edition:" to each chunk so the year is in the
embedding. This helps a little and fails for three reasons:

1. **Dates aren't years.** "15 March 2024" needs a *range* comparison against
   `effective_from`/`effective_to`. Embeddings don't do arithmetic. 2023 v1.0 and v1.1 both
   say "2023".
2. **It's soft, not hard.** A similarity nudge can be outvoted. A filter cannot.
3. **It doesn't help the minority-value case.** DTI-003 asks for the 2022 storm threshold
   (48 knots) when four editions say 47. Nudging similarity still leaves four distractors in
   the candidate set; a filter deletes them.

Keep the year in the text as well — it's cheap and helps the reranker — but understand it's
a garnish, not the mechanism.

---

## The corpus map

Derived from `Data/FactMatrix/editions_fact_matrix.csv`. **Build this yourself** with
`scripts/build_corpus_map.py` rather than copying the table — the exercise is the point, and
you'll need the script again in Lesson 10.

### Editions and their effective ranges

| doc_id | Year | Ver | Status | Effective from | Effective to |
|---|---|---|---|---|---|
| `DTI-HOME-PW-2022-v1.0` | 2022 | 1.0 | ARCHIVED | 1 Jan 2022 | 31 Dec 2022 |
| `DTI-HOME-PW-2023-v1.0` | 2023 | 1.0 | SUPERSEDED | 1 Jan 2023 | **30 Jun 2023** |
| `DTI-HOME-PW-2023-v1.1` | 2023 | 1.1 | SUPERSEDED | **1 Jul 2023** | 31 Dec 2023 |
| `DTI-HOME-PW-2024-v1.0` | 2024 | 1.0 | SUPERSEDED | 1 Jan 2024 | 31 Dec 2024 |
| `DTI-HOME-PW-2025-v1.0` | 2025 | 1.0 | CURRENT | 1 Jan 2025 | 31 Dec 2025 |

The ranges are contiguous and non-overlapping, so a loss date maps to **exactly one**
edition. That's the property your whole retrieval strategy rests on — verify it in code
rather than trusting this table.

**The 30 June / 1 July 2023 boundary is the most important date in the corpus.** It's the
only place where a single calendar year splits into two editions, and it's what makes a
year-level filter insufficient.

### What changes where

| Fact | 2022 | 23 v1.0 | 23 v1.1 | 2024 | 2025 |
|---|---|---|---|---|---|
| `standard_excess` | £250 | £250 | £250 | **£300** | **£350** |
| `eow_wetroom_excess` | £500 | £500 | £500 | **£600** | £600 |
| `trace_access_limit` | £5,000 | £5,000 | £5,000 | **£7,500** | **£10,000** |
| `gradual_leak_days` | 14 | 14 | 14 | **21** | 21 |
| `frozen_drain_days` | 30 | 30 | 30 | 30 | **45** |
| `storm_knots` | **48** | **47** | 47 | 47 | 47 |
| `outbuildings_limit` | £1,000 | **£1,500** | £1,500 | £1,500 | **£2,000** |
| `flood_excess` | £1,000 | £1,000 | £1,000 | **£1,500** | £1,500 |
| `weather_multi_hours` | 72 | 72 | 72 | 72 | **96** |
| `emergency_repair_limit` | £500 | £500 | £500 | **£750** | **£1,000** |
| `pedal_cycle_limit` | £500 | £500 | **£600** | **£750** | £750 |
| `unoccupied_days` | 60 | 60 | 60 | 60 | **45** |
| `ad_excess` | £150 | £150 | £150 | £150 | **£200** |
| `buildings_limit` | £500k | £500k | £500k | **£750k** | **£1m** |
| `contents_limit` | £75k | £75k | £75k | **£100k** | £100k |
| `police_hours` | **48** | **24** | 24 | 24 | 24 |
| `fuel_limit` | — | £2,000 | £2,000 | **£2,500** | £2,500 |
| `he_limit` | — | — | — | £1,000 | **£1,500** |

Clause existence (absent → present):

| Clause | First appears | Section |
|---|---|---|
| `escape_of_fuel` | 2023 v1.0 | 3.6 |
| `communicable_disease_excl` | 2023 v1.0 | 9.6 |
| `excess_per_claim_clarification` | **2023 v1.1** | 10 (end) |
| `home_emergency` | 2024 | 8 |
| `matching_sets` | 2024 | — |
| `ev_charger` | 2025 | 7.4 |
| `flood_re_note` | 2025 | 1, 4.1 |

Read that last table next to the one above it. **Every single fact changes at a different
point.** There is no "2024 was the big change" shortcut — you cannot cache a mental model
of which edition is "roughly right". Only per-fact, per-edition lookup works.

---

## The four traps, and what each one teaches

### Trap 1 — DTI-014: the table contradicts the wording

`editions_fact_matrix.csv` records `he_limit = 1000` against 2022, 2023 v1.0 and 2023 v1.1.

Open `DTI-HOME-PW-2022-v1.0.pdf` and read Section 8:

> **Section 8 — Reserved**
> This section number is reserved and is not in use in this edition of the wording. Home
> emergency cover is not offered under this edition.

The table is **wrong**. Home emergency didn't exist before 2024. A system that ingests the
CSV as fact will tell a claims handler that a 2022 policyholder has £1,000 of home emergency
cover — cover that was never sold, never priced, never underwritten. In a real insurer that
is a mis-statement of cover.

This is why **source-of-truth is policy #1** and why it needs to be a hard rule in the
prompt *and* a check in code, not a hope.

> **A second instance nobody has written down.** The same CSV carries `fuel_limit = 2000`
> against 2022, while `escape_of_fuel = False` for that edition — and the 2022 PDF's Section
> 3.6 is the claims-process clause, with no escape-of-fuel cover anywhere. Identical trap,
> undocumented. If your Lesson 10 evaluator only special-cases `he_limit`, you've patched a
> symptom. **Handle the class, not the instance:** a numeric limit in the table means nothing
> unless the corresponding clause exists in that edition's wording.

Finding that yourself is the real exercise here. Diff the boolean columns against the
numeric ones and see which other pairs disagree.

### Trap 2 — DTI-013: the section number is a decoy

| Edition | Section 3.6 is… |
|---|---|
| 2022 | **Claims process** |
| 2023+ | **Escape of oil or fuel** |

And the section *title* changes too: "Section 3 — Escape of water" in 2022 becomes "Section
3 — Escape of water and escape of fuel" from 2023.

So `section_id` is only meaningful **paired with `doc_id`**. A filter of `section_id eq
'3.6'` across editions returns two completely different clauses. Anywhere you use a section
number — filters, citations, cross-reference following in Lesson 8, the `gold_sections`
evaluator in Lesson 10 — the pair `(doc_id, section_id)` is the key, never `section_id`
alone.

### Trap 3 — DTI-022: the authoritative-looking incomplete summary

Page 2 of the 2025 edition has a "Summary of changes in this version" listing eight changes.
It reads like exactly the chunk you want for "what changed between 2024 and 2025".

It omits four real changes: `outbuildings_limit` (£1,500 → £2,000),
`emergency_repair_limit` (£750 → £1,000), `ad_excess` (£150 → £200) and `he_limit` (£1,000 →
£1,500).

A retriever will rank that summary chunk first, and a generator will trust it. Full credit
requires **diffing the wording**, not quoting the summary. This is a genuinely realistic
failure: real change logs are written by humans under deadline and are routinely incomplete.

### Trap 4 — DTI-024: the strong retrieval hit that doesn't contain the answer

*"What was the standard excess under the 2021 edition, DTI-HOME-PW-2021-v1.0?"*

That document reference appears **verbatim** in the 2022 edition's control page, as the
`supersedes` value. So the string match is perfect, retrieval returns a high-scoring chunk
with the exact document ID in it, and a naive generator reasons: "I found the 2021 edition
reference, the nearby excess is £250, therefore £250."

The 2021 wording is not in the corpus. The correct answer is a refusal.

**The lesson: retrieval confidence is not answer confidence.** A chunk scoring 0.95 can be
the exact chunk that proves you *can't* answer. Abstention has to be a decision made on
content, not on scores.

---

## The metadata schema

Every chunk carries all of this. Design it now; you'll implement it as
`ChunkMetadata` in `src/dti_rag/models.py` in Lesson 3.

| Field | Type | Index behaviour | Why it exists |
|---|---|---|---|
| `doc_id` | string | filterable, retrievable | The join key across PDFs, CSVs, QA bank, citations |
| `edition_year` | int | filterable, facetable | Explicit-year queries ("the 2024 edition") |
| `version` | string | filterable | Distinguishes 2023 v1.0 from v1.1 |
| `status` | string | filterable, facetable | Resolves "current" without keyword matching |
| `effective_from` | **DateTimeOffset** | filterable | Loss-date range filters |
| `effective_to` | **DateTimeOffset** | filterable | Loss-date range filters |
| `supersedes` | string | retrievable | Change-history questions (DTI-023) |
| `superseded_by` | string | retrievable | Same |
| `section_id` | string | filterable | e.g. `"3.4"`. Meaningful only with `doc_id` |
| `section_title` | string | searchable, retrievable | Feeds the semantic ranker's title field |
| `page` | int | retrievable | Citations a human can verify |

### Decisions to make now, because they're painful later

**`effective_from` / `effective_to` must be `Edm.DateTimeOffset`, not strings.** Range
comparison on a string does the wrong thing, silently. This is the single most consequential
type choice in the index.

**Normalise `status` case and write it down.** The CSV says `CURRENT`; the PDF footer says
`Status: CURRENT`; the learning path prose says `Current`. OData string equality **is
case-sensitive** — `status eq 'Current'` returns nothing against a value of `CURRENT`, with
no error. Pick one form, enforce it at ingestion, and put it in `SCHEMA.md`.

**Keep `version` a string.** `1.10` would sort before `1.2` numerically and `"1.1"` is not a
float you want to compare. You need equality, not ordering.

**Decide what `section_id` looks like for non-numbered content.** The control page, the
contents page and the Section 10 excess table aren't "3.4". The QA bank uses the literal
string `"Document control"` in `gold_sections` for DTI-022/023/024 — so match that exactly,
or your Lesson 10 retrieval evaluator scores zero on items your retriever actually got
right.

---

## The three policies

These start as prose here and become prompt rules (Lesson 8), router logic (Lesson 7) and
evaluators (Lesson 10). Write them properly in `SCHEMA.md`.

### 1. Source-of-truth policy

> **The policy wording PDF is authoritative.** The CSVs are convenience and evaluation data
> only. Where they disagree, the wording is right.
>
> Concretely: never assert that cover exists on the strength of a table value. A numeric
> limit means nothing unless the corresponding clause exists in that edition's wording.
> Where a section is marked **Reserved**, that is a positive statement that the cover is
> **not offered** — surface it as such.

### 2. Edition-selection policy

> - **Loss date given** → the edition where `effective_from ≤ date ≤ effective_to`. Exactly
>   one qualifies. Never select by recency.
> - **No date given** → default to `status = CURRENT`, **and state that earlier editions
>   differ.** The caveat is part of the correct answer, not politeness.
> - **Bare year mapping to two editions (2023)** → ambiguous. Ask for the loss date, or
>   return both values with their effective ranges. **Returning one value is a failure even
>   when that value is right.**
> - Always surface which edition governed and why. A handler must be able to check it.

### 3. Abstention policy

> If the answer isn't in the retrieved wording, say so.
>
> - A document referenced but not held (the 2021 edition) cannot be answered from
>   neighbouring editions. Don't extrapolate backwards.
> - A subject the wording doesn't cover (motor) is out of scope. Don't answer from general
>   insurance knowledge — cite the nearest relevant clause and decline.
> - Abstention is a **successful** outcome, and Lesson 10 scores it as one. Build the habit
>   now of treating "I can't answer that" as a feature.

---

## Environments

`SCHEMA.md` is the contract for **all three** indexes — dev's, test's and prod's — not a
description of the one on your laptop. Nothing in it may vary by environment: no "extra
debug field in dev", no looser types in test. The index schema sits in Lesson 1's "must
match" table for a reason — if test's index differs from prod's, the eval gate is scoring a
different system.

When the schema changes later, the change ships like code: it gets a new schema version
(Lesson 4), the new index is built in dev, and the pipeline builds it in test and then prod.
Nobody edits an index definition in the portal, in any environment.

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Treating the CSVs as ground truth for *answers* | You ship the DTI-014 bug |
| `section_id` without `doc_id` | 2022's 3.6 answers a 2023 fuel question |
| Dates stored as strings | Range filters silently wrong |
| `status` case mismatch | Filter returns zero results, no error |
| Year filter instead of date filter | The 2023 v1.0/v1.1 split is invisible |
| Treating the 2025 change summary as complete | DTI-022 loses four changes |
| Dropping "Reserved" sections as empty | DTI-014 becomes unanswerable |

---

## Deliverable

`Documentation/design/SCHEMA.md` containing:

1. The metadata field table, with types and index behaviour, and the normalisation
   decisions (status case, version-as-string, `section_id` for unnumbered content).
2. The three policies, written as rules you could hand to another engineer.
3. The corpus map — editions, effective ranges, and which facts change where.
4. A short "known traps" section including the **second** table-vs-wording conflict you
   found yourself.

## Done when

You can state, from memory and without hedging, **why naive top-k vector search returns the
wrong excess for a dated 2024 claim** — and why a better embedding model wouldn't fix it.

## Check yourself

1. Why doesn't prepending "2024 edition:" to every chunk solve DTI-004?
2. `section_id eq '3.6'` — what comes back, and why is that a bug?
3. Which fact changes at 2023 v1.1 and nowhere else? Why does it exist? *(Hint: read the
   v1.1 change summary — it tells you the motivation, which is worth citing in an answer.)*
4. DTI-024 retrieves a chunk containing the exact string `DTI-HOME-PW-2021-v1.0`. Why is
   that a reason to abstain rather than to answer?
5. You store `effective_from` as `"1 January 2024"`. Give a concrete query that now returns
   the wrong edition.
6. Besides `he_limit`, which other CSV column asserts a value for an edition where the
   clause doesn't exist?

---

**Next:** [Lesson 03 — Parse and chunk the PDFs](Lesson03.md)
