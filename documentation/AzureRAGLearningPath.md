# Building a Production RAG System on Azure — A Hands-On Learning Path

**Capstone goal:** an end-to-end retrieval-augmented assistant that a DavidsTown Insurance (DTI) claims handler could actually use — one that answers "what excess applies to this claim?" correctly, picks the *right edition of the policy wording* for the loss date, refuses to guess when it shouldn't, and is continuously evaluated against a ground-truth question bank.

**Who this is for:** you already understand RAG concepts (chunking, embeddings, vector search, reranking, grounding, evaluation) but haven't built and deployed one. So this path skips the theory and is organised entirely around *building*, using the DTI corpus as the thing under construction.

**Why this corpus is the right teacher.** The DTI corpus is deliberately adversarial. Five policy-wording editions (2022, 2023 v1.0, 2023 v1.1, 2024, 2025) share near-identical text with different numbers, there are two same-year minor versions, some clauses exist only in some editions, one section is "Reserved," and the supplied CSVs contain a *deliberate trap* (a home-emergency limit listed for years where the section didn't exist). Naive RAG fails on almost all of it. That failure is the point — each lesson makes a specific failure visible, then fixes it with a specific Azure capability.

---

## The stack you'll end up using

| Layer | Primary choice | Why |
|---|---|---|
| Cloud project / models | **Azure AI Foundry** (new "Foundry project", not hub-based) + Azure OpenAI deployments | Single project endpoint, model catalog, built-in evaluation & tracing |
| Chat + embeddings SDK | **OpenAI Python SDK, Azure-configured** (`openai` with `AzureOpenAI`) | Microsoft now recommends the stable OpenAI/v1 API over the older `azure-ai-inference` SDK |
| Retrieval engine | **Azure AI Search** (hybrid + semantic ranker + filters) | Most complete managed retrieval pipeline; metadata filtering is what makes this corpus solvable |
| Ingestion / retrieval abstractions | **LlamaIndex** (`llama-index-vector-stores-azureaisearch`) | Clean data/index/retriever abstractions and metadata filters |
| Orchestration / agents | **LangChain + LangGraph** (`langchain-openai`, Azure AI Search vector store) | Query routing and multi-hop/agentic flows as a graph |
| Evaluation | **`azure-ai-evaluation`** | Groundedness/Relevance/Retrieval + custom evaluators; your QA bank is the dataset |
| Serving | **FastAPI** + **Azure Container Apps** | Simple, containerised, managed-identity friendly |
| Ops | **App Insights / OpenTelemetry**, Key Vault, GitHub Actions | Tracing, secrets, eval-gated CI/CD |
| Environments | **dev / test / prod**, one resource group each, built in the Azure portal from a written runbook; GitHub Actions promotes the app between them | Real-world separation: test rehearses prod, the eval gate sits between them, identities are scoped per environment |

**Deliberate design choice:** you build the pipeline yourself rather than using a one-click managed RAG. Azure OpenAI "On Your Data" is being retired in favour of Foundry Agent Service / direct Search integration, and building it by hand is how you learn where the failure modes live. You'll *compare against* the managed options (agentic retrieval, Foundry Agent File Search) in Lesson 9 so you know when to reach for them.

### Current tooling notes (verify at build time — these move fast)
- Foundry now appears in docs as both "Azure AI Foundry" and "Microsoft Foundry." Create a **Foundry project**, not a hub-based one; the SDK code differs.
- Use the **OpenAI SDK with Azure config** for chat/embeddings; treat `azure-ai-inference` as legacy.
- For Azure AI Search, **integrated vectorization** (Text Split + AzureOpenAIEmbedding skills) went GA in API `2024-07-01`; **agentic retrieval** and scoring-profile-on-semantic are newer preview features. Pin an API version explicitly.
- Embedding model: **`text-embedding-3-large`** (3072 dims, supports Matryoshka variable dimensions) is the default recommendation; `text-embedding-3-small` (1536) if cost/latency matters.
- Prefer **`DefaultAzureCredential` / managed identity** over API keys everywhere.
- The Foundry RBAC roles were renamed: **Foundry User** (formerly Azure AI User) is the role for calling models and using projects. Microsoft's Foundry guidance says not to use the `Cognitive Services …` roles for Foundry work.
- Semantic ranker's **free plan now works on every Search tier**, including Free. Basic is still the right tier here: you only get one Free service per subscription, and Free can't use a managed identity for indexers.
- The Azure portal **can't disable key access on a Foundry resource**. Use Cloud Shell (`Set-AzCognitiveServicesAccount … -DisableLocalAuth $true`) and audit it with Azure Policy.

---

## How the lessons map to the corpus's hard cases

Every question in `dti_rag_qa_bank.jsonl` has a `category`. Here's where each is solved:

| QA-bank category | Example IDs | Solved mainly in |
|---|---|---|
| `single_fact_lookup` | 001, 002, 003 | Lessons 4–6 (index + hybrid + minority-value retrieval) |
| `temporal_disambiguation` | 004, 005, 006, 007 | Lessons 6–7 (date→edition filters) |
| `version_ambiguity` | 008, 009 | Lesson 7 (ambiguity detection, minor-version) |
| `freshness_default` | 010, 011 | Lesson 7 (status=Current default + caveat) |
| `clause_existence` | 012, 013, 014 | Lessons 3, 8 (Reserved handling, table-vs-wording trap) |
| `multi_hop_numeric` | 015, 016, 017 | Lesson 8 (single-edition arithmetic, no contamination) |
| `cross_section` | 018, 019 | Lessons 8–9 (cross-reference following / agentic) |
| `paraphrase_robustness` | 020, 021 | Lessons 6, 9 (hybrid + semantic ranker) |
| `cross_edition_comparison` | 022, 023 | Lesson 9 (multi-hop / agentic retrieval) |
| `abstention_out_of_corpus` / `out_of_scope` | 024, 025 | Lessons 7, 11 (abstention gating + guardrails) |

Keep this table open while you work — "which case am I trying to make pass right now?" is the question that keeps the build honest.

---

# Phase 0 — Foundations

## Lesson 1 — Provision Azure and prove your dev loop works

**Objective:** build the **dev** environment in the Azure portal, following a design that test and prod will copy exactly, and confirm you can call a chat model and an embedding model from Python.

**Design the three environments first:** one resource group each for dev, test and prod (plus a shared one). Write down which settings may differ (capacity, access, protection) and which must match (region, model versions, deployment names, auth mode, semantic plan, index schema). Test and prod are built in Lesson 13, from this written runbook.

**Build dev in the portal:**
- A **Foundry resource** (created in the Azure portal, so you control names), a project, and two deployments named by role: `chat` (a GPT-4-class model) and `embed` (**`text-embedding-3-large`**). Pin the versions and turn off auto-upgrade. Azure wants the *deployment* name, not the model name.
- An **Azure AI Search** service on **Basic**, with API access control set to **RBAC** (the default is keys only) and semantic ranker on the **Standard** plan.
- A **Key Vault** (RBAC permission model), a **Storage account** (key access off), and **Log Analytics + Application Insights**.
- Key access disabled on the Foundry resource. The portal can't do this, so use Cloud Shell.

**Set up the dev loop:**
- Python 3.11+ repo, virtual env, pre-commit, and a `Makefile`/task runner. Non-secret per-environment config in `deploy/<env>.env`, committed.
- `pip install azure-ai-projects azure-identity openai azure-search-documents python-dotenv`
- Authenticate with `az login` and use `DefaultAzureCredential`. Assign yourself, in **dev only**: Foundry User, Search Service Contributor, Search Index Data Contributor, Storage Blob Data Contributor.
- Put a **budget alert** on every resource group and per-deployment **TPM (tokens-per-minute) limits** in place now: cheap insurance against a runaway loop.

**Deliverable:** dev built and recorded in `ENVIRONMENTS.md`, plus a `smoke_test.py` that prints which environment it's talking to, (a) embeds a sentence with the `embed` deployment and asserts the vector length, and (b) gets a one-line chat completion. Both via the Azure-configured OpenAI SDK.

**Done when:** both calls succeed using `DefaultAzureCredential`, with no keys anywhere.

---

# Phase 1 — Data engineering (the part that decides everything)

## Lesson 2 — Read the corpus like an adversary; design the metadata schema

This is the most important lesson in the path. On this corpus, **the metadata schema *is* the product.** Vector similarity alone cannot tell 2023 v1.0 from v1.1, or "current" from "the one in force on 15 March 2024." Metadata can.

**Study, don't skim:**
- `DTI-HOME-INSTRUCTOR-GUIDE.pdf` — the fact matrix and the "suggested exercises" section literally enumerate the failure modes you must beat.
- `editions_fact_matrix.csv` — this is your metadata dictionary and part of your answer key.
- `fact_lookup_long.csv` — the same facts in long form (one row per fact per edition), handy for eval.
- `dti_rag_qa_bank.jsonl` — 25 questions with `gold_doc_ids`, `gold_sections`, `must_include`, `must_not_include`, `ambiguous`, `answerable`, `expected_behaviour`.

**Design the chunk metadata schema** (every chunk carries all of this):
`doc_id`, `edition_year`, `version`, `status` (Archived/Superseded/Current), `effective_from`, `effective_to`, `supersedes`, `superseded_by`, `section_id` (e.g. "3.4"), `section_title`, `page`.

**Write down three policies** now, before any code — they become prompt rules and router logic later:
1. **Source-of-truth policy.** The **policy wording PDF is authoritative.** The CSVs are convenience/eval data only. DTI-014 is the reason: the fact matrix lists a home-emergency limit for 2022/2023, but Section 8 is "Reserved" in those PDFs. A system that trusts the table reports cover that was never sold.
2. **Edition-selection policy.** Given a loss date, pick the edition where `effective_from ≤ date ≤ effective_to`. Given no date, default to `status = Current` and note that earlier editions differ. Given a bare year with two editions (2023), it's ambiguous — ask or return both.
3. **Abstention policy.** If the answer isn't in the retrieved wording (2021 edition doesn't exist here; motor cover is out of scope), say so rather than extrapolate.

