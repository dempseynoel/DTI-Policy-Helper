# Lesson 09 — Orchestration with LlamaIndex and LangGraph, and cross-edition comparison

**Objective:** rebuild the retrieval and orchestration layers in framework abstractions,
learn what they hide, and solve the comparison questions that need multi-step retrieval.

**Deliverables:**

- `src/dti_rag/generation/compare.py`: clause-by-clause diffing and the post-retrieval
  ambiguity check (framework-free)
- `src/dti_rag/orchestration/llamaindex_retriever.py`: retrieval in LlamaIndex, with probes
- `src/dti_rag/orchestration/graph.py`: the pipeline as a LangGraph graph
- `pipeline.py` gains the comparison branch and the agreement check
- `documentation/design/FRAMEWORKS.md`: a decision record, with evidence

---

## Why rebuild something that works

**Honest reason 1: you'll inherit codebases that use them.** Knowing what LlamaIndex and
LangGraph do, and what they hide, is table stakes.

**Honest reason 2: DTI-022 and DTI-023 need multi-step retrieval** you haven't built. "What
changed between 2024 and 2025?" means retrieving two editions, diffing them, then
generating. That's a graph, and building it teaches you why graph frameworks exist.

**The dishonest reason to avoid: "frameworks are best practice."** If the framework version
isn't clearly better for a layer, say so. **"We evaluated it and stayed with the SDK" is a
legitimate and often correct outcome**, especially in a regulated firm, where an abstraction
you can't fully inspect is a liability.

What makes this cheap: **every stack sits on the same index.** You're swapping the
orchestration layer, not rebuilding the system.

---

## Cross-edition comparison (`compare.py`)

### DTI-022: "What changed between the 2024 and 2025 editions?"

The 2025 change summary lists eight changes and **omits four**. That summary chunk ranks
first and looks authoritative. Full credit needs a **diff**, and there's a real design choice:

| Strategy | How | Trade-off |
|---|---|---|
| **Clause-by-clause wording diff** (used) | Every chunk of both editions, matched by clause, compared | Most faithful; most tokens; works on any corpus |
| Fact-matrix diff | Compare two CSV rows | Cheap and complete, but it's the artefact carrying the DTI-014 lie |
| Summary + verification | Quote the summary, verify each item, sweep for more | Pragmatic middle |

`diff_editions()` matches clauses by key (section ID, or the defined term for Section 1
definitions), strips the edition header, and reports added, removed and changed clauses. The
change summary is passed separately, **labelled "may be incomplete"**. `SYSTEM_COMPARE`
reports every substantive change with before and after values, and says where the summary
omits one. `test_the_diff_finds_the_four_changes_the_2025_summary_omits` runs this against
the real PDFs, offline.

The pipeline routes here when the route is `comparison` with two or more editions, and it
retrieves **every** chunk of each edition (`retrieve.all_chunks()`): a diff needs every
clause, not the top k most similar ones.

> You *could* use the fact matrix as a diff **index** (where to look) as long as each change
> is confirmed in the wording: "the cheap source is untrustworthy in a known way, so it
> navigates but doesn't testify." Worth writing down; a reviewer will ask.

### DTI-023: "Has the storm wind-speed threshold ever changed, and when?"

A change-history question: `existence_or_history`, so every edition, answered per edition
and combined (Lesson 08): 48 knots in 2022, 47 from 2023 v1.0. The 2023 v1.0 change summary
gives the *reason* (aligned to Beaufort force 9), and citing it makes a better answer.
Summaries are incomplete, but what they do say is useful.

### The post-retrieval ambiguity check (`resolve_after_retrieval`)

The Lesson 07 decision, completed. If a route is `ask`, and each edition's top-ranked clause
is **the same clause with identical wording**, the editions agree: switch to `answer` and say
both editions agree. DTI-008's 6.3 differs (£500 vs £600), so it stays `ask`; a 2023 police
notification question (6.7 is identical) doesn't need to ask.

