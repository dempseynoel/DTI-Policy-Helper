# Lesson 05 — The naive baseline, and watch it fail on purpose

**Objective:** build the RAG pipeline everyone builds first, run all 25 questions through it,
and document exactly how and why it fails.

**Deliverables:**

- `src/dti_rag/retrieval/baseline.py`: embed → vector top-5, **no filters** → stuff → generate
- `evaluation/`: the first scaffolding of the eval harness (QA bank loader, run rows, checks,
  run metadata) and `run_baseline.py`
- `evaluation/baselines/naive-baseline-dev.json` (raw output, **committed**)
- `documentation/design/baseline_failures.md`: each failure mapped to its mechanism

---

## Why deliberately build something bad

**You need a control group.** "Our RAG system gets 88%" means nothing. "Naive RAG scored X,
edition-aware retrieval scored Y, and here's where the difference came from, by category" is
an engineering result. Lesson 10 needs this baseline to say that.

**You need to feel the failure.** Watching your pipeline answer £350 to a £300 question, with
a fluent, well-cited-looking explanation, is what stops you trusting a demo that looks fine.

**It's the strongest thing to show a stakeholder.** Same question, same corpus, same model:
one pipeline says £350 and the other says £300.

---

## Build it thin, and keep it thin

`baseline.py` embeds the question, runs a pure vector search (top 5, no filter), joins the
chunks into a prompt, and asks `chat` (temperature 0) to "answer using only the context".

> **This file must never be improved.** Its job is to stay naive so every later comparison
> is honest. The warning is at the top of the file, for your future self.

Use a *reasonable* naive prompt, though. A deliberately hobbled prompt rigs the comparison
the other way; "answer only from the context" is what a competent engineer writes on day one.

---

## The five mechanisms to watch for

Run all 25 (`make baseline ENV=dev`), but these five show the distinct ways it fails:

| QA | Question (abridged) | Expected failure | Mechanism |
|---|---|---|---|
| DTI-004 | Kitchen flooded 15 March 2024. Excess? | £350 or a mix, not £300 | Five near-identical 3.4 clauses in noise order; the loss date is in no chunk. **Watch for the confident version:** "£350" with a fluent explanation and no uncertainty signal |
| DTI-003 | 2022 wording: storm wind speed? | 47 knots, not 48 | Minority value outvoted. RAG has no notion of authority, only similarity, and five similar chunks vote |
| DTI-008 | Pedal cycle limit in 2023? | One figure | Genuine ambiguity collapsed. **£600 alone is a failure even though it's a real 2023 value.** Most teams never measure this |
| DTI-014 | Is home emergency cover available? | Describes the cover | No edition scope; if it saw the fact matrix it'd confirm £1,000 for 2022. A customer told they have cover they never bought |
| DTI-024 | 2021 edition's excess? | £250 | The exact doc reference is on the 2022 control page. **Retrieval confidence became answer confidence** |

---

## What to record, and why

`run_baseline.py` records, per question: the answer, the retrieved `(doc_id, section_id,
score)`, the retrieved text, and the latency. The report it prints adds whether a **gold
document** and a **gold section** were retrieved, and the `must_include` / `must_not_include`
results.

The gold-retrieved column is the diagnostic that matters, because it splits failures in two:

| Gold doc retrieved? | Diagnosis | Fixed in |
|---|---|---|
| No | **Retrieval failure**: the right text never arrived | 06–07 |
| Yes, but the answer's wrong | **Generation failure**: right text, wrong reasoning | 08 |

Most baseline failures here are the first kind. Knowing that tells you to spend effort on
retrieval, not prompts; teams that skip this step tune prompts against a retrieval problem
for weeks.

**`must_include` checks are deliberately strict** (`evaluation/checks.py`): case-insensitive,
whitespace-collapsed, figures exact ("£300" ≠ "300 pounds"), and short words like "not"
matched as whole words so "note" doesn't count. Lesson 10 builds on this.

### Provenance, recorded with every run

A baseline compared across environments is only honest if both runs used the same models and
corpus. So the run's metadata (`evaluation/runmeta.py`) records: `app_env`, git SHA, prompt
version, temperature, **the model and version actually serving each deployment, read from the
Foundry resource at run time** (not copied from your notes), the index manifest and the
throttled-response count.

---

## Run it

