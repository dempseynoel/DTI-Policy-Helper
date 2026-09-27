# Lesson 10 — Turn the QA bank into an automated eval harness

**Objective:** stop eyeballing. Score the pipeline on all 25 questions, by category, with
retrieval, generation and behaviour reported separately, in one command, with a gate that
can fail a build.

**Deliverables:**

- `evaluation/evaluators.py`, `judge.py`, `targets.py`, `scorecard.py`, `compare.py`,
  `run_eval.py`
- `make eval ENV=dev`: a scorecard, a baseline-vs-current comparison, and a reference
  scorecard (`evaluation/baselines/reference-dev.json`)
- the `judge` deployment in dev (`deploy/environments.yaml`, applied with Terraform)

---

## Why this is the other half of the project

Lessons 02 and 10 are where RAG systems are won or lost: data engineering decides what's
*possible*; evaluation decides whether you *know* it's happening.

Without a harness you have vibes. You'll fix DTI-018, feel good, and not notice you broke
DTI-004, because you stopped checking it three lessons ago. The other thing a harness buys
is **permission to make risky changes**: a chunking change you can score in a few minutes is
a change you can try.

---

## Score retrieval, generation and behaviour separately

> A correct answer from the wrong chunk looks like a pass.

| Group | Metric | Evaluator |
|---|---|---|
| Retrieval | Gold doc retrieved; gold (doc, section) retrieved; **only** gold docs retrieved | `retrieval_recall`, `retrieval_section_hit`, `retrieval_purity` |
| Retrieval | **Dated questions, with vs without the loss-date pre-filter** | `probe_filtered_hit` / `probe_unfiltered_hit` |
| Generation | `must_include`; `must_not_include`; **edition correct** | `must_include`, `must_not_include`, `edition_correct` |
| Generation | Groundedness, relevance (LLM judge, 1–5) | `judge.py` |
| Behaviour | Abstained when unanswerable (and gave no figure) | `abstention_correct` |
| Behaviour | Asked, or gave both editions, when ambiguous | `ambiguity_handled` |
| Behaviour | Abstained on an answerable question (bad) | `over_abstained` |

> **The headline number:** the dated-question probe runs the same question with and without
> the date filter. The gap between the two is, precisely, the value of Lessons 02–07. It's
> the metric for your capstone slide.

### `edition_correct`: the domain metric

Passes when every gold edition was in scope, a gold edition is cited, and **nothing is cited
from outside the editions in scope**. No off-the-shelf evaluator gives you this. It's the
equivalent of the "did it invent an FCA reference number?" evaluators that real
financial-services teams write.

**Groundedness won't catch a wrong-edition answer.** "£350, per Section 3.4" is perfectly
grounded, in the 2025 chunk. For a 2024 loss it's wrong, and only `edition_correct` sees it.

### Normalisation decides pass/fail

Decided once, in `checks.py`: case-insensitive, whitespace-collapsed, figures exact, short
words matched whole. And **some `must_include` entries are weak tests**: DTI-007's `"not"`
passes on an answer that says the opposite of what's required, and DTI-015's `"two"` /
`"one"` are barely better. The scorecard lists them under "weak checks" so you pair them with
the judge rather than trusting them. Noticing that the eval set itself has weaknesses is a
real skill.

### The judge

`judge.py` uses azure-ai-evaluation's `GroundednessEvaluator` and `RelevanceEvaluator`, with
the **`judge` deployment**: a different, stronger model than `chat`, because a model grading
its own output is generous. Its model and version are recorded in the run metadata, because
judge drift otherwise looks like a pipeline regression.

**Add `judge` in dev now.** In `deploy/environments.yaml`, choose its model and version in
`shared.deployments.judge`, add `judge: 20` to `environments.dev.capacity`, and apply
`infra/dev`. The apply writes `AZURE_OPENAI_JUDGE_DEPLOYMENT=judge` into `deploy/dev.env`;
commit both. test gets one in Lesson 13. **Prod never gets one**: nothing in prod judges its
own answers, the Terraform module refuses to create one, and `check_env` treats one as drift.

If the judge is a reasoning model, check that the evaluators accept it before you commit to
it: some reject `temperature` and `max_tokens`, as Lesson 01 warned for `chat`.

---

## Harness design

**Running and scoring are separate.** `run_eval.py` saves the run as `run.json` (generation
is the slow, expensive part), then scores it. `--rescore path/to/run.json` re-scores without
generating anything: you'll iterate on evaluators far more than you expect.

**Every row records what the pipeline decided**: mode, governing editions, route reason,
citations, retrieved (doc, section, score), guardrail status. When DTI-008 fails you know
immediately whether the router chose the wrong mode or the generator ignored it.

