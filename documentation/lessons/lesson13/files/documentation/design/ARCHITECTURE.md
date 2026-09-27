# Architecture and design

The capstone design document: what the system is, why it's built this way, how a change
reaches production, and what the system deliberately refuses to do.

## 1. The problem

Five editions of the HomeShield policy wording say nearly the same thing with different
numbers. A claims handler needs the figure from **the edition that governs the claim**,
with the clause it came from. Being confidently wrong is worse than being unhelpful: a
wrong excess is a customer misinformed by their insurer.

## 2. The system

```
                 ┌──────────── dti_rag.pipeline.answer() ─────────────┐
 question ─► clean ─► route ─► retrieve (per edition) ─► generate ─► guardrails ─► answer
              │        │              │                     │            │       + citations
              │   LLM extracts    hybrid BM25+vector     one pass     figure check  + governing edition
              │   facts; code     + semantic rerank,     per edition; (blocks)      + why
              │   picks edition   pre-filtered to one    arithmetic   groundedness
              │   (editions.py)   doc_id; signposts      checked      (flags)
              │                   followed in-edition
              ▼
        injection-safe:                                       ┌─► traces → App Insights (sampled)
        typed filters only                     FastAPI /chat ─┤
                                                              └─► audit/<trace_id>.json (complete, redacted)
```

Everything that answers a question goes through `pipeline.answer()`: the API, the eval
harness and the scripts. What is evaluated is what ships.

## 3. The three policies

| Policy | Rule | Enforced by |
|---|---|---|
| Source of truth | The wording PDF is authoritative; the CSVs are convenience data. Reserved = not offered. | Fact columns never read at answer time; prompt rule; figure guardrail |
| Edition selection | Loss date → the edition in force. No date → current + "earlier editions differ". Bare 2023 → ambiguous. Unheld edition → abstain. | `query/editions.py` + `query/router.py` (deterministic, unit-tested) |
| Abstention | Not in the wording → say so, cite the nearest clause, give no figure. | Router `abstain` mode; abstention prompt; `abstention_correct` evaluator |

## 4. Why it's built this way

| Question | Answer, with evidence |
|---|---|
| Why metadata filtering rather than better embeddings? | The five 3.4 clauses score within ____ of each other unfiltered (`scripts/compare_filters.py`). Dated questions: section hit ____ unfiltered vs ____ filtered (scorecard `probe_*`). |
| Why section-aware chunking? | Section IDs drive filters, citations, cross-references and the QA bank's `gold_sections`. Fixed-size chunks destroy them and drop Reserved sections. |
| Why is edition resolution code, not the LLM? | It has exactly one right answer. A model is usually right and occasionally, untestably, wrong. |
| Why does the wording beat the fact matrix? | The matrix lists £1,000 home-emergency cover for 2022–2023, and £2,000 escape-of-fuel cover for 2022. Neither cover existed. Trusting it reports cover that was never sold. |
| What does it refuse to do? | Answer from editions it doesn't hold; answer non-home questions; state a figure it can't source; make coverage decisions. |
| Framework choices | `FRAMEWORKS.md`: SDK in production; LangGraph used to design the compare branch, then ported to plain code. |

## 5. Environments and promotion

```
 laptop ──► dev ──(merge to main)──► test ──(gate + approval)──► prod
            you + pipeline           pipeline only               pipeline only

 PR       ci.yml (offline) + pr-eval.yml (in-process, throwaway index on test)   blocks merge
 main     deploy.yml: build image + chunks ONCE ─► dev ─► test ─► [approve] ─► prod
                      each: check_env · load index · deploy digest · smoke
                      test: + promotion gate (eval through the deployed API)
 nightly  drift.yml: check_env × 3 (read-only identity) + sweep PR indexes
```

**Infrastructure is code, configuration is generated, code is promoted.** Terraform
(`infra/`) builds every environment from `deploy/environments.yaml` and writes each one's
`deploy/<env>.env`. Isolation is enforced by identity: each environment's deploy identity has
roles only in its own environment, and GitHub hands it out only to jobs that declare that
environment.

**How do I know test is a faithful rehearsal of prod?** Everything that changes behaviour is
in the shared section of `deploy/environments.yaml`, so Terraform gives test and prod the same
values; only capacity, access and protection differ. `check_env` compares both with that file
before every deploy and nightly, so an environment that wasn't applied, or was changed by
hand, can't be deployed to.

## 6. Capstone demo runbook

Demo live, against **prod**. Lead with case 1 shown twice: the baseline (£350, wrong) then
the real pipeline (£300, cited).

| # | Case | Question | Expected |
|---|---|---|---|
| 1 | Temporal | A kitchen flooded on 15 March 2024. What excess applies? | **£300**, 2024 edition §3.4/§10, with the loss-date reason |
| 2 | Minor version | A cycle was stolen from a locked shed on 12 August 2023. Limit? | **£600**, 2023 v1.1 §6.3 |
| 3 | Freshness default | What's the standard excess? | **£350** + "earlier editions differ" |
| 4 | Clause existence | Is communicable disease excluded? | Not in 2022; §9.6 from 2023 |
| 5 | Table vs wording | Is home emergency cover available? | 2024 £1,000, 2025 £1,500, £75 call-out; **Reserved, not offered** before 2024 |
| 6 | Paraphrase | Tiles blew off and rain came in. Leak or storm? | **Storm**, §4.1 |
| 7 | Multi-hop numeric | Two items of storm damage 80 hours apart, 2024 vs 2025? | 2 × £300 (72-hour window) vs 1 × £350 (96-hour) |
| 8 | Cross-section | A burst loft pipe collapsed a ceiling. Which section? | **§3**, not §7.2; £350 |
| 9 | Abstention | 2021 edition excess? / Is my car covered? | **Decline**, with reasons and the nearest clause |

Case 5 is the one an insurance audience remembers: cover that was never sold. Case 9 reads
as a limitation until you explain that the alternative was inventing a figure.

## 7. The capstone package

1. The deployed app (repo + prod URL), deployed by the pipeline.
2. The eval harness and scorecard, wired in as both gates.
3. This document and the design records: `SCHEMA.md`, `FRAMEWORKS.md`, `GUARDRAILS.md`,
   `OBSERVABILITY.md`; and `deploy/environments.yaml` with `infra/`, which define every
   environment.
4. The baseline comparison (`baseline_failures.md` and the scorecards).
5. The error-analysis log, wrong hypotheses included.
