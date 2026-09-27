# Lesson 00 — Orientation: why a claims assistant isn't a chatbot

**Objective:** understand what you're building, why it's shaped the way it is, and how these
lessons deliver it, before writing any code.

**Time:** an hour of reading.

**Deliverables:** `README.md` and `.gitignore` at the project root.

---

## What you'll have at the end of Lesson 13

A **production-grade RAG application for the insurance domain**: an assistant a DavidsTown
Insurance (DTI) claims handler can use, deployed to prod on Azure. It:

- answers questions about the HomeShield home-insurance policy wording;
- picks the **edition that governs the claim** from the loss date, and says why;
- cites the clause, with quoted text, for every figure;
- asks when the question is genuinely ambiguous, and declines when the wording can't answer;
- refuses to show a figure it can't trace to the wording;
- is scored against a 25-question ground-truth bank on every pull request and before every
  promotion to prod;
- runs in three environments (dev, test, prod), promoted by a pipeline that stops when
  an environment has drifted from its recorded configuration.

Every lesson adds one layer and ships the files for it. By Lesson 13 the project is complete.

---

## Why a claims assistant is not a chatbot

**Being confidently wrong is worse than being unhelpful.** If a handler asks what excess
applies and the assistant says £350 when the governing edition says £300, a customer has been
given the wrong number by their insurer. In a regulated firm that's a complaint, possibly a
Consumer Duty issue, and at scale a remediation exercise.

That one constraint drives every design decision:

| Because… | …the system must | Built in |
|---|---|---|
| A wrong figure is real harm | Prove every figure against retrieved text; abstain rather than guess | 08, 11 |
| Five editions say nearly the same thing | Select by **metadata**, not by similarity | 02–07 |
| The business changes the wording every year | Make edition selection a pure, tested function | 07 |
| Someone will ask "why did it say that?" | Return the governing edition **and the reason it was chosen** | 07, 12 |
| An answer may be challenged months later | Keep an audit record of the context, edition and prompt for every answer | 13 |
| A bad change can reach handlers unnoticed | Promote one artefact dev → test → prod, gated by the eval harness | 10, 13 |

Notice what's missing: answer fluency, tone, model choice. They matter, but they aren't what
makes this hard.

---

## The pipeline you'll build

```
 question
    │
    ▼
 clean()        Lesson 11   control characters, length cap, delimiter can't be closed
    │
    ▼
 route()        Lesson 07   LLM extracts facts (loss date, editions named, scope);
    │                       CODE decides the edition(s) and the mode: answer | ask | abstain
    ▼
 retrieve()     Lesson 06   hybrid BM25 + vector → RRF → semantic rerank,
    │                       pre-filtered to one edition at a time; signposts followed (08)
    ▼
 generate()     Lesson 08   one pass per edition, structured citations, arithmetic checked
    │
    ▼
 guardrails()   Lesson 11   every £ figure and § number must be in the retrieved wording
    │
    ▼
 answer + citations + governing edition + why  ──►  API + UI (12) ──► audit log + traces (13)
```

Three things about this diagram are worth internalising now.

**Routing happens before retrieval.** Deciding *what to filter on* is the highest-leverage
step. A perfect retriever pointed at the wrong edition returns perfectly wrong answers.

**The filter is applied before ranking, not after.** Post-filtering searches all five
editions, takes the top k, then discards the wrong ones. If the right clause wasn't in that
top k (likely, with four near-duplicates competing), you get nothing. Lesson 06.

**Guardrails are a separate, deterministic layer.** A prompt is persuasion; a post-check that
looks for every figure of the answer in the retrieved context is enforcement. You want both,
and you need to know which is which.

---

## How the lessons are organised

| Phase | Lessons | You end with |
|---|---|---|
| 0 Foundations | 00, 01 | all three environments in Terraform, dev applied, a passing smoke test |
| 1 Data | 02, 03, 04 | the schema and policies; deterministic section-aware chunks; a versioned index loaded in dev |
| 2 Retrieval | 05, 06, 07 | a measured naive baseline; edition-correct retrieval; the router |
| 3 Generation | 08, 09 | cited, honest answers; a framework comparison; cross-edition diffs |
| 4 Evaluation | 10, 11 | the scorecard harness; guardrails; a green scorecard |
| 5 Production | 12, 13 | the app in dev; test and prod applied from the same code; the gated pipeline; the demo against prod |

**If you're time-boxed**, the irreducible core is **02 → 03 → 04 → 06 → 07 → 08 → 10**:
metadata-driven retrieval plus honest evaluation. The rest is what makes it a system you
could put in front of a regulated business.

### Each lesson folder

```
lessonNN/
├── README.md     the lesson: why, what, how, pitfalls, "done when", check yourself
└── files/        ONLY the files new or changed in this lesson, in full, laid out like the
                  project root. Copy it over your project to reach this lesson's state.
```

Apply a lesson with:

```bash
documentation/lessons/apply_lesson.sh 01      # add --dry-run to preview
```

The script never overwrites files you fill in by hand (`deploy/environments.yaml`,
`documentation/design/*.md`) if they already exist. It prints a `diff` command instead.
`deploy/<env>.env` isn't in any lesson: `terraform apply` writes it.

**Read the lesson before copying its files.** The files are the answer key; the README is
the lesson. Several lessons (02, 03, 07) are much more valuable if you attempt the core
function yourself first and compare afterwards.

---

## The repository

Why the project is laid out the way it is:

