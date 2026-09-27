# Error-analysis log

One row per iteration. Worst category first; one change at a time; re-run the whole bank.
The wrong hypotheses are the most credible rows in a design review, so keep them.

Target bar: every answerable question passes `must_include` / `must_not_include`; every
abstention and ambiguity is handled; `no_unsupported_figures` = 1.00; held-out questions
not worse.

| # | Date | Worst category (score) | Failing IDs | Hypothesis (mechanism) | Change (one) | Layer | Before → after (category) | Anything regress? | Kept? |
|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | chunking / filters / reranking depth / prompt / routing | | | |

## Held-out questions

Written by me from the corpus map, never tuned against. Scored separately.

| ID | Question | Expected | Result |
|---|---|---|---|
| H-01 | | | |
| H-02 | | | |
| H-03 | | | |
| H-04 | | | |
| H-05 | | | |

## The model-swap experiment (run once)

| `chat` model | Score | Moved which categories? |
|---|---|---|
| Current | | |
| Larger | | |