---

## The LlamaIndex pass (`llamaindex_retriever.py`)

`AzureAISearchVectorStore` over the **existing** index, with
`IndexManagement.NO_VALIDATION` so it never creates or alters one. `AzureOpenAIEmbedding`
is configured through the modern global `Settings` (not the deprecated `ServiceContext`),
with **every value passed explicitly**, including the deployment name.

Run `APP_ENV=dev python -m dti_rag.orchestration.llamaindex_retriever`. Its three probes
answer the `FRAMEWORKS.md` questions with evidence:

1. **Does `MetadataFilters` keep pre-filtering?** The store **never sets
   `vector_filter_mode`**, so it inherits the service default (pre-filter in current API
   versions). Correct today by accident of a default, not by design. Probe 1 checks every
   DTI-004 chunk is 2024.
2. **Can it express a date range?** **No.** It quotes string values, so
   `effective_from le '2024-03-15T00:00:00Z'` is a type error against `DateTimeOffset`.
   Edition selection has to go through `doc_id`, which the router already does.
3. **Does semantic ranking survive?** Yes, in `semantic_hybrid` mode, where scores are
   reranker scores (0–4). In `hybrid` mode they're RRF scores. Know which one a threshold
   compares against.

Also recorded: it **requires a JSON metadata field**. That's why Lesson 04's schema carries
`metadata_json`: a framework dictating a schema field is a lock-in cost, so write it down.

---

## The LangGraph pass (`graph.py`)

The router as a graph:

```
START → route ─┬─ comparison ──► compare ─────────────────────────► END
               └─ otherwise ───► retrieve ─► check_agreement ─► generate ─► END
```

The nodes call **the same framework-free functions** as `pipeline.py`. The graph adds explicit
state and conditional edges; it adds no behaviour, so both stacks score identically on the
Lesson 10 harness, and any difference is a bug.

Where the graph earned its place: the `compare` branch as a node rather than an `if` buried
in a function; the post-retrieval check as an explicit edge; state (question, route,
retrievals, answer) as one object, which makes tracing easy. Where it cost: another fast-
moving dependency, and deeper stack traces. Nothing here needs its runtime (no loops, no
persistence, no human-in-the-loop).

**Decision recorded in `FRAMEWORKS.md`:** production stays on the SDK pipeline; the graph was
the design tool, and the design was ported to about 40 lines of plain code.

> **Using LangChain models?** `graph.py` doesn't need them: LangGraph runs plain functions.
> If you use `AzureChatOpenAI`, build it with `azure_endpoint`, `api_version`,
> `azure_deployment` and `azure_ad_token_provider` passed explicitly from `config.py`.
> Otherwise it silently falls back to `AZURE_OPENAI_ENDPOINT` / `OPENAI_API_VERSION` from
> your shell.

---

## Build vs buy: the managed options

Run both against the same questions **in dev only**, record the scores in `FRAMEWORKS.md`,
then **delete what they created**:

- **Azure AI Search agentic retrieval** decomposes "compare 2024 and 2025" into sub-queries.
  Try DTI-022. Check whether it's GA or preview in the API version you pin, and whether its
  billing needs separate consent on the service's Premium features.
- **Foundry Agent Service File Search**: fully managed retrieval. Expect it to do well on
  simple lookups and poorly on edition selection, because it doesn't know your metadata
  schema. That gap *is* the value of Lessons 02–07. Quantify it.

"We built it by hand because the managed option scored X and ours scored Y on temporal
questions" is a defensible decision. "We built it by hand" alone isn't.

---

## Environments

- **Frameworks read your settings, never the process environment.** Pass every value
  explicitly.
- **Managed-option experiments run in dev only, and you clean up.** Agents, knowledge sources
  and vector stores that Terraform doesn't know about become drift the moment one leaks into test.