**Deliverable:** a `SCHEMA.md` documenting the metadata fields and the three policies, plus a one-page "corpus map" (which facts change in which edition — you can derive it straight from the fact matrix).

**Done when:** you can state, from memory, why naive top-k vector search returns the *wrong* excess for a dated 2024 claim.

---

## Lesson 3 — Parse and chunk the PDFs (section-aware)

**Objective:** turn five PDFs into clean, section-scoped chunks that each carry the full metadata from Lesson 2.

**Parsing:**
- Start with **PyMuPDF / pdfplumber** — the DTI PDFs are born-digital and clean, so heavy tooling is overkill.
- Then do the same extraction with **Azure Document Intelligence** (Layout model) on at least one PDF, so you've used the tool you'd need for scanned/messy real-world claims documents. Note the difference in effort and output structure.

**Chunk on section boundaries, not blindly by token count.** A chunk should be a clause (e.g. all of 3.4, "Excess") so that:
- `section_id` is meaningful and retrievable (cross-references like 7.2 → 3 depend on it — Lesson 8).
- Near-identical clauses across editions stay distinguishable by their metadata, not their text.
- The reworded-but-equivalent storm clause (2022 vs later) survives paraphrase (Lesson 6).
- "Reserved" Section 8 is captured *as* "Reserved" for 2022/2023, so the model can say "not offered" rather than hallucinate.

