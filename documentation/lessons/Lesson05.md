# Lesson 05 — Baseline pipeline, and watch it fail on purpose

**Objective:** build the naive RAG pipeline everyone builds first, run it against the trap
questions, and document exactly how and why it fails.

**Deliverable:** `Documentation/design/baseline_failures.md` — each failing QA-bank ID mapped
to the mechanism that caused it.

---

## Why deliberately build something bad

Three reasons, and they're all about honesty.

**You need a control group.** In Lesson 10 you'll report that the system scores well. Well
*compared to what*? Without a measured baseline, "our RAG system gets 88%" is a number with
no meaning. With one, "naive RAG got 40%, edition-aware retrieval got 88%, and here is the
per-category breakdown of where the 48 points came from" is an engineering result.

**You need to feel the failure.** Reading "vector search can't distinguish near-identical
editions" is abstract. Watching your pipeline confidently answer £350 to a question whose
answer is £300 — with a fluent, plausible, well-cited-looking explanation — is not. That
experience is what stops you from trusting a demo that looks fine.

**It's the strongest thing you can show a stakeholder.** Same question, same corpus, same
model; one pipeline says £350 and the other says £300. No diagram explains the value of
metadata filtering faster.

---

## Build it thin, and keep it thin

`src/dti_rag/retrieval/baseline.py`:

1. Embed the query.
2. Vector search, top-k, **no filters**.
3. Concatenate the chunks into a grounding prompt.
4. Chat completion with "answer only from the context provided."

That's it. Resist every instinct to improve it.

> **This file must never be improved.** Its job is to stay bad so Lesson 10 has something
> honest to compare against. Put a comment at the top saying so — including to your future
> self, who will find it and "fix" it.

Use a *reasonable* naive prompt, though. If you deliberately hobble the prompt, the
comparison is rigged and you've learned nothing. "Answer only from the context" is what a
competent engineer writes on day one; that's the right bar.

---

## The trap questions to run first

Run all 25, but these five show the distinct failure *mechanisms*:

### DTI-004 — recency bias (expect £350, answer is £300)

> "A customer's kitchen flooded on 15 March 2024 when a dishwasher supply hose burst. What
> excess applies?"

Five near-identical 3.4 clauses come back in noise order. The model picks one. It will tend
to prefer the 2025 figure — partly ordering luck, partly because "current"-flavoured
language and the highest number read as most authoritative.

**Watch for the dangerous version of this failure:** the answer that says "£350" *and*
explains it confidently. There's no uncertainty signal. This is the single most important
thing to see with your own eyes.

### DTI-003 — minority value (expect 47 knots, answer is 48)

> "In the 2022 wording, what wind speed is needed before weather counts as a storm?"

Four editions say 47, one says 48. Even though the query names 2022, the four distractors
dominate the candidate set and the model reads consensus as correctness.

This is the cleanest demonstration that **RAG has no notion of authority** — it has
similarity, and five similar chunks vote.

### DTI-008 — false confidence on an ambiguous question (expect one figure, answer is "it depends")

> "What was the pedal cycle theft limit in 2023?"

£500 until 30 June, £600 from 1 July. The correct response asks for the loss date or returns
both. The baseline will return one number with no hedge.

Note carefully: **returning £600 is a failure even though £600 is a real value from a real
2023 edition.** The failure is collapsing genuine ambiguity, not picking wrong. This is the
category most teams don't even measure.

### DTI-014 — wrong on cover existence (expect a limit, answer is "not offered")

> "Is home emergency cover available, and what does it pay out?"

Without edition scoping the model sees the 2024/2025 home emergency sections and describes
the cover. If you also fed it the fact matrix, it'll confirm £1,000 for 2022.

This is the one with real-world teeth: a customer told they have cover they never bought.

### DTI-024 — answering when it should abstain (expect £250, answer is a refusal)

> "What was the standard excess under the 2021 edition, DTI-HOME-PW-2021-v1.0?"

The 2022 control page contains that exact document reference, so retrieval returns a
high-scoring chunk. The model sees the ID it was asked about, finds £250 nearby, and
answers.

