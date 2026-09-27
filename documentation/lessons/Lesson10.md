# Lesson 10 — Turn the QA bank into an automated eval harness

**Objective:** stop eyeballing. Score the pipeline across all 25 questions, by category,
automatically.

**Deliverable:** `evaluation/run_eval.py` producing a per-question and per-category
scorecard, plus a baseline-vs-current comparison against Lesson 5.

---

## Why this is the other half of the project

Lessons 2 and 10 are where RAG systems are won or lost. Data engineering decides what's
*possible*; evaluation decides whether you *know* whether it's happening.

Without a harness you have vibes. You'll fix DTI-018, feel good, and not notice you broke
DTI-004 — because you stopped checking it three lessons ago. Regression is the normal state
of a system being actively improved, and the only defence is scoring everything, every time.

The other thing a harness buys you: **permission to make risky changes.** A chunking
strategy you can evaluate in four minutes is a change you can try. Without that, every
change is a gamble and you stop improving the system.

---

## Score retrieval and generation separately

The most important structural decision in this lesson.

> A correct answer from the wrong chunk looks like a pass.

That happens more than you'd think — the model knows insurance, the retrieved context is
irrelevant, and the answer is plausibly right. It'll pass `must_include` and fail the moment
a figure changes.

So:

**Retrieval metrics** — did the right chunks arrive?
- `recall@k` against `gold_doc_ids`
- A stricter section-level hit against `gold_sections`
- For items with a `query_date`: **run twice, with and without the pre-filter.**

> That last one produces **the single most informative number this bank generates.** The gap
> between filtered and unfiltered retrieval on dated questions is, precisely, the value of
> everything Lessons 2–7 built. It's your headline metric and your capstone slide.

**Generation metrics** — given the right chunks, was the answer right?
- `must_include` as a cheap exact gate
- `must_not_include` as a contamination check
- LLM judge against the reference `answer` for reasoning-heavy items (014, 015, 017, 018, 022)

**Behavioural metrics** — did it do the right *kind* of thing?
- `ambiguous == true` (008, 009) **fails if a single value is returned, even the right one**
- `answerable == false` (024, 025) fails on any confident figure

Report all three separately. A single blended score hides exactly the information you need.

---

## What the QA bank already gives you

Everything. This is unusually well-specified ground truth — real projects rarely start here,
and building the bank is usually *your* first job.

| Field | Becomes |
|---|---|
| `gold_doc_ids` | qrels for retrieval scoring; input to `edition_correct` |
| `gold_sections` | Stricter section-level retrieval hit |
| `must_include` | Custom code evaluator (exact substring) |
| `must_not_include` | Contamination check |
| `answerable: false` | Custom abstention evaluator |
| `ambiguous: true` | Custom ambiguity evaluator |
| `answer` | Reference for Response Completeness / Similarity / LLM judge |
| `category` | The per-category breakdown that drives Lesson 11 |
| `query_date` | Filtered vs unfiltered retrieval comparison |

---

## Built-in evaluators (`azure-ai-evaluation`)

LLM-judge evaluators configured with `AzureOpenAIModelConfiguration`:

- **Retrieval** — are the retrieved chunks relevant to the query?
- **Groundedness** (1–5) and/or **Groundedness Pro** (Content Safety, pass/fail) — is the
  answer grounded, or is it inventing figures and section numbers?
- **Relevance** — does the answer address the question?
- **Document Retrieval** — Fidelity, NDCG and friends, using `gold_doc_ids` as qrels.
- **Response Completeness / Similarity** — against the reference `answer`.

**Use a different, stronger model as judge than the one generating.** A model judging its own
output is systematically generous. Record which judge model and version produced a score —
judge drift across model updates will otherwise look like pipeline regression.

And know the limits: **groundedness will not catch a wrong-edition answer.** "£350, per
Section 3.4" is perfectly grounded in the 2025 chunk. It's the wrong edition. Which is
exactly why you need:

---

## Custom evaluators — where the real value is

### `edition_correct` — the domain metric

Did the cited `doc_id` match `gold_doc_ids`?

This is the metric this whole project exists to move, and **no off-the-shelf evaluator gives
it to you.** It's directly analogous to the custom "did it invent an FCA reference number?"
evaluators that real financial-services teams write — the domain-specific correctness check
that generic metrics structurally cannot see.

