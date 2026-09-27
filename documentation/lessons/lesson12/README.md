# Lesson 12 — Serve it: the API, a claims-handler UI, and deploy to dev

**Objective:** expose the pipeline as a service a handler can use, and deploy it to **dev**
yourself, once (build the image, then let Terraform create the app), so you understand every
piece Lesson 13's pipeline will automate.

**Deliverables:**

- `src/dti_rag/api/`: FastAPI app, response contract, UI
- `Dockerfile` and an allowlist `.dockerignore`: an image with no environment in it
- the app running in dev as `ca-dti-rag-dev`, created by Terraform, pulling its image and
  calling Azure only as `id-dti-rag-app-dev`
- `scripts/smoke_api.py`, passing against dev

---

## The design principle

> **In insurance, auditability matters more than polish.**

A beautiful UI that returns a number is worse than a plain one that returns the number, the
clause it came from, the edition that governs and *why*. The handler is accountable for what
they tell a customer; your job is to make that possible.

---

## The API (`api/app.py`)

| Endpoint | Purpose |
|---|---|
| `POST /chat` | The answer, as JSON |
| `POST /chat/stream` | Server-sent events: `stage` while working, then one `answer` |
| `GET /editions` | The editions held, with effective dates: makes the edition concept visible |
| `GET /health` | Liveness and readiness. **Never calls a model**: a probe that burns tokens costs money every time the app scales |
| `GET /` | The UI |

### The response contract (`api/schemas.py`)

| Field | Why |
|---|---|
| `answer` | The text |
| `mode` | `answer` / `ask` / `abstain`: the UI renders each differently |
| `citations[]` | doc_id, section, dates, page and **quoted text** |
| `governing_editions` | Which edition(s) |
| `edition_reason` | **Why**: "the loss date (15 March 2024) falls within 2024 edition v1.0, in force 1 January to 31 December 2024" |
| `guardrail_status`, `guardrail_detail` | passed / flagged / blocked, and what |
| `trace_id` | Ties the response to the audit log (Lesson 13) |
| `prompt_version`, `git_sha` | Which prompt, which code |

`edition_reason` is what makes this an insurance tool rather than a chatbot. "The system says
£300" is unverifiable; "£300 because the loss date falls inside the 2024 edition's period,
and here's the clause" can be checked in fifteen seconds. The eval harness's `api` target
(Lesson 10) depends on this contract.

### Streaming, and why the answer is buffered

