# Lesson 03 — Parse and chunk the PDFs (section-aware)

**Objective:** turn five PDFs into clean, section-scoped chunks that each carry the full
Lesson 2 metadata.

**Deliverable:** `artifacts/chunks.jsonl` — one record per chunk as
`{"id", "content", "metadata": {...}}`.

---

## Why chunking decides your ceiling

Every later lesson operates on what comes out of this one. If the storm definition and the
excess clause land in the same chunk, no amount of reranking separates them. If "Section 8 —
Reserved" is dropped as empty boilerplate, DTI-014 becomes permanently unanswerable. If
section IDs are wrong, the cross-reference following in Lesson 8 has nothing to follow.

**Chunking bugs present as retrieval bugs**, which is why people spend a week tuning
retrieval when the fix was in the parser. Sanity-check the output of this lesson harder than
feels necessary.

---

## Parse: start simple

These PDFs are born-digital and clean — no scans, no columns, consistent layout. **PyMuPDF**
handles them in a few lines. Start there.

Then, separately, run **at least one** PDF through **Azure Document Intelligence (Layout
model)** and compare. Not because you need it here, but because real claims documents *are*
scanned — a loss adjuster's report, a photographed schedule, a handwritten statement — and
you should have felt the difference in effort, output structure and cost before you need to
make that call under pressure. Write down what you learn; that comparison is a legitimate
part of the capstone's design doc.

Don't reach for heavy tooling on clean PDFs. "We used Document Intelligence because the
documents needed it" is an engineering decision; "because it's the Azure service for PDFs"
isn't.

### Five extraction artefacts you will actually hit

Verified against the real files — you'll meet all of these:

**1. Running footers on every page.** Each page ends with:

```
DAVIDSTOWN INSURANCE
HomeShield Home Insurance  —  2025 Edition
DTI-HOME-PW-2025-v1.0  |  Version 1.0  |  Status: CURRENT
Effective 1 January 2025
Page 10 of 10
```

Strip it. Left in, it appends boilerplate to every chunk, dilutes embeddings, and pollutes
BM25 with terms that appear in literally every document.

*But note the irony:* that footer contains `doc_id`, version and status — genuinely useful
metadata. Harvest it as a **cross-check** against the fact matrix (does the footer's status
agree with the CSV?), then remove it from the content. Free validation.

**2. Bullets extract as lone glyphs.** PyMuPDF renders bullet lists as:

```
–
a fixed water tank, apparatus or pipe, including washing machine and dishwasher supply hoses;
–
a fixed heating system, including burst or frozen pipes;
```

The `–` sits on its own line, divorced from its text. Rejoin them or your chunks read as
fragments and sentence-based splitting misfires.

**3. The Contents page repeats every section heading.** Page 3 lists all ten `Section N —
Title` lines. A naive "split on `^Section \d+`" regex finds each heading **twice** — once on
the contents page, once at the real section — and produces phantom sections whose content is
the next line of the table of contents. **Skip pages 1–3** (cover, document control,
contents) when detecting section starts, or detect the contents page explicitly.

**4. Sections span page breaks.** Section 3 starts on page 4 and continues on page 5.
Section-aware chunking must operate on the *concatenated* document, not page by page. Keep
page numbers by tracking character offsets, since `page` is in your metadata for citations.

**5. A real text artefact in 2023 v1.1.** Its footer extracts as:

```
DTI-HOME-PW-2023-v1.1  |  Version 1.1  |  Status: SUPERSEDEDEffective 1 July 2023
```

Note `SUPERSEDEDEffective` — the space is missing. If you parse status out of the footer
with a naive regex you'll get `SUPERSEDEDEFFECTIVE` for exactly one edition and a filter
that silently matches nothing. This is a perfect miniature of why you validate parsed
metadata against a known-good source instead of trusting extraction.

---

## Chunk on section boundaries, not token counts