| Path | Rule |
|---|---|
| `src/dti_rag/` | One package. `pipeline.py` composes every stage, and **everything** that answers a question goes through it: the API, the eval harness, the scripts. The moment an evaluator calls a different code path from the one you ship, you're evaluating something you don't ship. |
| `src/dti_rag/<subpackage>/` | One per lesson layer: `ingestion/` (03), `search/` (04), `retrieval/` (05, 06), `query/` (07), `generation/` (08), `orchestration/` (09), `guardrails/` (11), `api/` (12), `observability/` (13). |
| `evaluation/` | **Outside** the package. It depends on ground truth that has no place in production, and it never ships in the container. |
| `data/policy_documents/` | **Authoritative.** If these say it, it's true. |
| `data/fact_matrix/` | **Convenience** data. Where it disagrees with the PDFs, it's wrong (Lesson 02 shows it does). |
| `data/question_answers/` | **Ground truth for scoring**, never for answering. |
| `artifacts/` | Git-ignored and regenerable: chunks, eval runs. Hand-editing anything here means the pipeline that produced it has a bug. |
| `tests/unit/` | Must run with no network. If unit tests need Azure, you'll stop running them. |
| `tests/integration/` | Run against a live environment named by `APP_ENV` (`make test-integration ENV=dev`). |
| `deploy/environments.yaml` | What every environment must be. Terraform builds from it; Lesson 13's drift check compares live Azure with it. |
| `deploy/<env>.env` | Each environment's configuration: endpoints, deployment names, API versions. Written by `terraform apply`, and committed, because there are no keys in it. |
| `infra/` | The Terraform. One folder per environment, plus `shared`. |
| `documentation/design/` | Your design records. Most lessons add one. |

---

## Conventions fixed now

**Deployment name ≠ model name.** You deploy `text-embedding-3-large` under a name you choose.
The SDKs (LlamaIndex and LangChain especially) want the *deployment* name. This course names
deployments by role (`chat`, `embed`, `judge`), so the difference can't be missed and the
names are identical in every environment.

**Pin API versions, identically everywhere.** `AZURE_SEARCH_API_VERSION` and
`AZURE_OPENAI_API_VERSION` live in `deploy/<env>.env`. A different API version in test and
prod means the eval gate tested something prod doesn't run.

**No API keys, anywhere, ever.** `DefaultAzureCredential` on your laptop (via `az login`), in
GitHub Actions (via OIDC) and in Azure (via managed identity). Key access is switched off on
every resource, dev included.

**Behaviour never branches on the environment.** `APP_ENV` labels telemetry, scorecards and
logs, and guards destructive scripts. If pipeline code ever says `if env == "prod":`, test
is no longer a rehearsal for prod.

**`doc_id` is the join key.** `DTI-HOME-PW-2024-v1.0` appears in the PDFs, the fact matrix,
the QA bank, the chunk metadata, the citations and the evaluators. Don't normalise it,
lowercase it, or strip its version.

**Nothing defaults to an environment.** Every command that touches Azure takes `ENV=dev|test|prod`
explicitly. A command that defaults to an environment will one day default to the wrong one.

---

## Keep this table open while you work

Every question in the QA bank probes one failure mode. "Which case am I trying to make pass
right now?" is the question that keeps the build honest.

| Category (as named in the QA bank) | IDs | Fixed in |
|---|---|---|
| `single_fact_lookup` | 001–003 | 04, 06 |
| `temporal_disambiguation` | 004–007 | 06, 07 |
| `version_ambiguity` | 008, 009 | 07, 09 |
| `freshness_default` | 010, 011 | 07 |
| `clause_existence` | 012–014 | 03, 07, 08 |
| `multi_hop_numeric` | 015–017 | 08 |
| `cross_section` | 018, 019 | 08 |
| `paraphrase_robustness` | 020, 021 | 06 |
| `cross_edition_comparison` | 022, 023 | 09 |
| `abstention_out_of_corpus`, `abstention_out_of_scope` | 024, 025 | 07, 08 |

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `README.md` | new | What the project is and where things live |
| `.gitignore` | new | Keeps `.venv`, `artifacts/` and personal `.env` files out of git |

## Project structure at the end of this lesson

```text
DTI-Policy-Helper/
├── data/
│   ├── fact_matrix/  (editions_fact_matrix.csv, fact_lookup_long.csv: convenience data)
│   ├── policy_documents/  (the 5 policy wording PDFs: authoritative)
│   └── question_answers/  (dti_rag_qa_bank.jsonl and .csv, README.md: ground truth for scoring)
├── documentation/
│   └── lessons/  (this course)
├── .gitignore  ★ new
└── README.md  ★ new
```

`★ new` in this lesson · `✎ changed` in this lesson · `◇ generated` by running the code (git-ignored or produced by you) · unmarked: unchanged from earlier lessons

## Check yourself

1. Why does `evaluation/` sit outside `src/dti_rag/`?
2. What breaks if the eval harness calls `retrieve()` directly instead of `pipeline.answer()`?
3. A colleague suggests skipping metadata and using a better embedding model to tell the
   five editions apart. What's wrong with that plan?
4. What's the difference between a guardrail in the prompt and a guardrail in code, and why
   do you want both?
5. Where does the code that maps a loss date to an edition belong, and why not in the LLM?
6. Which settings may differ between test and prod, and which must not? Why does the eval
   gate's value depend on the answer?

---

**Next:** [Lesson 01 — Build dev with Terraform, design for test and prod](../lesson01/README.md)