**Retrieval confidence became answer confidence.** That's the mechanism, and it's the one
that generalises furthest beyond this corpus.

---

## What to log

Don't just record pass/fail. For each question capture:

- The question and the generated answer
- **The top-k retrieved chunks with their `doc_id`, `section_id` and score**
- Whether `gold_doc_ids` appeared in the retrieved set **at all**
- `must_include` / `must_not_include` results

That third one is the diagnostic that matters, because it splits failures into two kinds:

| Gold doc in retrieved set? | Diagnosis | Fixed in |
|---|---|---|
| **No** | Retrieval failure — the right text never arrived | Lessons 6–7 |
| **Yes**, but answer wrong | Generation failure — right text, wrong reasoning | Lesson 8 |

Most baseline failures here are the first kind, and knowing that is what tells you to spend
your effort on retrieval rather than prompt engineering. Teams that skip this step spend
weeks tuning prompts against a retrieval problem.

Write the scaffolding so Lesson 10 can reuse it. You're building the first version of the
eval harness without calling it that.

---

## The deliverable

`Documentation/design/baseline_failures.md`:

| QA ID | Category | Expected | Baseline gave | Gold retrieved? | Mechanism |
|---|---|---|---|---|---|
| DTI-004 | temporal_disambiguation | £300 | £350 | Yes | Recency bias across near-identical chunks |
| DTI-003 | single_fact_lookup | 48 knots | 47 knots | Yes | Minority value outvoted by 4 distractors |
| … | | | | | |

Plus a short summary: score by category, and the retrieval-failure vs generation-failure
split.

**Commit the raw JSON output too**, not just the markdown. Lesson 10 compares against it,
and CI in Lesson 13 needs a machine-readable baseline.

---

## Environments

**Run the baseline in dev.** This lesson is the one most likely to produce a runaway loop,
and dev's TPM cap and budget alert (Lesson 1) are there to catch it.

**Record where the numbers came from.** The raw JSON carries, alongside the date and
temperature:

- `app_env`
- the deployment names **and the model versions actually serving them**, read from the
  Foundry resource at run time rather than copied from your notes
- the index manifest from Lesson 4: schema version, `chunks.jsonl` hash, embedding model
  version

This matters because the baseline will be compared across environments. Lesson 13's eval
gate runs in **test** and regenerates its baseline there. That comparison is only honest if
dev and test served the same model versions from the same chunks. Lesson 1's "must match"
table is supposed to guarantee that, and the recorded metadata lets you *prove* it rather
than assume it.

**`baseline.py` reads config like everything else.** No endpoint or deployment name in the
file. It must run unchanged against test, because in Lesson 13 it will.

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Improving the baseline "just a bit" | Your comparison is meaningless |
| Deliberately hobbling the prompt | Rigged the other way; also meaningless |
| Recording pass/fail only | Can't tell retrieval failures from generation failures |
| Not fixing a seed / temperature | Non-reproducible baseline |
| Only running the five trap questions | No per-category baseline for Lesson 10 |
| Markdown only, no JSON | Lesson 13's CI gate has nothing to diff |
| Baseline without environment and model-version metadata | Can't tell a regression from an environment difference |

**On reproducibility:** set temperature to 0 and record the environment, the model
deployment and version, and the date. You'll re-run this in Lesson 10, and in test in
Lesson 13, and you need the difference to be your pipeline, not sampling noise, a model
update or a different environment.

---

## Done when

You have documented, reproducible failures — not a vague sense that "it's not great" — and
for every failure you can say whether the right chunk was retrieved.

## Check yourself

1. Why is returning £600 for DTI-008 a failure when £600 is a real 2023 value?
2. Which baseline failures are retrieval problems and which are generation problems? How
   does that change what you build next?
3. Why keep the baseline unimproved rather than deleting it once Lesson 6 works?
4. What does DTI-024 teach about the relationship between retrieval score and answer
   confidence?
5. Your baseline scores 100% on DTI-010 ("what is the standard excess?" → £350). Is that a
   pass? *(Careful.)*

---

**Next:** [Lesson 06 — Hybrid search, semantic ranking, and metadata filters](Lesson06.md)