Use a small overlap only within long sections. Attach the Lesson-2 metadata to *every* chunk at creation time.

**Deliverable:** a chunking pipeline emitting `chunks.jsonl` — one record per chunk as `{ "id", "content", "metadata": {...} }` — for all five editions. Sanity-check counts per edition and spot-check that `section_id` values are correct.

**Done when:** you can filter `chunks.jsonl` to `edition_year == 2024 AND section_id == "3.4"` and get exactly the 2024 escape-of-water excess clause.

---

## Lesson 4 — Build and load the Azure AI Search index

**Objective:** a searchable index with a vector field *and* filterable metadata.

**Index schema essentials:**
- `content` — searchable text (BM25).
- `contentVector` — vector field (HNSW; dimension matches your embedding model, e.g. 3072 for `text-embedding-3-large`).
- Metadata fields **filterable/facetable**: `edition_year` (Int, filterable), `status` (String, filterable), `section_id` (String, filterable), and crucially `effective_from` / `effective_to` as **`Edm.DateTimeOffset`, filterable** so you can do range filters by loss date.
- A **semantic configuration** (title/content fields) to enable the semantic ranker.

**Two loading paths — do both, in order:**
1. **Push model first.** Embed each chunk in code with `text-embedding-3-large`, then upload documents with `azure-search-documents`. Doing it by hand teaches you exactly what's in the index.
2. **Integrated vectorization second.** Build an indexer + skillset (**Text Split** skill for chunking, **AzureOpenAIEmbedding** skill for vectors) so Search chunks and embeds for you, and attach a **query vectorizer** so you can send raw text at query time. This is the managed path you'd likely use in production.