- **If a managed option earns a place in production**, whatever it needs is created by code
  (Terraform or the loader), identically in every environment. Preview features need an explicit
  written decision before prod.

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `src/dti_rag/generation/compare.py` | new | `diff_editions`, `compare()`, `resolve_after_retrieval()` |
| `src/dti_rag/generation/prompts.py` | changed | `SYSTEM_COMPARE`; `PROMPT_VERSION` → `gen-v2` |
| `src/dti_rag/retrieval/retrieve.py` | changed | `all_chunks(doc_id)` for diffs |
| `src/dti_rag/pipeline.py` | changed | Comparison branch; post-retrieval agreement check |
| `src/dti_rag/orchestration/__init__.py` | new | The package |
| `src/dti_rag/orchestration/llamaindex_retriever.py` | new | LlamaIndex over the existing index; three probes |
| `src/dti_rag/orchestration/graph.py` | new | The LangGraph version |
| `tests/unit/test_compare.py` | new | The real 2024 → 2025 diff; agreement check |
| `tests/unit/test_graph.py` | new | The graph's nodes and edges |
| `documentation/design/FRAMEWORKS.md` | new | Decision record: evidence filled, scores to measure |
| `pyproject.toml` | changed | `orchestration` extra |

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
│   │   ├── baseline_failures.md
│   │   ├── corpus_map.md
│   │   ├── FRAMEWORKS.md  ★ new
│   │   └── SCHEMA.md
│   └── lessons/  (this course)
├── evaluation/
│   ├── baselines/
│   │   └── naive-baseline-dev.json  ◇ generated
│   ├── __init__.py
│   ├── checks.py
│   ├── qa_bank.py
│   ├── rows.py
│   ├── run_baseline.py
│   └── runmeta.py
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
│       │   ├── compare.py  ★ new
│       │   ├── crossref.py
│       │   ├── generate.py
│       │   └── prompts.py  ✎ changed
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── __main__.py
│       │   ├── chunk.py
│       │   └── parse.py
│       ├── orchestration/
│       │   ├── __init__.py  ★ new
│       │   ├── graph.py  ★ new
│       │   └── llamaindex_retriever.py  ★ new
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
│       │   └── retrieve.py  ✎ changed
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
│       ├── pipeline.py  ✎ changed
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
│       ├── test_compare.py  ★ new
│       ├── test_config.py
│       ├── test_editions.py
│       ├── test_filters.py
│       ├── test_generation.py
│       ├── test_graph.py  ★ new
│       ├── test_router.py
│       └── test_search_schema.py
├── .gitignore
├── Makefile
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
| Letting LlamaIndex create its own index | Two indexes, divergent schemas |
| `ServiceContext` from an old tutorial | Deprecated; obscure errors |
| Model name instead of deployment name | `DeploymentNotFound` |
| Not verifying the framework's filter mode | Lesson 06's central fix silently undone |
| Quoting the 2025 change summary | Four changes missing |
| Diffing the fact matrix alone | Violates source of truth; inherits the DTI-014 lie |
| Diffing top-k retrievals instead of every clause | Changes that didn't rank are missed |
| Framework clients reading shell variables | Silently talking to another environment |
| Leaving agents or knowledge sources behind | Drift nobody recorded |

## Done when

DTI-022 and DTI-023 pass **including the "summary is incomplete" nuance**, both stacks give
the same answers, and `FRAMEWORKS.md` records a decision you could defend in a design review.

## Check yourself

1. Why does `compare` want to be a graph node rather than an `if` branch?
2. How do you check whether LlamaIndex pre-filters, and what's the symptom if it doesn't?
3. Why can the fact matrix navigate the DTI-022 diff but not testify to it?
4. Where does agentic retrieval beat your pipeline, and where does it lose?
5. Which Lesson 07 design question does the agreement check resolve?
6. What would make you keep the raw SDK for a layer even though a framework works?

---

**Next:** [Lesson 10 — Turn the QA bank into an automated eval harness](../lesson10/README.md)