Guardrails run *after* generation. Streaming the text and retracting it a second later means
a handler may already have read, or acted on, a withdrawn figure. So `/chat/stream` streams
**progress** ("Working out which edition applies…", "Checking every figure against the
wording…") and sends the answer **once, after the guardrails**. The latency cost is real,
and the alternative is worse. The pipeline reports stages through an `on_stage` callback.

Settings and the edition registry load **once at startup** (the `lifespan` handler), so a
missing setting or a missing registry file fails the revision before it takes traffic.

---

## The UI (`api/static/index.html`)

One static page, no build step. Three things are unmissable:

1. **Which edition governs, and why**, next to the answer, not buried in a citation.
2. **The citations, with the quoted text.** A handler who has to open a PDF to check will
   stop checking, and an unchecked citation is decoration.
3. **Abstention and `ask` look different from answers.** A distinct colour and badge ("Can't
   answer from the wording", "Question back: which date?"). An abstention that looks like an
   answer will be read as one.

The schedule caveat is permanent, because the wording says throughout that the schedule takes
priority.

```bash
make run ENV=dev        # http://localhost:8000
```

---

## The image

**Build once, promote by digest.** One shared registry serves all three environments. Each
commit's image is built once, tagged with its git SHA, and every environment runs the same
**digest** (`…@sha256:…`). A tag can be re-pointed between the test deploy and the prod
deploy; a digest can't.

**The image contains no environment.** `.dockerignore` is an **allowlist**: everything is
excluded except `pyproject.toml`, `src/` and `data/fact_matrix/editions_fact_matrix.csv`
(the edition registry). No `deploy/*.env`, no `.env`, no `evaluation/`, no PDFs.
Configuration arrives at runtime as environment variables. An allowlist can't leak a new
file by accident, which a denylist can.

**Only runtime dependencies.** The Dockerfile installs the core dependencies plus the `api`
and `observability` extras, read from `pyproject.toml`, and not the package's ingestion,
evaluation or framework extras. `PYTHONPATH=/app/src` runs the code in place. The git SHA is
a build argument, stamped into every response. The container runs as a non-root user on
port 8000.

---

## Deploy to dev

Terraform built everything the app needs in Lesson 01. It just had nothing to run yet:

| Already there | From | What it's for |
|---|---|---|
| Registry `crdtirag` | `infra/shared` | Every environment pulls from it. Admin user off; managed-identity pulls on |
| Your **AcrPush** and **Container Registry Tasks Contributor** on it | `infra/shared` | `make image` runs `az acr build`: an ACR Task builds the image and pushes it. By hand, for now; Lesson 13 hands that job to a build identity |
| `id-dti-rag-app-dev` | `infra/dev` | The app's identity: **user-assigned**, so it existed, with its roles propagated, long before the first revision pulls an image. A system-assigned identity is born with the app, and the first revisions fail while its roles catch up |
| Its roles | `infra/dev` | **AcrPull** (registry), **Foundry User** (chat, embeddings, Content Safety), **Search Index Data Reader**: *Reader*, never Contributor, because the app never writes. Plus the `audit` container, used from Lesson 13 |
| `APP_IDENTITY_CLIENT_ID` | `deploy/dev.env` | `clients.credential()` passes it to `DefaultAzureCredential`, so the app uses *this* identity |
| `cae-dti-rag-dev` | `infra/dev` | The Container Apps environment, logging to dev's workspace |

1. **Push an image**: `make image ACR=crdtirag` (`az acr build`, tagged and stamped with the
   git SHA).
2. **Name it in `deploy/environments.yaml`**: `environments.dev.app_image:
   crdtirag.azurecr.io/dti-rag:<git sha>`.
3. **Apply dev**: `terraform plan -out=tfplan && terraform apply tfplan` in `infra/dev`. The
   plan creates `ca-dti-rag-dev`: the image pulled **through the managed identity**, every
   value of `deploy/dev.env` as an environment variable, liveness and readiness probes on
   `GET /health`, **target port 8000**, scale **0–1** (from `app_replicas`), and the deploy
   identity's Contributor on this app alone. Scale-to-zero saves money at the price of a
   cold start, which the smoke test absorbs by polling `/health`.
4. **Authentication**: optional in dev, required in test and prod (Lesson 13). It isn't in
   Terraform: it creates an app registration, and needs a client secret for browser sign-in
   (see `infra/README.md`).

Then:

```bash
python scripts/smoke_api.py --base-url "$(terraform -chdir=infra/dev output -raw app_url)" --env dev
```

It checks what only a deployment can get wrong: the app reports the right `app_env`; the
registry file is in the image; a dated question selects 2024 and cites (so the index is
loaded and the identity's roles work); an unheld edition abstains; and **an input the
guardrail must reject gets a 422** (the guardrails are wired in).

### After this, Terraform leaves the image alone

`app_image` is only the image the app is **created** with. Terraform ignores the image and
the environment variables after that (`ignore_changes` in `app.tf`): from Lesson 13 the
pipeline deploys each commit's image with `deploy/dev.env` as its variables. Until then, to
run a newer build in dev, push it and run
`az containerapp update -n ca-dti-rag-dev -g rg-dti-rag-dev --image <new image>`.

**Never set `app_image` back to `null`**: Terraform would delete the app. And don't change
the app in the portal: probes, port, scale and identity belong to Terraform, and the next
apply puts them back.

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `src/dti_rag/api/__init__.py` | new | The package |
| `src/dti_rag/api/schemas.py` | new | `ChatRequest`, `ChatResponse`, `EditionOut`: the contract |
| `src/dti_rag/api/app.py` | new | Endpoints; buffered SSE stream; startup checks |
| `src/dti_rag/api/static/index.html` | new | The handler UI |
| `src/dti_rag/pipeline.py` | changed | `on_stage` callback for progress |
| `src/dti_rag/clients.py` | changed | `DefaultAzureCredential(managed_identity_client_id=…)` |
| `Dockerfile` | new | Runtime dependencies only; non-root; git SHA stamped |
| `.dockerignore` | new | An allowlist: no environment in the image |
| `scripts/smoke_api.py` | new | Deterministic checks against a deployed app |
| `tests/unit/test_api.py` | new | Contract, health, 422, buffered stream, UI |
| `pyproject.toml` | changed | `api` extra |
| `Makefile` | changed | `make run ENV=…`, `make image ACR=…` |

You also edit `deploy/environments.yaml` (`app_image`), and the apply rewrites
`deploy/dev.env`.

## Project structure at the end of this lesson

```text
DTI-Policy-Helper/
├── artifacts/
│   ├── eval/
│   │   └── <run>/
│   │       ├── run.json  ◇ generated
│   │       ├── scorecard.json  ◇ generated
│   │       └── scorecard.md  ◇ generated
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
│   │   ├── error_analysis_log.md
│   │   ├── FRAMEWORKS.md
│   │   ├── GUARDRAILS.md
│   │   └── SCHEMA.md
│   └── lessons/  (this course)
├── evaluation/
│   ├── baselines/
│   │   ├── naive-baseline-dev.json  ◇ generated
│   │   └── reference-dev.json  ◇ generated
│   ├── __init__.py
│   ├── checks.py
│   ├── compare.py
│   ├── evaluators.py
│   ├── judge.py
│   ├── qa_bank.py
│   ├── rows.py
│   ├── run_baseline.py
│   ├── run_eval.py
│   ├── runmeta.py
│   ├── scorecard.py
│   └── targets.py
├── infra/  (Terraform: modules/environment, shared, dev, test, prod)
├── scripts/
│   ├── experiments/
│   │   └── integrated_vectorization.py
│   ├── ask.py
│   ├── build_corpus_map.py
│   ├── compare_filters.py
│   ├── measure_retrieval.py
│   ├── smoke_api.py  ★ new
│   └── smoke_test.py
├── src/
│   └── dti_rag/
│       ├── api/
│       │   ├── static/
│       │   │   └── index.html  ★ new
│       │   ├── __init__.py  ★ new
│       │   ├── app.py  ★ new
│       │   └── schemas.py  ★ new
│       ├── generation/
│       │   ├── __init__.py
│       │   ├── arithmetic.py
│       │   ├── compare.py
│       │   ├── crossref.py
│       │   ├── generate.py
│       │   └── prompts.py
│       ├── guardrails/
│       │   ├── __init__.py
│       │   ├── check.py
│       │   ├── figures.py
│       │   ├── groundedness.py
│       │   ├── pii.py
│       │   └── user_input.py
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── __main__.py
│       │   ├── chunk.py
│       │   └── parse.py
│       ├── orchestration/
│       │   ├── __init__.py
│       │   ├── graph.py
│       │   └── llamaindex_retriever.py
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
│       │   └── retrieve.py
│       ├── search/
│       │   ├── __init__.py
│       │   ├── documents.py
│       │   ├── loader.py
│       │   ├── manifest.py
│       │   └── schema.py
│       ├── __init__.py
│       ├── clients.py  ✎ changed
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
│       ├── test_api.py  ★ new
│       ├── test_checks.py
│       ├── test_chunking.py
│       ├── test_compare.py
│       ├── test_config.py
│       ├── test_editions.py
│       ├── test_evaluators.py
│       ├── test_filters.py
│       ├── test_generation.py
│       ├── test_graph.py
│       ├── test_guardrails.py
│       ├── test_router.py
│       └── test_search_schema.py
├── Dockerfile  ★ new
├── .dockerignore  ★ new
├── .gitignore
├── Makefile  ✎ changed
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
| Citations without quoted text | Nobody checks them |
| No `edition_reason` | The most important decision can't be verified |
| Abstention rendered like an answer | Read as an answer |
| Streaming text before the guardrail check | A handler reads retracted text |
| Health probe calling a model | Cost and throttling per probe |
| Search Index Data **Contributor** on the app identity | Over-privileged; the app never writes |
| System-assigned identity for the app | First revisions can't pull or call Search while roles propagate |
| `APP_IDENTITY_CLIENT_ID` missing | `DefaultAzureCredential` can't pick the user-assigned identity |
| Registry refuses managed-identity pulls | ARM-audience tokens disabled (`azuread_authentication_as_arm_policy_enabled` in `infra/shared`) |
| Promoting a tag instead of a digest | Test and prod ran different images under one name |
| `deploy/*.env` inside the image | One environment's endpoints baked into another |
| `app_image` set back to `null` | Terraform deletes the Container App |
| Editing the app in the portal | The next apply reverts it, or the next deploy does |

## Done when

A colleague asks *"kitchen flooded 15 March 2024, what's the excess?"* in **dev** and sees:

> **£300** · governing edition DTI-HOME-PW-2024-v1.0, in force 1 January–31 December 2024,
> selected because the loss date falls within that period · §3.4, with the quoted clause ·
> *the schedule takes priority*

and `smoke_api.py` passes against dev, `id-dti-rag-app-dev` holds exactly its roles, and
`terraform plan` in `infra/dev` says **No changes**.

## Check yourself

1. Why is `edition_reason` a required field?
2. What breaks if you stream the answer before the guardrail check?
3. Which Search role does the app identity get, and why not yours?
4. Why must `/health` not call the model?
5. Why a user-assigned identity rather than system-assigned?
6. Why promote a digest rather than a tag?
7. Why is `.dockerignore` an allowlist?

---

**Next:** [Lesson 13 — Observability, promotion dev → test → prod, and the capstone](../lesson13/README.md)
