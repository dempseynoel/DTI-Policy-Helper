# Learning path index

Each lesson is a single file in `lessons/` (`Lesson00.md` … `Lesson13.md`): what you're
building, why it's built that way, the corpus-specific detail that decides the design, and
the pitfalls that will actually bite. Read before you code.

**Environments.** The system runs in three environments: dev, test and prod. You build the
Azure resources yourself in the portal, following the runbook you start in Lesson 01. A
GitHub Actions pipeline, built in Lesson 13, promotes the application dev → test → prod,
gated by the eval harness. Lesson 01 builds dev and designs all three. Lesson 04 covers
loading the index in each environment, Lesson 12 deploys to dev, and Lesson 13 builds test
and prod and the promotion pipeline. Each of the others has an **Environments** section on
what the separation means for the part you're building.

| Lesson | Title | Phase | Deliverable |
|---|---|---|---|
| [00](lessons/Lesson00.md) | Orientation and repo shape | — | You can navigate the skeleton and explain each layer |
| [01](lessons/Lesson01.md) | Build dev in the portal; design dev/test/prod; prove the dev loop | 0 — Foundations | dev built, `design/ENVIRONMENTS.md`, `deploy/dev.env`, `scripts/smoke_test.py` runs |
| [02](lessons/Lesson02.md) | Read the corpus as an adversary; design the schema | 1 — Data | `design/SCHEMA.md` + corpus map |
| [03](lessons/Lesson03.md) | Parse and chunk the PDFs | 1 — Data | `artifacts/chunks.jsonl` |
| [04](lessons/Lesson04.md) | Build and load the Search index | 1 — Data | Populated index, both loading paths |
| [05](lessons/Lesson05.md) | Baseline pipeline; watch it fail | 2 — Retrieval | `design/baseline_failures.md` |
| [06](lessons/Lesson06.md) | Hybrid search, semantic ranking, filters | 2 — Retrieval | `retrieve(query, filters)` |
| [07](lessons/Lesson07.md) | Query understanding and routing | 2 — Retrieval | `route(query)` |
| [08](lessons/Lesson08.md) | Grounded generation, citations, multi-hop | 3 — Generation | `generate(query, chunks, mode)` |
| [09](lessons/Lesson09.md) | LlamaIndex and LangGraph; build vs buy | 3 — Generation | `design/FRAMEWORKS.md` |
| [10](lessons/Lesson10.md) | The eval harness | 4 — Evaluation | `evaluation/run_eval.py` scorecard |
| [11](lessons/Lesson11.md) | Close the gaps; guardrails | 4 — Evaluation | `design/GUARDRAILS.md`, green scorecard |
| [12](lessons/Lesson12.md) | Serve it: API, UI, deploy to dev | 5 — Production | The app running in dev on managed identity |
| [13](lessons/Lesson13.md) | Observability, promotion dev → test → prod, capstone | 5 — Production | test + prod built from the runbook; gated pipeline; demo against prod |

## If you're time-boxed

The irreducible core is **02 → 03 → 04 → 06 → 07 → 08 → 10**. That gets you
metadata-driven retrieval plus honest evaluation, which is the actual lesson of this
corpus. Lesson 01's dev environment is a prerequisite for everything from 04 onwards. Test
and prod aren't: they arrive in 13. Lessons 05, 09, 11, 12 and 13 are what make it a system
you could put in front of a regulated business.

## Keep this table open while you work

Every question in the QA bank probes a specific failure mode. "Which case am I trying to
make pass right now?" is the question that keeps the build honest.

| Category | IDs | Fixed in |
|---|---|---|
| `single_fact_lookup` | 001–003 | 04, 06 |
| `temporal_disambiguation` | 004–007 | 06, 07 |
| `version_ambiguity` | 008, 009 | 07 |
| `freshness_default` | 010, 011 | 07 |
| `clause_existence` | 012–014 | 03, 08 |
| `multi_hop_numeric` | 015–017 | 08 |
| `cross_section` | 018, 019 | 08, 09 |
| `paraphrase_robustness` | 020, 021 | 06, 09 |
| `cross_edition_comparison` | 022, 023 | 09 |
| `abstention` | 024, 025 | 07, 11 |

## A note on the source material

`Documentation/AzureRAGLearningPath.md` references a `DTI-HOME-INSTRUCTOR-GUIDE.pdf` that
is **not** in `Data/`. Nothing depends on it — the fact matrix, the QA bank and the five
PDFs carry everything you need, and the failure modes it would have enumerated are written
out in [lessons/Lesson02.md](lessons/Lesson02.md). Don't go looking for it.