**Deliverable:** a populated index and a notebook that runs (a) a pure vector query, (b) the same query with an OData filter `edition_year eq 2024`, and shows the results differ.

**Done when:** Search Explorer returns the correct single-edition clause when you add a metadata filter, and returns cross-edition noise when you don't.

---

# Phase 2 — Retrieval

## Lesson 5 — Baseline pipeline, and watch it fail on purpose

**Objective:** a minimal embed → search → stuff → generate loop using only the OpenAI SDK + Search, with **no metadata filtering**, so you can measure how bad naive RAG is here.

**Build it thin:** embed the query, vector-search top-k, concatenate the chunks into a grounding prompt, call the chat model with "answer only from the context."

**Run the trap questions and log what happens:**
- DTI-001 / DTI-004 (dated 2024 excess) → expect it to return £350 (recency bias to the current edition) instead of £300.
- DTI-003 (48 knots, 2022) → expect 47 knots (the minority value loses to four near-identical distractors).
- DTI-008 (2023 cycle limit) → expect a single confident number instead of "it's ambiguous."

**Deliverable:** the baseline pipeline plus a `baseline_failures.md` mapping each failing QA-bank ID to *why* it failed. This is your control group; Lesson 10 will quantify it.

**Done when:** you have documented, reproducible failures — not a vague sense that "it's not great."

---

## Lesson 6 — Hybrid search, semantic ranking, and metadata filters

**Objective:** fix retrieval so the *right chunks* come back for temporal, minority-value, and paraphrase cases.

**Upgrade the retriever:**
- **Hybrid query:** run BM25 keyword + vector in parallel; Search merges them with **Reciprocal Rank Fusion**. This alone rescues paraphrase cases (DTI-020/021) and keyword-heavy ones.
- **Semantic ranker (L2):** rerank the fused top results with the transformer cross-encoder. This pushes the genuinely-relevant clause to position 1 instead of 7.
- **Metadata filters (the key move):** for a dated query, apply `effective_from le <date> and effective_to ge <date>`; for "current," apply `status eq 'Current'`. Use **preFilter** (`vectorFilterMode`) so the filter constrains the candidate set *before* ranking — essential for temporal correctness.

**This is where the corpus starts behaving:** DTI-004 → £300, DTI-005/006 → correct 2023 minor version, DTI-002/010/011 → current-edition values. Minority-value cases (DTI-003) now work because the filter removes the four distractor editions entirely.

**Deliverable:** a `retrieve(query, filters)` function returning ranked, edition-correct chunks, with a test that the dated-2024 query returns *only* 2024 chunks.

**Done when:** every `single_fact_lookup` and `temporal_disambiguation` question retrieves its `gold_doc_ids` / `gold_sections`.

---

## Lesson 7 — The query-understanding layer (dates, freshness, ambiguity, abstention)

**Objective:** decide *what filter to apply and what mode to answer in* before retrieving. Filters only help if you set them correctly.

**Build a pre-retrieval router** (LLM function-calling is the pragmatic choice) that extracts:
- a **loss date** if present ("flooded on 15 March 2024") → set date-range filter.
- whether the query **names an edition/year** → set that filter; if a bare year maps to two editions (2023), flag **ambiguous**.
- whether the query is plausibly **out of corpus** (2021 edition) or **out of scope** (motor cover) → set **abstain** mode.
- otherwise → **freshness default**: `status = Current`, and instruct generation to add "earlier editions differ."