If you build one custom evaluator, build this one.

### `must_include` / `must_not_include`

Exact substring. Simple — with one trap:

> **Normalisation decides pass/fail.** Is "£300" equal to "£300.00"? To "300 pounds"? Is
> "24 hours" equal to "24-hour"? Decide once, write it in the evaluator's docstring, and
> apply it consistently.

Lean strict. For insurance figures, exact-match is defensible: a system that says "roughly
£300" is worse than one that says "£300". But make it a deliberate decision, not an accident
of implementation.

Watch DTI-007, whose `must_include` is `["45", "not", "fire, lightning and explosion"]`.
`"not"` as a bare substring matches "note", "nothing", "cannot" — it'll pass on answers that
say the opposite of what's required. **Some `must_include` entries are weak tests.** Flag
them; consider a word-boundary match; consider pairing with the LLM judge for those items.
Noticing that the eval set itself has weaknesses is a genuine skill.

### `abstention_correct`

For `answerable == false`: did it decline? Check for the *absence* of a confident figure as
well as the presence of a refusal — "I can't confirm, but it was probably £250" is a
failure.

### `ambiguity_handled`

For `ambiguous == true`: did it return both values or ask for the date? A single value fails
even when correct.

---

## Harness design

**`evaluation/dataset.py`** runs the pipeline over all 25 questions and emits rows with:
`query`, `response`, `context` (the retrieved chunks), `ground_truth`, plus every QA-bank
field the evaluators need, plus what your pipeline *decided* — mode, filter, selected
edition, citations.

That last group matters: when DTI-008 fails you want to know immediately whether the router
chose the wrong mode or the generator ignored it. Without it you re-run by hand to find out.

**Cache pipeline runs.** Generation is the slow, expensive part; evaluator iteration is
fast. Separate "run the pipeline" from "score the outputs" so you can re-score without
re-generating. You'll iterate on evaluators far more than you expect.

**Run local first, then cloud.** Iterate locally for speed; submit batch runs to Foundry
when you want results logged to MLflow / App Insights and shareable. Cloud runs land in
*that environment's* Foundry project — dev's while you iterate, test's for gate runs —
which keeps the two histories apart by design.

### The scorecard

```
                        baseline   current   Δ
retrieval  recall@5        0.48      0.96   +0.48
           section hit     0.32      0.88   +0.56
           dated: filtered  —        1.00
           dated: unfiltered 0.25    0.25          ← the headline gap
generation must_include    0.40      0.92   +0.52
           groundedness    3.1       4.6    +1.5
           edition_correct 0.36      1.00   +0.64
behaviour  abstention      0/2       2/2
           ambiguity       0/2       2/2

by category:
  temporal_disambiguation  0.25 → 1.00
  clause_existence         0.33 → 0.67    ← worst; start here in Lesson 11
  ...
```

Per-category is what drives Lesson 11. An aggregate of 0.84 tells you nothing about what to
fix next.

**Make it one command** — `make eval`. A harness you have to remember how to invoke is a
harness you stop running.

**Exit non-zero on regression.** Lesson 13's CI gate needs that, and building it now means
the gate is a workflow file rather than a refactor.

---

## Environments

You'll run this harness in dev for the rest of the course. Lesson 13 runs the same harness
in test as the gate between test and prod. Build it for both now.

### Add the judge deployment in dev and test, not prod

**Foundry portal:** the environment's project → **Discover** → **Models** → your judge model
→ **Deploy** → **Custom settings**. Deployment name `judge`, the same deployment type as
`chat`, version pinned, no auto-upgrade. Do it in dev now, and add it to the test column of
`ENVIRONMENTS.md` so it's there when Lesson 13 builds test. **Prod doesn't get one.** Nothing
in prod judges its own answers. If you later add online evaluation in prod, that's a
deliberate, recorded change.

Use the same judge model **and version** in dev and test. A score from a different judge
isn't comparable, and "judge drift looks like pipeline regression" (below) then happens
between environments rather than across time.

### One harness, two targets

Build `run_eval.py` so that what gets evaluated is pluggable:

