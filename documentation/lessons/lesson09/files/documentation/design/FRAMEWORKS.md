# Frameworks: a decision record

Which tool for which layer, and why. Evidence first; opinions only where labelled.

Code: `src/dti_rag/orchestration/` (`llamaindex_retriever.py`, `graph.py`). Both stacks sit on the same index (`dti-policy-v1`), so only the orchestration layer changes.

---

## 1. Decision

| Layer | Production choice | Why |
|---|---|---|
| Ingestion and chunking | Own code (`ingestion/`) | Section-aware chunking is the product; no framework splitter keeps `section_id` |
| Index schema and loading | Own code + `azure-search-documents` | The schema is a contract across three environments; it must be explicit |
| Retrieval | Own code (`retrieval/`) | Pre-filtering, typed filters and date ranges must be guaranteed, not inherited |
| Routing and orchestration | Own code (`pipeline.py`), **designed in LangGraph** | The graph clarified the compare branch and the post-retrieval ambiguity check; both were ported to ~40 lines of plain code |
| Generation | OpenAI SDK, structured outputs | One call shape everywhere; every call auditable |

**What would change the decision:** a genuinely agentic flow (open-ended multi-step tool use) would move orchestration to LangGraph. This corpus's flows are fixed and short.

---

## 2. What each abstraction hid

### LlamaIndex (`AzureAISearchVectorStore`), from `uv run python -m dti_rag.orchestration.llamaindex_retriever`

| Question | Finding | Evidence |
|---|---|---|
| Does `MetadataFilters` keep pre-filtering? | It never sets `vector_filter_mode`, so it **inherits the service default** (pre-filter in current API versions). Correct today by accident of a default, not by design. | Probe 1: ____ nodes, doc_ids = ____ |
| Can it express a date range? | **No.** String values are quoted, so `effective_from le '2024-…'` is a type error against `Edm.DateTimeOffset`. Edition selection must go through `doc_id`. | Probe 2 error: ____ |
| Semantic ranking? | Supported (`semantic_hybrid` mode). Scores are reranker scores (0–4) in that mode and RRF scores in `hybrid` mode. | Probe 3: ____ |
| Schema demands | Requires a JSON metadata string field (`metadata_json`, added to the schema for it) and a `doc_id` field it treats as the parent document. | `schema.py` |
| Environment safety | Azure classes fall back to `AZURE_OPENAI_ENDPOINT` / `OPENAI_API_VERSION` env vars if a value isn't passed. Every value is passed explicitly. | `llamaindex_retriever.configure()` |

### LangGraph (`graph.py`)

| Where it earned its place | Where it cost |
|---|---|
| The `compare` branch as a node, not an `if` buried in a function | Another dependency that moves fast |
| The post-retrieval ambiguity check as an explicit edge | Harder stack traces through the graph runtime |
| Explicit state (question, route, retrievals, answer), which makes tracing easy | Nothing it does here needs its runtime: no loops, no persistence, no human-in-the-loop |

---

## 3. Managed options, on the same questions

Run in **dev only**, and delete what they create afterwards.

| Option | DTI-004 (dated) | DTI-008 (ambiguous) | DTI-022 (compare) | DTI-024 (abstain) | Notes |
|---|---|---|---|---|---|
| Our pipeline | ____ | ____ | ____ | ____ | |
| Azure AI Search agentic retrieval | ____ | ____ | ____ | ____ | GA or preview in the pinned API version? ____ |
| Foundry Agent Service, File Search | ____ | ____ | ____ | ____ | Doesn't know the metadata schema |

The expected shape: managed options do well on simple lookups and poorly on edition selection. That gap is the value of Lessons 02–07. Quantify it.

---

## 4. Audit and lock-in

"Can I explain to an auditor exactly what this call did?"

- Own code: yes. The OData filter sent, the prompt version and the chunks are all logged.
- LlamaIndex: mostly, but the filter mode is implicit and the node reconstruction is opaque.
- Agentic retrieval / File Search: the sub-queries and ranking are the service's; you can log inputs and outputs, not the reasoning in between.

---

## 5. Environment cost

| Option | What it adds to the infrastructure | Allowed in prod? |
|---|---|---|
| LlamaIndex / LangGraph | Nothing in Azure; a dependency to pin | Yes, if adopted: it's code, promoted like code |
| Agentic retrieval | Knowledge sources / agents inside the Search service, created by code in every environment | Only once GA, by explicit policy decision |
| Foundry Agent Service | Agents and vector stores in the Foundry project | Same: preview features need a written decision |