**Route to one of three modes:** `answer` (with the right filter), `ask` (ambiguous — request the date, or return both with effective ranges, DTI-008), `abstain` (DTI-024/025).

**Deliverable:** a `route(query)` returning `{filter, mode, notes}`, unit-tested against the ambiguity, freshness, and abstention questions.

**Done when:** DTI-008 returns "ambiguous — need the date" (or both values), DTI-010 defaults to £350 *and* notes others differ, and DTI-024/025 route to `abstain`.

---

# Phase 3 — Generation & orchestration

## Lesson 8 — Grounded generation: citations, conflicts, multi-hop, cross-references

**Objective:** turn correct retrieval into correct, cited, honest answers — including the cases where naive generation still goes wrong even with good retrieval.

**Prompt design rules** (encode the Lesson-2 policies):
- Answer **only** from retrieved context; if it's insufficient, abstain.
- **Cite** `doc_id` + `section_id` (and the effective range) for every figure.
- Quote figures **exactly** (this is what `must_include` / `must_not_include` check).
- **Wording overrides tables.** Never assert cover for a section marked "Reserved" (DTI-014), regardless of what any table says.
- For **ambiguous** queries, present both editions with their date ranges.

**Handle the reasoning traps:**
- **Multi-hop numeric (DTI-015/016/017):** pull *all* needed facts from the **same edition** and do the arithmetic in a controlled step. The classic failure is mixing the 2025 aggregation window with the 2024 excess — guard against cross-edition contamination by tagging each retrieved fact with its `doc_id` and refusing to combine mismatched editions.
- **Cross-reference following (DTI-018/019):** the top-ranked chunk is often *not* the answer (Section 7.2 "ceilings" signposts to Section 3 for water-caused collapse; "lightning" scores highest in Section 5 but a no-fire power surge is Section 4). Detect the signpost and do a **second retrieval** for the referenced section.

**Deliverable:** a `generate(query, chunks, mode)` that produces a cited answer (or an abstention), passing `must_include`/`must_not_include` on a hand-picked sample spanning each trap.

**Done when:** DTI-016 returns £4,600 (wet-room excess chosen over standard), DTI-018 routes to Section 3 with £350, and DTI-014 says "Reserved / not offered before 2024."

---

## Lesson 9 — Orchestration with LlamaIndex and LangChain/LangGraph (and when to use each)

**Objective:** rebuild the pipeline in the framework abstractions, learn the trade-offs, and handle the cross-edition-comparison cases that need real multi-step retrieval.

**LlamaIndex pass (data/retrieval layer):**
- Use `AzureAISearchVectorStore` over your existing index, `AzureOpenAI` (LLM) and `AzureOpenAIEmbedding` (remember deployment names), configured via the modern global `Settings` (not the deprecated `ServiceContext`).
- Express the Lesson-6 filters as `MetadataFilters`. LlamaIndex's retriever/query-engine abstractions make the edition-aware retrieval concise.

**LangChain + LangGraph pass (orchestration/agents):**
- `langchain-openai` (`AzureChatOpenAI`, `AzureOpenAIEmbeddings` with `model="text-embedding-3-large"`, optional `dimensions`) + the Azure AI Search vector store integration.
- Model the **Lesson-7 router as a LangGraph graph**: nodes for route → (answer | ask | abstain), with a **multi-hop node** for cross-edition comparison (DTI-022/023): retrieve 2024, retrieve 2025, diff, then generate. This is also where you catch that the 2025 "summary of changes" page is *incomplete* — full credit for DTI-022 requires diffing the wording/fact-matrix, not quoting the summary.

**Compare against the managed options** (build vs buy):
- **Azure AI Search agentic retrieval** natively decomposes "compare 2024 and 2025" into parallel sub-queries — try it on DTI-022 and see how close it gets for free.
- **Foundry Agent Service File Search** as a fully-managed retrieval tool.

**Guidance you'll internalise:** OpenAI SDK for fundamentals and thin production paths; **LlamaIndex** for ingestion/indexing/retrieval ergonomics; **LangChain/LangGraph** for routing and agentic multi-step flows. They all sit on the *same* Search index, so you can mix them.

**Deliverable:** the eval-passing pipeline implemented in at least two stacks, plus a short `FRAMEWORKS.md` recording which you'd pick for which layer and why.

