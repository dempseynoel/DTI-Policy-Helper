# Lesson 00 — Orientation and repo shape

**Objective:** understand the skeleton before you fill it, and understand why a RAG system
for insurance is shaped differently from a RAG demo.

**Time:** an hour of reading. No code.

---

## Why a claims assistant is not a chatbot

The thing that makes this project worth doing is that **being confidently wrong is worse
than being unhelpful.** If a claims handler asks what excess applies and the assistant says
£350 when the governing edition says £300, that is a customer who was told the wrong number
by their insurer. In a regulated environment that is a complaint, potentially a Consumer
Duty issue, and — if it happened at scale — a remediation exercise.

That single constraint drives every design decision in this repo:

| Because… | …the system must |
|---|---|
| A wrong figure is a real harm | Abstain rather than guess, and prove every figure against retrieved text |
| An answer may be challenged months later | Log the retrieved context and the selected edition for every response |
| Five editions say nearly the same thing | Select by **metadata**, not by similarity |
| The business changes the wording annually | Make edition selection a first-class, testable, pure function |
| Someone will ask "why did it say that?" | Return the governing edition **and the reason it was chosen** |
| A bad change reaches handlers before anyone notices | Promote one artefact through **dev → test → prod**, with the eval gate between test and prod |

Notice what's *not* on that list: answer quality, tone, model choice. Those matter, but they
aren't what makes this hard.

---

## The shape of the pipeline

```
                       ┌──────────────────────────────────────────┐
  user question ─────► │ route()      Lesson 7                    │
                       │ What edition? What mode?                 │
                       │ → {filter, mode: answer|ask|abstain}     │
                       └──────────────┬───────────────────────────┘
                                      │
                       ┌──────────────▼───────────────────────────┐
                       │ retrieve()   Lesson 6                    │
                       │ hybrid BM25+vector → RRF → semantic      │
                       │ rerank, with the filter applied *before* │
                       │ ranking (preFilter)                      │
                       └──────────────┬───────────────────────────┘
                                      │
                       ┌──────────────▼───────────────────────────┐
                       │ generate()   Lesson 8                    │
                       │ cited answer, or an honest refusal       │
                       └──────────────┬───────────────────────────┘
                                      │
                       ┌──────────────▼───────────────────────────┐
                       │ guardrails() Lesson 11                   │
                       │ every £ figure and § number must appear  │
                       │ in the retrieved context                 │
                       └──────────────┬───────────────────────────┘
                                      ▼
                        answer + citations + governing edition + why
```

Three things about this diagram are worth internalising now.

**Routing happens *before* retrieval.** Most RAG tutorials go straight to the vector store.
Here, deciding *what to filter on* is the highest-leverage step in the whole system — a
perfect retriever pointed at the wrong edition returns perfectly wrong answers. Get used to
thinking of retrieval as a two-step act: decide the scope, then search within it.

**The filter is applied before ranking, not after.** This is `vectorFilterMode=preFilter`
and it's covered properly in Lesson 6. Post-filtering searches all five editions, takes the
top 50, *then* discards the four wrong editions — and if the right edition's clause wasn't
in that top 50 (likely, when four near-duplicates outrank it), you get nothing.

**Guardrails are a separate, deterministic layer.** Not a prompt instruction. Prompts are
persuasion; a post-check that greps the retrieved context for every figure in the answer is
enforcement. You want both, and you want to know which is which.

---

## Why the repo is laid out this way

### `src/dti_rag/` — one package, one pipeline

`pipeline.py` composes route → retrieve → generate → guardrails, and **everything** goes
through it: the API, the eval harness, the notebooks. The moment your eval harness calls a
different code path from your API, you are evaluating something you do not ship. This is
the single most common way RAG teams end up with a green scorecard and an unhappy user.

The subpackages map one-to-one onto lessons, so you always know where new code goes:

```
ingestion/   Lesson 3   PDFs → chunks
search/      Lesson 4   chunks → index
retrieval/   Lessons 5,6  index → ranked chunks
query/       Lesson 7   question → filter + mode
generation/  Lesson 8   chunks → cited answer
orchestration/ Lesson 9 the same thing in LlamaIndex / LangGraph
guardrails/  Lesson 11
observability/ Lesson 13
api/         Lesson 12
```

### `evaluation/` is outside the package, deliberately

It doesn't ship in the container, it depends on ground-truth data that has no place in
production, and keeping it separate stops eval-only helpers leaking into app code. When you
containerise in Lesson 12, `.dockerignore` excludes it — check that it still builds.

### `Data/` splits into authoritative and convenience

