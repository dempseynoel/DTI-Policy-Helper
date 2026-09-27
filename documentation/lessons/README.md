# Lessons v2 — a production RAG application for insurance, built lesson by lesson

Fourteen lessons that take this repository from five policy PDFs and a question bank to an
edition-aware claims-handler assistant, **deployed to prod on Azure**, evaluated on every pull
request and before every promotion, with an audit trail for every answer.

Each lesson folder has:

```
lessonNN/
├── README.md      the lesson: why, what, how, environments, pitfalls, "done when", check yourself
└── files/         ONLY the files new or changed in this lesson, in full, laid out like the
                   project root, plus a diagram of the whole project at that point (in the README)
```

## How to use it

1. Read `lesson00/README.md` first.
2. For each lesson: **read the README**, attempt the core piece yourself where it suggests
   (02, 03, 07 especially), then apply the files:

   ```bash
   documentation/lessons/apply_lesson.sh 03            # add --dry-run to preview
   make test
   ```

3. Apply lessons **in order**. Copying lessons 00–13 in sequence reproduces the finished
   project exactly (verified), and no file is ever deleted by a later lesson.

`apply_lesson.sh` **never overwrites files you fill in by hand** (`deploy/environments.yaml`,
`documentation/design/*.md`) if they already exist; it prints a `diff` command instead.
`deploy/<env>.env` is written by `terraform apply`, never by hand or by a lesson. v1's
`deploy/dev.env` and `documentation/design/ENVIRONMENTS.md` are replaced in Lesson 01: the
apply rewrites the first, and the second is superseded by `environments.yaml` and `infra/`.

## The lessons

| # | Lesson | You end with | Unit tests |
|---|---|---|---|
| [00](lesson00/README.md) | Orientation | What you're building and why it's shaped this way | — |
| [01](lesson01/README.md) | Build dev; design dev/test/prod | Terraform for all three, dev applied, config, `make smoke ENV=dev` | 11 |
| [02](lesson02/README.md) | Read the corpus like an adversary | `SCHEMA.md`, the corpus map, the traps | 11 |
| [03](lesson03/README.md) | Parse and chunk | 269 deterministic clause-level chunks | 35 |
| [04](lesson04/README.md) | The Search index | A versioned index, both loading paths, a manifest | 44 |
| [05](lesson05/README.md) | The naive baseline | Documented, measured failures | 51 |
| [06](lesson06/README.md) | Hybrid, semantic, filters | `retrieve()`, typed injection-safe filters | 67 |
| [07](lesson07/README.md) | The router | `route()`: LLM extracts, code decides | 92 |
| [08](lesson08/README.md) | Grounded generation | `pipeline.answer()`: cited, per-edition, arithmetic checked | 109 |
| [09](lesson09/README.md) | LlamaIndex, LangGraph, comparison | Two stacks, a clause diff, `FRAMEWORKS.md` | 116 |
| [10](lesson10/README.md) | The eval harness | `make eval`: scorecard, gate, reference | 128 |
| [11](lesson11/README.md) | Close the gaps; guardrails | A green scorecard; figures that can't be invented | 143 |
| [12](lesson12/README.md) | Serve it; deploy to dev | API, UI, image, the app in dev | 149 |
| [13](lesson13/README.md) | Observability, promotion, capstone | test + prod applied, the gated pipeline, the demo against prod | 163 |

Integration tests (`make test-integration ENV=dev`) add 19 more that run against a live
environment.

---

## Review of the v1 lessons: what changed, and why