The instinct from generic RAG is "1000 tokens, 200 overlap". **Don't.** A chunk here should
be a **clause** — all of 3.4, "Excess" — because:

- `section_id` stays meaningful and retrievable, which is what cross-references in Lesson 8
  and `gold_sections` scoring in Lesson 10 depend on.
- Near-identical clauses across editions stay distinguishable **by metadata**, since their
  text can't distinguish them.
- The reworded-but-equivalent storm clause (2022 vs later) survives paraphrase matching
  because the whole clause is one unit.
- "Reserved" Section 8 is captured **as** Reserved, so the model can say "not offered"
  rather than hallucinate.

Fixed-size chunking would slice mid-clause, put half the excess table in one chunk and half
in another, and destroy the section IDs. On a structured legal document, structure-aware
chunking isn't a refinement — it's the only thing that works.

### The structure you're parsing

Consistent across all five editions:

```
Page 1        Cover: doc ref, edition, version, status, dates
Page 2        Document control + "Summary of changes in this version"
Page 3        Contents
Pages 4–10    Section 1 … Section 10, each with numbered clauses (3.1, 3.2, …)
```

Sections and their clause ranges:

| § | Title | Clauses |
|---|---|---|
| 1 | About your policy and definitions | Prose + definitions (Storm, Unoccupied, Flood, Flood Re) |
| 2 | Making a claim | Prose + Fraud |
| 3 | Escape of water *(and escape of fuel, 2023+)* | 3.1–3.6 (2022), 3.1–3.7 (2023+) |
| 4 | Storm, flood and weather | 4.1–4.6 |
| 5 | Fire, lightning and explosion | 5.1–5.6 |
| 6 | Theft and malicious damage | 6.1–6.7 |
| 7 | Accidental damage (optional) | 7.1–7.6 |
| 8 | **Reserved** (2022, 2023) / Home emergency (2024+) | none / 8.1–8.3 |
| 9 | General exclusions | 9.1–9.8 |
| 10 | Excess summary | Table + trailing prose |

### Four special cases to handle explicitly

**Section 8 when Reserved.** Two lines of body text, no subsections. It is *not* empty and
must not be filtered out by a minimum-length rule. Its content — "Home emergency cover is
not offered under this edition" — is the correct answer to DTI-014. Give it
`section_id = "8"` and let it through.

**Section 1's definitions.** One long section holding Storm (48/47 knots), Unoccupied
(60/45 days), Flood and, in 2025, Flood Re. DTI-003 and DTI-007 need individual definitions
retrievable. This is the one place a sub-split is justified: split on definition term. Weigh
that against keeping the section whole — decide, and write down why.

**Section 10's excess table.** Extracts as alternating label/value lines:

```
Escape of water (standard)
£350
Escape of water (shower tray / wet room)
£600
```

As-is, the association between label and figure is positional and fragile — and this table
is `gold_sections` for DTI-001, 004, 010, 016 and 018, so it matters. Reconstruct the
pairing into readable text (`"Escape of water (standard): £350"`) at parse time. Don't hope
the LLM figures out the alternation.

**Page 2's "Summary of changes".** Its own chunk, `section_id = "Document control"` to match
the QA bank. Carries the `supersedes` relationship and, for DTI-023, the *reason* a change
was made. Remember Lesson 2: for 2025 it is **incomplete** — chunk it, but don't let Lesson 8
treat it as exhaustive.

### Overlap

Use a small overlap **only inside sections long enough to need splitting** (realistically
Section 1 and Section 9). Overlap *between* sections actively hurts here: it copies text from
3.4 into the 3.5 chunk, so a search for the excess figure matches two chunks whose
`section_id` disagree, and your citations become unreliable.

---

## Chunk IDs

Every chunk needs a stable, deterministic ID — Azure AI Search keys, and you want re-runs to
update documents rather than duplicate them.