- `PolicyDocuments/` — **authoritative**. Five PDFs. If these say a thing, it is true.
- `FactMatrix/` — **convenience**. Derived tables, useful for eval and for deriving the
  corpus map. Where these disagree with the PDFs, the PDFs win and the CSV is wrong.
  (This isn't hypothetical: see the DTI-014 trap in Lesson 2.)
- `QuestionAnswers/` — **ground truth for scoring**, not for answering.

Keeping that distinction crisp in your head from day one is most of what Lesson 2 teaches.

### `artifacts/` is git-ignored and regenerable

`chunks.jsonl`, embeddings, eval scorecards. If you ever find yourself hand-editing
something in here, that's a signal the pipeline that generates it has a bug.

One exception you'll add in Lesson 10: the **baseline scorecard** gets committed, because
CI needs something to compare against.

In CI, `chunks.jsonl` is built **once per commit** and the same file is loaded into every
environment. That only means something if chunking is deterministic, which Lesson 3 makes
you prove.

### `tests/unit` must run without Azure

Filter construction, date→edition resolution, section detection — all pure logic, all
testable offline, all things that silently produce wrong answers when they break. If your
unit tests need a network, you'll stop running them.

### `deploy/` — one config file per environment

The system runs in three environments, and the difference between them is **data, not
code**:

```
  your laptop ──► dev ──(merge to main)──► test ──(eval gate + your approval)──► prod
                  you + pipeline           pipeline only                         pipeline only
```

- `deploy/dev.env`, `deploy/test.env`, `deploy/prod.env` — endpoints, deployment names, API
  versions and `APP_ENV` for each environment. Committed, because they hold nothing secret:
  there are no keys.
- `deploy/environments.yaml` (Lesson 13) — what each environment's Azure configuration is
  *supposed* to be, which the pipeline checks before it deploys.

The infrastructure itself is built by hand in the Azure portal, following the runbook in
`Documentation/design/ENVIRONMENTS.md` (Lesson 1). **Infrastructure is clicked,
configuration is committed, code is promoted** — and the pipeline refuses to deploy to an
environment whose live configuration doesn't match what's committed.

---

## Conventions worth fixing now

**Deployment name ≠ model name.** In Azure OpenAI you deploy `text-embedding-3-large` under
a name you choose. The SDKs — and LlamaIndex and LangChain especially — want the
*deployment* name. Every config variable in `.env.example` that ends `_DEPLOYMENT` is a name
you picked, not a name Azure picked. Expect to lose twenty minutes to this once; expect to
lose an afternoon to it if you don't read this paragraph. Lesson 1 names deployments by
role — `chat`, `embed` — so the difference is impossible to miss, and so the names are
identical in every environment.

**Pin API versions explicitly — and identically in every environment.**
`AZURE_SEARCH_API_VERSION` and `AZURE_OPENAI_API_VERSION` are in `.env.example` for a
reason. Features here move fast — integrated vectorization went GA in `2024-07-01`, agentic
retrieval is newer — and taking the SDK default means your pipeline's behaviour can change
when you next `pip install`. A different API version in test and prod means the eval gate
tested something prod doesn't run.

**No API keys, anywhere, ever — and no environment where they're allowed.**
`DefaultAzureCredential` locally (via `az login`) and managed identity in Azure. Key access
is switched off on every resource, dev included. The RBAC roles you need are in Lesson 1.
This is not box-ticking: key-based auth is the thing that turns a leaked repo into an
incident, and "we'll fix auth later" never survives contact with a deadline.

**Behaviour never branches on the environment.** `APP_ENV` exists for labelling telemetry
and guarding destructive scripts. The moment pipeline code says `if env == "prod":`, test is
no longer a rehearsal for prod. Environments differ in capacity, access and protection —
never in what the system does.

**`doc_id` is the join key.** `DTI-HOME-PW-2024-v1.0` appears in the PDFs, the fact matrix,
the QA bank's `gold_doc_ids`, your chunk metadata, your citations and your
`edition_correct` evaluator. It is the one identifier that ties the whole system together.
Don't normalise it, don't lowercase it, don't strip the version suffix.

---

## Deliverables

None — this is a reading lesson. But before moving on you should be able to answer:

## Check yourself

1. Why does `evaluation/` sit outside `src/dti_rag/`?
2. What breaks if the eval harness calls `retrieve()` directly instead of going through
   `pipeline.py`?
3. A colleague suggests skipping metadata and using a better embedding model to tell the
   five editions apart. What's wrong with that plan?
4. What's the difference between a guardrail in the prompt and a guardrail in code, and why
   do you want both?
5. Where would you add code that maps a loss date to a governing edition — and why does it
   belong there rather than in the router?
6. Which things may differ between test and prod, and which must not? Why does the eval
   gate's value depend on the answer?

---

**Next:** [Lesson 01 — Build dev in the Azure portal, design for test and prod](Lesson01.md)