The v1 lessons (removed from the repo; they're in the first commit, `0d77e13`) are strong on
*why*. The review found they didn't consistently deliver the objective, a production-grade
deployment, because they described code that didn't exist, and in places contradicted each
other, the corpus, or Azure. Every item below is fixed in v2 and backed by code that runs.

### Delivery

| v1 | v2 |
|---|---|
| Described a skeleton as if present ("the dependency set is already in `pyproject.toml`", `.env.example`, `src/dti_rag/…`); the repo had none of it, and no lesson shipped code | Every lesson ships its files. Each lesson's state was built and tested in isolation: lint clean, unit tests passing, on Python 3.11 and 3.12 |
| Paths mixed `Data/` and `data/`, `Documentation/` and `documentation/`, `design/` and `Documentation/design/` | One layout: `data/`, `documentation/design/` |
| Portal settings duplicated between the lessons and `ENVIRONMENTS.md`, and they disagreed | Every setting is in `deploy/environments.yaml`, built by Terraform (`infra/`); lessons explain the decisions |
| The README's category names (`abstention`) didn't match the QA bank's (`abstention_out_of_corpus`, `abstention_out_of_scope`) | The QA bank's names are used everywhere |

### Facts, checked against the PDFs

| v1 said | The PDFs say |
|---|---|
| Section 7 has 7.1–7.6 and Section 9 has 9.1–9.8 in every edition | 7.1–7.5 before 2025; 2022 has 9.1–9.7, with the "how exclusions interact" rule at **9.6**, which moves to **9.7** from 2023. A second section-number decoy, alongside 3.6 |
| Every page has a footer; pages 4–10 hold the sections | The cover has no footer; 2022 and 2023 v1.0 have 9 pages |
| Search keys: encode the `.` in `3.4` (`DTI-HOME-PW-2024-v1.0__3.4` → `…__3_4`) | The doc_id contains a `.` too (`v1.0`). Every illegal character must be replaced |
| (not mentioned) | The 2024 change summary announces a "matching items, pairs and sets" basis of settlement that **appears nowhere in the 2024 wording**: summaries can add changes as well as omit them |
| (not mentioned) | The CURRENT edition's `effective_to` is 31 December 2025, which has passed: a 2026 loss date has no governing edition, and "current" must not be used as a silent fallback |

### Azure and tooling

| v1 | v2 |
|---|---|
| "Default `vectorFilterMode` (post-filter)" is a pitfall | Current API versions default to **pre-filter**. The real risk is relying on any default; v2 sets it explicitly, and Lesson 09 shows LlamaIndex never sets it |
| Cloud Shell step: "PowerShell mode" but bash-style `az` syntax, and a resource name without the suffix; the runbook used `Set-AzCognitiveServicesAccount` instead | One line of Terraform (`local_auth_enabled = false`), the same in every environment |
| `deploy/dev.env`: endpoint with `/openai/v1` for the `AzureOpenAI` client, no suffix, no `AZURE_OPENAI_API_VERSION`, and `AZURE_SEARCH_INDEX` as config | Base endpoint + pinned API version; the index name is versioned in code (as v1's own Lesson 04 required) |
| Lesson 12's env vars omitted the app identity's client ID, and Lesson 13's `--replace-env-vars` would have wiped the one the runbook added | `APP_IDENTITY_CLIENT_ID` is written into `deploy/<env>.env` by Terraform, and `DefaultAzureCredential(managed_identity_client_id=…)` uses it |
| `make smoke` defaulted `ENV=dev` while Lesson 04 called a defaulting loader a pitfall | No Azure-touching target has a default |
| Extras "keep observability out of the production container" | The prod container needs telemetry; v2's container installs core + `api` + `observability` only |
| (not mentioned) | LlamaIndex's Azure Search store requires a JSON metadata field and quotes filter values, so it can't express a date range. Both recorded in `FRAMEWORKS.md` |
| (not caught) | An old `azure-monitor-opentelemetry` resolves against an `opentelemetry-sdk` it can't import. v2 pins a compatible floor and tests the import |

### Design contradictions resolved

| v1 | v2 |
|---|---|
| "The baseline" meant both the naive Lesson 05 pipeline and what the CI gate compares against. Gating against a naive baseline passes almost anything | Two artefacts: the **naive baseline** (the improvement story) and the **reference scorecard** (what the gate compares against, updated deliberately by PR), plus a first-run bootstrap |
| Block any figure not in the context (Lesson 11), which would block the correct DTI-016 answer (£4,600 is computed) | Calculations are shown as working, verified in code, and their results allowed; a figure only the *user* supplied is never evidence |
| The prod approval should show prod's `check_env`, but test's identity can't see prod by design | Test's evidence on the approval screen; prod's `check_env` runs first after approval |
| A nightly drift job over dev/test/prod would wait for prod's required reviewers, or need a deploy identity in an unprotected environment | A read-only `id-dti-rag-drift` identity in its own `drift` environment |
| Deploy identities scoped to one environment can't read the shared registry or other environments, which `check_env` needs | Reader on the shared resource group; cross-environment checks run nightly with the drift identity |
| "Read context back from the audit log by trace_id" had no audit store | Redacted JSON per answer in the environment's storage account, with lifecycle retention; the API **fails closed** if it can't write one |
| The post-retrieval ambiguity check was deferred to Lesson 09 but never specified | `resolve_after_retrieval()`: identical clause wording in both editions means answer, don't ask |
| "Stream the answer" and "buffer until guardrails pass" | Stream progress events; send the answer once, after the guardrails |
| Blank values, stale shell exports and empty env vars were unaddressed | The committed file beats the shell; a blank value means unset; the file's `APP_ENV` must match |

### What was verified, and what wasn't

- **Verified here:** every lesson's code at its own state (lint + unit tests), on Python 3.11
  and 3.12, in clean environments; the chunker against the real PDFs (269 chunks, stable
  SHA-256); the diff that finds the four changes the 2025 summary omits, on the real PDFs;
  the app running from a container-like layout with only runtime dependencies; workflow YAML
  parses; applying lessons 00–13 to a copy of this repo reproduces the finished project;
  every `infra/` folder passes `terraform validate`, `infra/shared` plans against the real
  subscription, and dev, test and prod pass mocked applies (with and without the app and the
  judge) whose generated `deploy/<env>.env` passes `check_env`'s configuration check.
- **Not verified, because it needs your Azure subscription:** anything against live Azure
  (`terraform apply`, the integration tests, `make index`, `make eval`, the deploy), the portal's current labels,
  and the Content Safety groundedness **preview** API version. The Docker image wasn't
  built (no local daemon); its install step was checked separately. Run the integration tests
  in dev first: they're written to find exactly these problems.