**Two targets, one row shape** (`targets.py`):

- `--target local` calls `pipeline.answer()` in-process. Fast; used now, and by Lesson 13's
  **PR gate**.
- `--target api --base-url …` calls a deployed `/chat`. It proves the *deployed* system
  (container, identity, config, index), which is Lesson 13's **promotion gate**. The API
  doesn't return retrieved context, so Lesson 13 reads it back from the audit log by
  `trace_id`: every promotion then also proves the audit trail is complete.
- `--pipeline baseline` runs the naive Lesson 05 pipeline through the same harness.

**Every scorecard records where it came from**: environment, target, prompt version, git SHA,
**the model versions actually serving** (read from Foundry at run time), the index manifest
and **the number of throttled responses**. Throttling is a result, not noise: a run that
quietly dropped throttled questions would score 22/22 instead of 22/25. Here a failed row is
recorded as an error and fails the gate.

### The gate (`compare.py`)

`run_eval --compare reference.json` renders both side by side and exits non-zero on
regression. It gates **per metric, never on an aggregate**, because a big win in one
category can hide a regression in another:

| Metric | Tolerance | Why |
|---|---|---|
| `edition_correct`, `abstention_correct`, `ambiguity_handled` | **Zero**, per question | Deterministic at temperature 0; any drop is real |
| New abstentions on answerable questions | Zero | Over-abstention is a regression too |
| `must_include` | One newly failing question | Exact-match on 25 items is noisy |
| Groundedness (mean) | −0.25 | LLM-judged; genuinely varies |

And it **refuses to compare scorecards from different sources** (different serving model
versions or index manifest), saying why, instead of reporting a "regression" that is really
a model upgrade. Without that check the gate eventually blocks a good change for the wrong
reason, and people stop trusting it.

> **Two different baselines, not one.** The **naive baseline** (Lesson 05) is the control
> group for the improvement story: scorecards compared against it show how far you've come.
> The **reference scorecard** is what the gate compares against: the last accepted scorecard
> of *your* pipeline, committed as `evaluation/baselines/reference-<env>.json` and updated
> deliberately, by pull request, when you accept a new level. Gating against the naive
> baseline would pass almost anything.

---

## Run it

```bash
documentation/lessons/apply_lesson.sh 10
pip install -e ".[dev]"                                 # adds azure-ai-evaluation

# 1. Re-score the Lesson 05 baseline with the full evaluator set (no generation)
APP_ENV=dev python -m evaluation.run_eval --rescore evaluation/baselines/naive-baseline-dev.json --no-judge

# 2. Score the current pipeline, side by side with the baseline's scorecard
make eval ENV=dev REF=artifacts/eval/<baseline-run>/scorecard.json

# 3. Accept the current level as dev's reference
APP_ENV=dev python -m evaluation.run_eval --rescore artifacts/eval/<current-run>/run.json --save-reference
```

The comparison in step 2 will say **not comparable** if the baseline was run against
different `chat` or `embed` versions: re-run the baseline rather than overriding the check.
(A baseline recorded before `judge` existed is still comparable; it just has no groundedness
to compare.) Against the naive baseline the gate's verdict is informative, not a blocker:
any question the naive pipeline got right and yours gets wrong is worth reading.

---

## A warning about overfitting

You have 25 questions and you're about to optimise against them. You *will* overfit.

- **Prefer general fixes.** "Follow signposts" generalises; "if the question mentions
  ceilings, also retrieve Section 3" doesn't. When you catch yourself naming a specific
  question in a rule, stop.
- **Write five held-out questions** from the corpus map, and never tune against them
  (`error_analysis_log.md`, Lesson 11).
- **Watch the category, not the question.** Fixing DTI-018 should move `cross_section`.
- **Be suspicious of 25/25.**

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `evaluation/evaluators.py` | new | One function per metric; weak-check flagging |
| `evaluation/judge.py` | new | Groundedness and relevance via the `judge` deployment |
| `evaluation/targets.py` | new | `local`, `api` and `baseline` targets, one row shape; dated-query probe |
| `evaluation/scorecard.py` | new | Per-metric, per-category, per-question; markdown render |
| `evaluation/compare.py` | new | Comparability check and per-metric gate; exits non-zero |
| `evaluation/run_eval.py` | new | One command; `--rescore`, `--compare`, `--save-reference` |
| `evaluation/rows.py` | changed | Probe and judge fields |
| `tests/unit/test_evaluators.py` | new | edition_correct catches grounded wrong-edition answers; gate behaviour |
| `pyproject.toml` | changed | `evaluation` extra |
| `Makefile` | changed | `make eval ENV=… [REF=…]` |

