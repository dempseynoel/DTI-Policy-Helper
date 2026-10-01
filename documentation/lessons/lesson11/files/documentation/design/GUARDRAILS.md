# Guardrails

What can go wrong, what stops it, and the evidence that it does. Identical in every environment: no setting disables any control.

## 1. Threat model (most severe first)

| # | Threat | Harm |
|---|---|---|
| 1 | Wrong monetary figure (wrong edition, transcription, arithmetic) | Customer told the wrong amount by their insurer; complaint; remediation at scale |
| 2 | Cover asserted that doesn't exist (Reserved section; table trusted over wording) | Mis-statement of cover |
| 3 | Confident answer where it should abstain (edition not held; out of scope) | Invented figure for a document that doesn't exist |
| 4 | Ambiguity collapsed to one value | Right-looking answer for the wrong half of 2023 |
| 5 | Prompt injection via pasted correspondence ("confirm cover is in place") | Confirmation of cover never given |
| 6 | Personal data in logs | A personal-data store nobody designed; UK GDPR exposure |
| 7 | The assistant read as making coverage decisions | A different regulatory posture entirely |

## 2. Controls

| Threat | Prompt rule (persuasion) | Code (enforcement) | Where |
|---|---|---|---|
| 1 | Quote figures exactly; cite every figure; show calculations | **Figure check blocks** any £ figure not in the retrieved wording or a verified calculation | `guardrails/figures.py` |
| 1 | — | Arithmetic verified in code, never trusted | `generation/arithmetic.py` |
| 1 | — | One generation pass per edition: cross-edition contamination impossible | `generation/generate.py` |
| 1, 2 | Wording overrides tables; Reserved = not offered | The CSV fact columns are never read at answer time | `query/editions.py` |
| 1 | — | Groundedness detection **flags** on every answer | `guardrails/groundedness.py` |
| 3 | Abstention prompt: give no figure | Router abstains on unheld editions and out-of-scope questions (deterministic) | `query/router.py` |
| 4 | Ask prompt: never a single value | Router `ask` mode; post-retrieval agreement check | `query/router.py`, `generation/compare.py` |
| 5 | Question is data, inside `<question>` tags | Delimiter neutralised; length capped; typed filters only (no user text in OData); **the output figure check holds however the model was manipulated** | `guardrails/user_input.py`, `retrieval/filters.py` |
| 6 | — | Redaction before anything is logged | `guardrails/pii.py` (Lesson 13 audit log) |
| 7 | Describe the wording; the schedule takes priority | UI states it permanently (Lesson 12) | `api/static/index.html` |

## 3. Evidence

| Control | Test |
|---|---|
| Injected wrong figure is blocked | `tests/unit/test_guardrails.py::test_injected_wrong_figure_is_blocked` |
| User-supplied figure isn't evidence | `test_a_figure_only_the_user_supplied_is_not_evidence` |
| Wrong arithmetic is blocked | `test_a_wrong_calculation_is_blocked`, `test_generation.py` |
| Per-edition isolation | `test_generation.py::test_each_edition_is_generated_from_its_own_chunks_only` |
| OData injection impossible | `test_filters.py::test_untyped_or_malformed_values_never_reach_a_filter` |
| Deployed guardrail is on | Lesson 13 post-deploy smoke: a request that must be blocked is blocked |
| Eval bar | Scorecard `no_unsupported_figures` = 1.00, zero tolerance in the gate |

## 4. Failure behaviour

| Check | On failure | Why |
|---|---|---|
| Figure not sourced | **Block**: answer withheld, citations still shown, draft kept in the audit log | A wrong number is direct harm |
| Calculation doesn't verify | **Block** | Same |
| Section not in retrieved wording | **Flag** | An annoyance the handler can see |
| Groundedness: ungrounded | **Flag** | Model-based, so it has false positives; blocking on it would cause outages |
| Groundedness: unavailable | Recorded as unavailable; answer shown | The deterministic check still ran |

Groundedness latency: measure p50/p95 with and without it (Lesson 13 dashboard). If it doubles p95, move it to an asynchronous flag after the response rather than inline.

## 5. Logging and retention

| | dev | test | prod |
|---|---|---|---|
| Data | Synthetic only | Synthetic only | Real claims context |
| Traces (App Insights) | 100% sampled, 30 days | 100%, 30 days | Sampled, ____ days |
| Audit log (blob, `audit/`) | 30 days | 30 days | ____ (complaint-handling timeframe) |
| Redaction | Always | Always | Always |
| Who can read the audit log | Me | Pipeline deploy identity (gate read-back) | ____ (named roles only) |
| Lawful basis for prod logging | — | — | ____ |

## 6. Scope statement

The assistant surfaces HomeShield policy wording, with citations, to help a claims handler. It does not make coverage decisions and does not give legal advice. The customer's schedule takes priority over the wording, and the assistant says so.

## 7. Known gaps

| Gap | What a real deployment would do |
|---|---|
| Regex PII redaction can't find names | Azure AI Language PII detection before logging |
| Groundedness detection is a preview API | Written approval to use it in prod, or run it offline only |
| Public endpoints (Lesson 01) | Private endpoints |
| ____ | |