- `--target local` calls `pipeline.py` in-process. It's fast, it's what you use now, and
  it's what Lesson 13's **PR gate** uses.
- `--target api --base-url …` calls a deployed `/chat` endpoint. It's what Lesson 13's
  **promotion gate** uses in test: it proves the *deployed* system, including the container,
  identity, config and index, not just the code.

The scoring code must not know which target produced a row. Both emit the same row shape.
The one gap is the retrieved context that groundedness needs, which the API doesn't return
by default. **Recommended:** read it back from the audit log by `trace_id` (Lesson 13). It's
slower, but every promotion then also proves the audit trail is complete. The alternative is
an opt-in `include_context` flag that only the eval identity may use. It's simpler, but it's
a debug path in production code.

### Every scorecard records where it came from

- `app_env` and the target (`local` / `api`)
- deployment names and the **model versions actually serving them**, read from the Foundry
  resource at the start of the run, not copied from config. The point is to record what
  was true.
- the index manifest (schema version, `chunks.jsonl` hash, embedding model version)
- prompt version, judge model and version, git SHA

**The comparison script refuses to diff scorecards whose model versions or manifests
differ.** It says why instead of reporting a "regression" that is really a model upgrade or
an environment mismatch. Without that check, the gate eventually blocks a good change for
the wrong reason, and people stop trusting it.

### Throttling is a result, not noise

Dev's TPM cap will throttle a full run. Retry 429s with back-off and **count the retries in
the scorecard.** A run that quietly dropped throttled questions scores 22/22 instead of
22/25, which looks like progress. Size test's `chat` and `judge` capacity so a gate run
finishes in minutes.

---

## A warning about overfitting

You have 25 questions and you're about to optimise against them. That is a small eval set
and you *will* overfit.

Mitigations, in rough order of value:

- **Prefer general fixes to special cases.** "Detect signposts" generalises; "if the query
  mentions ceilings, also retrieve Section 3" does not. When you catch yourself adding a
  rule that names a specific question, stop.
- **Write a few held-out questions yourself** from the fact matrix, and don't tune against
  them. Even five is a meaningful check.
- **Watch the category, not the question.** Fixing DTI-018 should move `cross_section`, not
  just that one row.
- **Be suspicious of 25/25.** Perfect on a small set usually means you've fitted the set.

This applies with real force to the Lesson 8 prompt, which is where rules accumulate one per
failing question.

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Blending retrieval and generation into one score | Can't tell what to fix |
| Not running dated questions both ways | You lose your headline metric |
| Same model generating and judging | Systematically generous scores |
| Unrecorded judge model/version | Judge drift looks like regression |
| Inconsistent currency normalisation | Correct answers fail; wrong ones pass |
| Trusting weak `must_include` entries | DTI-007 passes on a wrong answer |
| Re-running generation to iterate on evaluators | Slow, expensive, so you stop |
| Not logging mode/filter/edition per row | Every failure needs a manual re-run |
| Optimising against 25 questions | Overfitting, dressed as progress |
| Aggregate score only | No idea what to fix next |
| Harness that can only call `pipeline.py` in-process | Lesson 13 can't test the deployed system |
| Scorecard without environment / model versions / manifest | Environment differences reported as regressions |
| Different judge model or version in dev and test | Scores not comparable across environments |
| Dropping throttled questions silently | Inflated scores at dev's TPM cap |

---

## Done when

One command scores the whole bank, breaks results down by category, separates retrieval
from generation from behaviour, and shows measurable improvement over the Lesson 5 baseline
— including the filtered-vs-unfiltered gap on dated questions.

## Check yourself

1. Why score retrieval separately, and what does a correct answer from the wrong chunk
   look like?
2. Why won't groundedness catch a wrong-edition answer?
3. Which single number best expresses the value of Lessons 2–7? Why that one?
4. DTI-007's `must_include` contains `"not"`. What's wrong, and what would you do?
5. You score 25/25. Give two reasons to be suspicious.
6. Why cache pipeline runs separately from scoring?
7. Why read model versions from the Foundry resource at run time rather than from config?
8. What does `--target api` catch that `--target local` can't?

---

**Next:** [Lesson 11 — Close the gaps; add guardrails](Lesson11.md)