**Done when:** DTI-022/023 (cross-edition comparison) pass, including the "summary is incomplete" nuance.

---

# Phase 4 — Evaluation & hardening

## Lesson 10 — Turn the QA bank into an automated eval harness

**Objective:** stop eyeballing. Score the pipeline across all 25 questions, by category, automatically — using your QA bank as the dataset and `azure-ai-evaluation` for the metrics.

**Your QA bank already contains the ground truth:**
- `gold_doc_ids` / `gold_sections` → **qrels** for the **Document Retrieval** evaluator (Fidelity, NDCG, etc.) and simpler retrieval-hit checks.
- `must_include` / `must_not_include` → a **custom code evaluator** (exact-substring pass/fail).
- `answerable == false` → a **custom abstention evaluator** (did it decline?).
- `ambiguous == true` → a **custom ambiguity evaluator** (did it flag/return both?).
- `answer` (reference text) → **Response Completeness** / **Similarity**.

**Built-in evaluators to wire up** (LLM-judge via `AzureOpenAIModelConfiguration`):
- **Retrieval** — are the retrieved chunks relevant to the query?
- **Groundedness** (1–5) and/or **Groundedness Pro** (Content Safety, pass/fail) — is the answer grounded, or is it inventing figures/section numbers?
- **Relevance** — does the answer address the question?

**Custom evaluators** (subclass/callable): `must_include`/`must_not_include`, `abstention_correct`, and `edition_correct` (did the cited `doc_id` match `gold_doc_ids`?) — the last one is the domain-specific metric that off-the-shelf groundedness won't catch, exactly analogous to the "made-up FCA reference number" custom evaluators teams write for real financial-services RAG.

**Run local first, then cloud:** iterate locally, then submit batch evaluation runs in Foundry and log results to MLflow / App Insights.

**Deliverable:** `run_eval.py` producing a per-question and per-category scorecard, plus a **baseline-vs-current** comparison against Lesson 5.

**Done when:** you have a single command that scores the whole bank and shows measurable improvement over the naive baseline.

---

## Lesson 11 — Close the gaps; add guardrails and safety

**Objective:** iterate to a target score and make the system safe to put in front of a claims handler.

**Error-analysis loop:** read the Lesson-10 scorecard, pick the worst category, form a hypothesis (bad chunk boundary? filter not applied? prompt not following a signpost?), fix one thing, re-run. Repeat. Typical fixes land in chunking, filter construction, reranking depth, or prompt rules — not model swaps.