```bash
documentation/lessons/apply_lesson.sh 05
make baseline ENV=dev
```

Then fill in `documentation/design/baseline_failures.md` from the printed table, and commit
it **and** `evaluation/baselines/naive-baseline-dev.json`. Lesson 10 re-scores that JSON with
the full evaluator set, with no need to regenerate.

---

## Environments

**Run the baseline in dev.** This lesson is the likeliest to produce a runaway loop, and
dev's TPM cap and budget alert are there to catch it. `baseline.py` reads configuration like
everything else, with no endpoint in the file, so it runs unchanged anywhere.

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `src/dti_rag/retrieval/__init__.py` | new | The package |
| `src/dti_rag/retrieval/results.py` | new | Search result → `RetrievedChunk`; the fields to select |
| `src/dti_rag/retrieval/baseline.py` | new | The naive pipeline. Never improve it |
| `src/dti_rag/models.py` | changed | `RetrievedChunk` |
| `evaluation/__init__.py` | new | The harness package, outside `src/` |
| `evaluation/qa_bank.py` | new | Load the 25 questions |
| `evaluation/rows.py` | new | `RunRow`, `RunMeta`, `Run`: running is separate from scoring |
| `evaluation/checks.py` | new | `must_include` / `must_not_include`, gold doc and gold section hits |
| `evaluation/runmeta.py` | new | Provenance: environment, serving model versions, manifest, git |
| `evaluation/run_baseline.py` | new | `make baseline ENV=…` |
| `tests/unit/test_checks.py` | new | Normalisation rules; section hits need the doc/section pair |
| `documentation/design/baseline_failures.md` | new | The template you fill in |
| `Makefile` | changed | `make baseline`; lint covers `evaluation/` |

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
│   │   ├── baseline_failures.md  ★ new
│   │   ├── corpus_map.md
│   │   └── SCHEMA.md
│   └── lessons/  (this course)
├── evaluation/
│   ├── baselines/
│   │   └── naive-baseline-dev.json  ◇ generated
│   ├── __init__.py  ★ new
│   ├── checks.py  ★ new
│   ├── qa_bank.py  ★ new
│   ├── rows.py  ★ new
│   ├── run_baseline.py  ★ new
│   └── runmeta.py  ★ new
├── infra/  (Terraform: modules/environment, shared, dev, test, prod)
├── scripts/
│   ├── experiments/
│   │   └── integrated_vectorization.py
│   ├── build_corpus_map.py
│   ├── compare_filters.py
│   └── smoke_test.py
├── src/
│   └── dti_rag/
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── __main__.py
│       │   ├── chunk.py
│       │   └── parse.py
│       ├── retrieval/
│       │   ├── __init__.py  ★ new
│       │   ├── baseline.py  ★ new
│       │   └── results.py  ★ new
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
│       ├── models.py  ✎ changed
│       └── runinfo.py
├── tests/
│   └── unit/
│       ├── test_checks.py  ★ new
│       ├── test_chunking.py
│       ├── test_config.py
│       └── test_search_schema.py
├── .gitignore
├── Makefile  ✎ changed
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
| Improving the baseline "just a bit" | Every later comparison lies |
| Deliberately hobbling the prompt | Rigged the other way; also meaningless |
| Recording pass/fail only | Can't tell retrieval failures from generation failures |
| No fixed temperature | Non-reproducible baseline |
| Running only the five trap questions | No per-category baseline for Lesson 10 |
| Markdown only, no JSON | Nothing machine-readable to compare against |
| No model-version or manifest metadata | Can't tell a regression from an environment difference |

## Done when

You have documented, reproducible failures, not a vague sense that "it's not great", and for
every failure you can say whether the right chunk was retrieved.

## Check yourself

1. Why is returning £600 for DTI-008 a failure when £600 is a real 2023 value?
2. Which baseline failures are retrieval problems and which are generation problems? How
   does that change what you build next?
3. Why keep the baseline rather than deleting it once Lesson 06 works?
4. What does DTI-024 teach about retrieval score vs answer confidence?
5. The baseline scores DTI-010 ("what is the standard excess?") correct with £350. Is that a
   pass? *(Careful: read its `expected_behaviour`.)*

---

**Next:** [Lesson 06 — Hybrid search, semantic ranking and metadata filters](../lesson06/README.md)
