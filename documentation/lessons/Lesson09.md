# Lesson 09 — Orchestration with LlamaIndex and LangGraph (and when to use each)

**Objective:** rebuild the pipeline in framework abstractions, learn the trade-offs
first-hand, and solve the cross-edition comparison cases that need real multi-step
retrieval.

**Deliverable:** the pipeline in at least two stacks, plus
`Documentation/design/FRAMEWORKS.md` recording which you'd pick for which layer and why.

---

## Why rebuild something that works

Two honest reasons and one dishonest one.

**Honest #1: you'll be handed a codebase that uses them.** LlamaIndex and LangChain are
everywhere. Knowing what they do — and what they hide — is table stakes.

**Honest #2: DTI-022/023 need multi-step retrieval you haven't built.** "What changed
between 2024 and 2025?" requires retrieving two editions, diffing them, then generating.
That's a graph, and doing it by hand teaches you why graph frameworks exist.

**Dishonest reason to avoid: "frameworks are best practice."** You've already built a
working pipeline on the raw SDKs. If the framework version isn't clearly better for a
layer, say so in `FRAMEWORKS.md`. **"We evaluated it and stayed with the SDK" is a
legitimate, and often correct, engineering outcome** — especially in regulated environments
where an abstraction you can't fully inspect is a liability.

The thing that makes this lesson cheap: **all three stacks sit on the same Azure AI Search
index.** You're swapping the orchestration layer, not rebuilding the system. That's worth
noticing as an architectural property you engineered for.

---

## The LlamaIndex pass (data / retrieval layer)

Use `AzureAISearchVectorStore` over your **existing** index — don't let it build a new one.

Configure via the modern global `Settings` object (`Settings.llm`, `Settings.embed_model`).
`ServiceContext` is deprecated and most tutorials you'll find still use it.

Both `AzureOpenAI` and `AzureOpenAIEmbedding` want the **deployment name** — that Lesson 1
distinction again, and it's where most LlamaIndex/Azure setup time goes.

Express your Lesson 6 filters as `MetadataFilters`. This is where LlamaIndex is genuinely
good: the retriever/query-engine abstractions make edition-aware retrieval concise, and
metadata filtering is a first-class concept rather than a string you build.

**What to evaluate as you go:**

- Does `MetadataFilters` give you `preFilter` semantics, or does it silently post-filter?
  **Verify this** — it's the one place a framework abstraction could quietly undo Lesson 6's
  central fix. Run the DTI-004 test through the LlamaIndex path and check every returned
  chunk is 2024.
- Can you express a date **range** filter cleanly, or only equality?
- What happens to the semantic ranker configuration?

Answer those three in `FRAMEWORKS.md` with evidence, not impressions.

---

## The LangChain + LangGraph pass (orchestration / agents)

`langchain-openai` (`AzureChatOpenAI`, `AzureOpenAIEmbeddings` — `model=` plus optional
`dimensions=`) with the Azure AI Search vector store integration.

The real exercise: **model the Lesson 7 router as a graph.**

```
                    ┌─────────┐
                    │  route  │
                    └────┬────┘
           ┌─────────────┼─────────────┬──────────────┐
           ▼             ▼             ▼              ▼
      ┌────────┐   ┌─────────┐   ┌─────────┐   ┌──────────┐
      │ answer │   │   ask   │   │ abstain │   │ compare  │
      └───┬────┘   └─────────┘   └─────────┘   └────┬─────┘
          │                                          │
          ▼                                  ┌───────┴───────┐
     ┌──────────┐                            ▼               ▼
     │ retrieve │                      retrieve(2024)  retrieve(2025)
     └────┬─────┘                            └───────┬───────┘
          │                                          ▼
          ▼  signpost detected?                   ┌──────┐
     ┌──────────┐                                 │ diff │
     │ generate │◄────────────────────────────────┴──────┘
     └──────────┘
```

Where a graph genuinely earns its place over your hand-rolled pipeline:

- **The `compare` node** fans out to two retrievals and joins. Awkward as straight-line code,
  natural as a graph.
- **The signpost loop** (Lesson 8) is a conditional edge back to `retrieve` — this is the
  principled version of the follow-up retrieval you hacked in.
- **The post-retrieval ambiguity check** you deferred in Lesson 7: a conditional edge from
  `retrieve` back to `ask` when the retrieved editions disagree. This is the clean answer to
  that design question.
- **State is explicit.** The graph's state object carries query, filter, mode, chunks,
  citations — which makes tracing in Lesson 13 nearly free.

Where it costs you: another abstraction between you and the API, harder stack traces, and a
dependency that moves fast. Note both sides.

---

## Cross-edition comparison (DTI-022, 023)

### DTI-022 — "What changed between the 2024 and 2025 editions?"

The trap from Lesson 2: page 2 of the 2025 edition has a "Summary of changes" listing eight
changes, and **omits four real ones** — `outbuildings_limit` (£1,500→£2,000),
`emergency_repair_limit` (£750→£1,000), `ad_excess` (£150→£200), `he_limit` (£1,000→£1,500).

That summary chunk will rank first. It looks authoritative. A single-retrieval pipeline
quotes it and loses four changes.

Full credit needs a **diff**, which means a genuine architectural choice:

| Strategy | How | Trade-off |
|---|---|---|
| **Section-by-section wording diff** | Retrieve all chunks for both editions, compare pairwise | Most faithful, most tokens, works on any corpus |
| **Fact-matrix diff** | Compare the two rows of `editions_fact_matrix.csv` | Cheap and complete — but violates the source-of-truth policy |
| **Summary + verification** | Take the summary, then verify each claimed change and sweep for unlisted ones | Pragmatic middle |