**Guardrails for an insurance assistant:**
- **Groundedness / hallucination detection** on every answer (Content Safety Groundedness Pro) — block or flag answers that assert figures not in the retrieved wording.
- A hard rule and a post-check: **never emit a monetary figure or section number that isn't present in the retrieved context.**
- **Prompt-injection** basics (the retrieved docs are trusted here, but the user turn isn't).
- **PII handling** and logging hygiene — claims contexts contain personal data.
- **Scope/role framing:** the assistant surfaces policy wording to help a handler; it isn't giving a coverage decision or legal advice. Make abstention and "check the schedule" prominent (the wording itself defers to the schedule).

**Deliverable:** a pipeline that hits your target (suggested bar: every `answerable` question correct on `must_include`/`must_not_include`, every abstention correct, no ungrounded figures), plus a `GUARDRAILS.md`.

**Done when:** the scorecard is green on your bar *and* the groundedness check catches a deliberately-injected wrong figure in a test.

---

# Phase 5 — Serve, operate, and the capstone

## Lesson 12 — Serve it: API + a claims-handler UI, then deploy

**Objective:** expose the pipeline as a service a human can use.

**Backend:** a **FastAPI** app with a streaming `/chat` endpoint wrapping `route → retrieve → generate`. Every response returns the answer **plus citations** (`doc_id`, `section_id`, effective range) **plus the governing edition it selected and why** — auditability matters more than polish in insurance.

**Frontend:** a minimal chat UI (build one, or adapt an Azure RAG chat sample). The claims-handler UX should make three things obvious: which edition governs (and the date/edition logic that chose it), the citations, and when the assistant is abstaining.

**Deploy (to dev, by hand, once):** containerise, push to a shared registry, and run it on **Azure Container Apps**, created in the portal. Give the app a **user-assigned managed identity** with exactly AcrPull, Foundry User and Search Index Data **Reader**. Secrets, if any, go in **Key Vault**; config comes from `deploy/<env>.env`. The image holds no environment-specific config, so the same digest can run everywhere. Optionally stand up the same thing as a **Foundry Agent** to compare hosting models.

**Deliverable:** the app running in dev, answering DTI questions with citations and edition reasoning. Every portal step goes into the runbook for test and prod.

**Done when:** a colleague can ask "kitchen flooded 15 March 2024, what's the excess?" and get "£300, per DTI-HOME-PW-2024-v1.0 §3.4/§10, in force 1 Jan–31 Dec 2024," with the citation shown.

---

## Lesson 13 — Observability, eval-gated CI/CD, and the capstone demo

**Objective:** make it operable and provably non-regressing — then assemble the capstone.

**Observability:** OpenTelemetry traces → **Application Insights**; dashboards for token cost, latency (retrieval vs generation), and groundedness rate. **Log the retrieved context and the selected edition for every answer** — this is your audit trail.

**Build test and prod** in the portal from the runbook, with nothing improvised.

**Eval-gated promotion:** GitHub Actions builds the image and `chunks.jsonl` **once**, then promotes them dev → test → prod. Each environment has its own OIDC-federated managed identity, scoped to that environment only, and a GitHub environment. Prod has required reviewers. Before each deploy, `check_env` compares the environment's live configuration with `deploy/environments.yaml` and stops on drift. Two gates:
- a **PR gate**: `run_eval.py` in-process against a throwaway index in test. It blocks merge.
- a **promotion gate**: the eval bank through test's deployed API. It blocks prod.

Adopt the "block, don't slow" discipline real regulated teams use.

**Capstone assembly & demo runbook.** Your capstone is the deployed, evaluated, observable claims-handler assistant. Prove it by demoing, live, one question from each instructor-guide exercise plus abstention:
1. Temporal — dated 2024 excess (£300).
2. Same-year minor version — 2023 cycle limit by exact date.
3. Freshness default — bare "standard excess" → £350 + caveat.
4. Clause existence — communicable disease (no in 2022, yes from 2023).
5. Table-vs-wording trap — home emergency before 2024 → "Reserved."
6. Paraphrase — "tiles blew off, rain came in" → storm (Section 4).
7. Multi-hop numeric — 80-hour storm gap: two excesses in 2024, one in 2025.
8. Cross-section — burst-pipe ceiling collapse → Section 3, not 7.2.
9. Abstention — 2021 edition / motor cover → decline.

**Final deliverables (the capstone package):**
- The deployed end-to-end app (repo + live endpoint).
- The eval harness and its scorecard, wired into CI as a gate.
- An architecture diagram and a short design doc covering the three policies (source-of-truth, edition-selection, abstention) and the framework choices.
- The demo runbook above.

**Done when:** all nine demo cases pass live against prod, a fresh commit that breaks retrieval is *automatically blocked* by the eval gate, and a change that breaks the deployment is stopped before it reaches prod.

---

## Suggested pacing

Roughly 10–13 weeks part-time, one lesson per ~half-week, with Phases 1 and 4 deserving the most time — data engineering and evaluation are where RAG systems are actually won or lost. If you're time-boxed, the irreducible core is Lessons 2 → 3 → 4 → 6 → 7 → 8 → 10: metadata-driven retrieval plus honest evaluation. Everything else makes it production-grade.

## A short brush-up list (things worth refreshing before you start)
- OData filter syntax in Azure AI Search and `vectorFilterMode` pre/post-filtering.
- RRF and how hybrid + semantic ranking interact (semantic ranker reranks the fused set; it doesn't use the vectors).
- `DefaultAzureCredential` and the RBAC roles for Search and Azure OpenAI.
- The difference between a model *name* and a *deployment name* in Azure OpenAI (both LlamaIndex and LangChain need the deployment name).
- GitHub Actions environments, and OIDC federated credentials on a user-assigned managed identity. These are what let a pipeline deploy to prod with no stored secret.