Compose it from `doc_id` + `section_id` (+ a part index when a section splits):
`DTI-HOME-PW-2024-v1.0__3.4`. Deterministic, debuggable, and it tells you what a chunk is
from the ID alone in a log line.

**Azure AI Search document keys may only contain letters, digits, `_`, `-` and `=`.** A `.`
in `3.4` is illegal. Encode it (`3_4`) and keep the human-readable `section_id` as a separate
field — don't let the key format leak into your metadata.

---

## Deliverable

`artifacts/chunks.jsonl` for all five editions, produced by `make chunks`.

Sanity checks before you move on:

1. **Per-edition chunk counts** — roughly comparable across editions. A wild outlier means a
   heading regex failed on one file.
2. `edition_year == 2024 AND section_id == "3.4"` returns **exactly one** chunk, and it's the
   escape-of-water excess clause saying £300.
3. Section 8 exists for **all five** editions — Reserved in three, Home emergency in two.
4. 2022's `3.6` is the claims-process clause; 2023+'s `3.6` is escape of fuel.
5. No chunk contains the string `"Page "` followed by a digit and `" of "` — i.e. footers
   really are gone.
6. Parsed status matches the fact matrix for every edition. (Catches the `SUPERSEDEDEffective`
   artefact.)

7. **Running `make chunks` twice produces a byte-identical file** — same SHA-256. (See
   below.)

Make these assertions in `tests/unit/test_chunking.py`, not eyeballs. You'll re-run this
pipeline a dozen times.

---

## Environments

Chunking is the one stage that must know **nothing** about environments: no settings, no
Azure calls, no `APP_ENV`. PDFs in, `chunks.jsonl` out, identical every run.

That determinism is what makes environment separation honest. In Lesson 13 the pipeline
builds `chunks.jsonl` **once per commit** and loads that same file into dev, then test, then
prod. If chunking varied between runs — dict ordering, a timestamp in each record, a set
iterated in arbitrary order — then "passed the eval in test" would mean "passed on a
slightly different corpus from the one prod is serving", and you'd have no way to prove
otherwise.

So:

- **Record the artefact's SHA-256.** Lesson 4's loader writes it into each environment's
  index manifest, and Lesson 10's scorecards record it. "Which corpus is prod serving?"
  becomes a one-line answer.
- **The Document Intelligence comparison is a dev-only experiment** against your dev
  Foundry resource. It isn't part of the pipeline, so it never needs access to test or
  prod — keep it in a notebook, not in `ingestion/`.

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Heading regex without skipping the contents page | Phantom sections from the ToC |
| Dropping short sections | Section 8 Reserved disappears; DTI-014 unanswerable |
| Chunking page-by-page | Sections split at page breaks |
| Leaving footers in content | Every chunk carries boilerplate; BM25 degraded |
| Overlap across section boundaries | Ambiguous citations, duplicate hits |
| Parsing status from the footer without validation | `SUPERSEDEDEffective` in 2023 v1.1 |
| `.` in the Search document key | Upload rejected |
| Excess table left as alternating lines | Label/figure pairing lost for five QA items |
| Non-deterministic output (timestamps, unordered iteration) | Can't prove test and prod hold the same corpus |

---

## Done when

You can filter `chunks.jsonl` to `edition_year == 2024 AND section_id == "3.4"` and get
exactly the 2024 escape-of-water excess clause — and the seven sanity checks pass as tests.

## Check yourself

1. Why is overlap *between* sections harmful here when it's standard practice elsewhere?
2. What breaks downstream if Section 8 Reserved is dropped?
3. You see 47 chunks for 2022 and 61 for 2023 v1.0. Bug or expected? How do you tell?
4. Why keep the Search document key separate from `section_id`?
5. Section 1 holds every definition. Argue both sides of sub-splitting it, then commit.
6. The footer contains status. Why parse it *and* not trust it?
7. Why does environment separation depend on chunking being deterministic?

---

**Next:** [Lesson 04 — Build and load the Azure AI Search index](Lesson04.md)