Note the tension in the middle option. The fact matrix would give a complete, correct answer
cheaply — and it's the artefact that carries the DTI-014 lie. **You can use the matrix as a
diff *index* (where to look) but must confirm each change against the wording.** Write that
reasoning down; it's exactly the kind of judgement a reviewer will ask you to justify, and
"the cheap source is untrustworthy in a specific known way, so it navigates but doesn't
testify" is a good answer.

### DTI-023 — "Has the storm wind-speed threshold ever changed, and when?"

Across all five editions: 48 knots in 2022, 47 from 2023 v1.0 onward. This is a **change
history** question, not a value lookup — the answer is the shape of the change over time.

Nice detail: the 2023 v1.0 change summary states the *reason* for the alignment, and citing
it makes for a materially better answer. Change summaries are incomplete, but what they do
say is useful.

---

## Build vs buy: the managed options

Run both against the same questions and record what you find.

**Azure AI Search agentic retrieval** natively decomposes "compare 2024 and 2025" into
parallel sub-queries. Try DTI-022 and see how close it gets with no orchestration code. It's
newer than the rest of your stack — check whether it's GA or preview in the API version you
pin, and whether it's available in your region. Note too that from Search API `2026-04-01`
its billing is a separate service-level consent from the semantic ranker's; check your
service's **Premium features** settings.

**Foundry Agent Service File Search** is fully-managed retrieval. Useful as a baseline for
"what do you get for almost no effort?" Expect it to do well on simple lookups and poorly on
edition selection, since it doesn't know your metadata schema — and that gap *is* the value
of everything you built in Lessons 2–7. Quantify it.

This comparison is genuinely valuable for your capstone. "We built it by hand because the
managed option scored X and ours scored Y on temporal disambiguation" is a defensible
engineering decision. "We built it by hand" alone is not.

---

## What goes in FRAMEWORKS.md

Not a feature comparison — a **decision record**:

1. **Which layer, which tool, why.** The guidance you're likely to converge on: OpenAI SDK
   for fundamentals and thin production paths; LlamaIndex for ingestion/indexing/retrieval
   ergonomics; LangChain/LangGraph for routing and agentic multi-step flows. Confirm or
   refute it with what you actually observed.
2. **What each abstraction hid** — especially whether `MetadataFilters` preserved
   pre-filtering. Hidden behaviour that undoes a correctness fix is the most important thing
   you can document.
3. **Managed-option scores** on the same questions.
4. **What you'd use in production here, and why** — including any layer where you'd keep the
   raw SDK.
5. **Lock-in and audit cost.** In a regulated setting, "can I explain to an auditor exactly
   what this call did?" is a real criterion.
6. **Environment cost.** What each option adds to the environment runbook, and whether it's
   allowed in prod at all (see below).

---

## Environments

**Frameworks must read your settings, not the process environment.** LangChain's
`AzureChatOpenAI` and `AzureOpenAIEmbeddings` fall back to environment variables such as
`AZURE_OPENAI_ENDPOINT` and `OPENAI_API_VERSION` when you don't pass values explicitly, and
LlamaIndex's Azure classes have similar fallbacks. A stale `export` in your shell then points
the framework at a different environment, or a different API version, from the rest of your
pipeline, and nothing errors. Build every framework client from `config.py` values, pass
them explicitly, and pass the same token provider your `clients.py` factories use.

**Managed-option experiments run in dev only, and you clean up after them.** Agentic
retrieval and Foundry Agent Service create objects inside your Foundry project and search
service (knowledge sources, agents, vector stores) that no runbook and no loader knows
about. That's fine for an experiment. It becomes drift the moment one of them leaks into
test. Delete what you created when you've recorded the scores.

**If a managed option earns a place in production,** everything it needs gets created by
code (your loader, or a setup script the pipeline runs) or recorded in the runbook and
applied identically in every environment. Never by clicking in the portal of whichever
environment you happen to be looking at. Preview features also need an explicit policy
decision before prod: no SLA, and they can change under you. Many regulated firms simply
don't allow them in prod. Write down what you'd propose in `FRAMEWORKS.md`.

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Letting LlamaIndex create its own index | Two indexes, divergent schemas |
| `ServiceContext` from an old tutorial | Deprecated; obscure errors |
| Model name instead of deployment name | `DeploymentNotFound` |
| Not verifying `MetadataFilters` pre-filters | Lesson 6's central fix silently undone |
| Quoting the 2025 change summary | Four missing changes |
| Diffing the fact matrix alone | Violates source-of-truth; inherits the DTI-014 lie |
| Adopting a framework because it's popular | Abstraction you can't audit |
| Rebuilding everything in both | Time sink; rebuild the layer you're evaluating |
| Framework clients picking up shell environment variables | Silently talking to a different environment |
| Leaving agents / knowledge sources behind after experiments | Drift nobody recorded |

---

## Done when

DTI-022 and DTI-023 pass, **including the "summary is incomplete" nuance**, and
`FRAMEWORKS.md` records a decision you could defend in a design review.

## Check yourself

1. Why does `compare` want to be a graph node rather than an `if` branch?
2. How do you verify LlamaIndex's `MetadataFilters` pre-filters rather than post-filters,
   and what's the observable symptom if it doesn't?
3. Why can the fact matrix navigate the DTI-022 diff but not testify to it?
4. Where does agentic retrieval beat your hand-built pipeline, and where does it lose?
5. Which Lesson 7 design question does a LangGraph conditional edge resolve cleanly?
6. What would make you keep the raw SDK for a layer despite a framework working?

---

**Next:** [Lesson 10 — Turn the QA bank into an automated eval harness](Lesson10.md)