## Project structure at the end of this lesson

```text
DTI-Policy-Helper/
├── artifacts/
│   ├── eval/
│   │   └── <run>/
│   │       ├── run.json  ◇ generated
│   │       ├── scorecard.json  ◇ generated
│   │       └── scorecard.md  ◇ generated
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
│   │   ├── FRAMEWORKS.md
│   │   └── SCHEMA.md
│   └── lessons/  (this course)
├── evaluation/
│   ├── baselines/
│   │   ├── naive-baseline-dev.json  ◇ generated
│   │   └── reference-dev.json  ◇ generated
│   ├── __init__.py
│   ├── checks.py
│   ├── compare.py  ★ new
│   ├── evaluators.py  ★ new
│   ├── judge.py  ★ new
│   ├── qa_bank.py
│   ├── rows.py  ✎ changed
│   ├── run_baseline.py
│   ├── run_eval.py  ★ new
│   ├── runmeta.py
│   ├── scorecard.py  ★ new
│   └── targets.py  ★ new
├── infra/  (Terraform: modules/environment, shared, dev, test, prod)
├── scripts/
│   ├── experiments/
│   │   └── integrated_vectorization.py
│   ├── ask.py
│   ├── build_corpus_map.py
│   ├── compare_filters.py
│   ├── measure_retrieval.py
│   └── smoke_test.py
├── src/
│   └── dti_rag/
│       ├── generation/
│       │   ├── __init__.py
│       │   ├── arithmetic.py
│       │   ├── compare.py
│       │   ├── crossref.py
│       │   ├── generate.py
│       │   └── prompts.py
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── __main__.py
│       │   ├── chunk.py
│       │   └── parse.py
│       ├── orchestration/
│       │   ├── __init__.py
│       │   ├── graph.py
│       │   └── llamaindex_retriever.py
│       ├── query/
│       │   ├── __init__.py
│       │   ├── editions.py
│       │   ├── extract.py
│       │   └── router.py
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
│       ├── pipeline.py
│       └── runinfo.py
├── tests/
│   ├── integration/
│   │   ├── conftest.py
│   │   ├── test_pipeline.py
│   │   ├── test_retrieve.py
│   │   └── test_router_llm.py
│   └── unit/
│       ├── test_checks.py
│       ├── test_chunking.py
│       ├── test_compare.py
│       ├── test_config.py
│       ├── test_editions.py
│       ├── test_evaluators.py  ★ new
│       ├── test_filters.py
│       ├── test_generation.py
│       ├── test_graph.py
│       ├── test_router.py
│       └── test_search_schema.py
├── .gitignore
├── Makefile  ✎ changed
├── .pre-commit-config.yaml
├── pyproject.toml  ✎ changed
├── .python-version
└── README.md
```

`★ new` in this lesson · `✎ changed` in this lesson · `◇ generated` by running the code (git-ignored or produced by you) · unmarked: unchanged from earlier lessons

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Blending retrieval and generation into one score | Can't tell what to fix |
| Not running dated questions both ways | You lose the headline metric |
| The same model generating and judging | Systematically generous scores |
| Gating against the naive baseline | A gate that passes almost anything |
| Inconsistent normalisation | Correct answers fail; wrong ones pass |
| Trusting weak `must_include` entries | DTI-007 passes on a wrong answer |
| Re-generating to iterate on evaluators | Slow and expensive, so you stop |
| No mode / edition / citations per row | Every failure needs a manual re-run |
| A harness that only runs in-process | Lesson 13 can't test the deployed system |
| No provenance on the scorecard | Environment differences reported as regressions |
| Different judge versions in dev and test | Scores not comparable |
| Dropping failed or throttled rows | Inflated scores |

## Done when

One command scores the whole bank; the scorecard separates retrieval, generation and
behaviour; it shows measurable improvement over the naive baseline, including the
filtered-vs-unfiltered gap; and `reference-dev.json` is committed.

## Check yourself

1. What does a correct answer from the wrong chunk look like, and which metric catches it?
2. Why won't groundedness catch a wrong-edition answer?
3. Which single number best expresses the value of Lessons 02–07, and why?
4. DTI-007's `must_include` contains `"not"`. What's wrong, and what do you do?
5. Give two reasons to be suspicious of 25/25.
6. Why gate against a reference scorecard rather than the naive baseline?
7. Why read model versions from Foundry at run time rather than from config?
8. What does `--target api` catch that `--target local` can't?

---

**Next:** [Lesson 11 — Close the gaps; add guardrails](../lesson11/README.md)
