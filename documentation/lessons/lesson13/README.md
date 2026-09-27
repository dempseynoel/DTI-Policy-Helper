# Lesson 13 — Observability, promotion dev → test → prod, and the capstone

**Objective:** make the system operable and provably non-regressing; build test and prod with
Terraform; promote one artefact through three environments behind an eval gate and your
approval; then demo it against prod.

**Deliverables:**

- traces in each environment's Application Insights; a complete, redacted **audit log**
- test and prod built by `terraform apply`; the only portal step is the apps' authentication
- `scripts/check_env.py`: a live environment that differs from `deploy/environments.yaml` stops a deploy
- `.github/workflows/`: `ci`, `pr-eval`, `deploy` (+ `_deploy-env`), `drift`
- `documentation/design/ARCHITECTURE.md` (the capstone design doc and demo runbook) and
  `OBSERVABILITY.md`
- the nine demo cases passing live **against prod**

---

## Part 1 — Observability

### Traces (`observability/telemetry.py`)

`configure_azure_monitor()` at app startup sends OpenTelemetry to **this environment's** App
Insights and instruments FastAPI, HTTP and the Azure SDK. The pipeline adds a span per stage:
`chat` → `route` → `retrieve` → `generate` → `guardrail_check`. Aggregate latency tells you
the system is slow; per-stage latency tells you *which part*, and the fixes are completely
different.

Span attributes (full table in `OBSERVABILITY.md`): mode, editions, the OData filters sent,
chunks retrieved and top score, **token counts** (accumulated across the several model calls
one stage can make), guardrail status, prompt version.

- **Every span says where it came from**: `deployment.environment.name` = `APP_ENV` and
  `service.version` = the git SHA, as resource attributes.
- **Sampling** is 100% in dev and test and 0.2 in prod (`trace_sampling_ratio` in
  `environments.yaml`, written into `deploy/<env>.env` as `TRACE_SAMPLING_RATIO`): a cost
  setting, so it may differ.
- **Never point two environments at one App Insights**: test traffic in prod's dashboards
  corrupts the one signal you rely on.
- **Build the workbook once**, in dev, from the KQL in `OBSERVABILITY.md`; copy its JSON into
  the repo and import it into test and prod. **Alerts** in prod: blocks, abstention spike,
  p95, 5xx, 429.

### The audit trail (`observability/audit.py`)

> **Log the retrieved context and the selected edition for every answer.**

When a handler is asked in six months why a customer was told £300, the answer must be
reconstructible: this question, this edition, this reason, these chunks, this draft, this
answer, this prompt, this code, this environment. `build_record()` assembles exactly that,
and `write_record()` writes it to `audit/<trace_id>.json` in the environment's storage
account.

| | Traces | Audit log |
|---|---|---|
| For | Operations | Accountability |
| Completeness | Sampled in prod | **Every answer** |
| Retention | Short | Complaint-handling timeframe (lifecycle rule on `audit/`) |
| Personal data | None on spans | **Redacted** (Lesson 11) before writing |
| Access | Operators | Named roles only |

Conflating them fails both ways: sampled traces are useless as an audit trail, and
audit-retention traces are expensive and a liability.

**Fail closed.** If the audit record can't be written, `/chat` returns **503** and no answer:
an answer that can't be audited isn't given. That's a deliberate trade of availability for
accountability; record it in `GUARDRAILS.md`.

**Read back by `trace_id`.** The promotion gate (`run_eval --target api`) reads each
answer's retrieved context from the audit log, so every promotion also proves the audit
trail is complete.

---

## Part 2 — Build test and prod with Terraform

Lesson 01 wrote test and prod into `deploy/environments.yaml` and `infra/`. Building them is
now the test of that code: **if you have to do anything by hand, it goes into the code
first.** Test built by a colleague at 2am has to come out the same as yours.

1. **Decide what Lesson 01 left open**, in `environments.yaml`: test's and prod's `chat` TPM
   (sized by arithmetic), prod's `app_replicas.max`, and prod's log and audit retention (the
   complaint-handling timeframe; today's 30 days are placeholders).
2. **Give test a judge**: add `judge` to `environments.test.capacity`. Not prod: `check_env`
   treats a judge in prod as drift, and the module refuses to create one.
3. **Name the image**: set `app_image` for test and prod to the **digest** dev is running
   (`crdtirag.azurecr.io/dti-rag@sha256:…`). From the first pipeline run, the pipeline
   deploys every image.
4. **Apply**, test then prod:

   ```bash
   cd infra/test && terraform init && terraform plan -out=tfplan && terraform apply tfplan
   cd ../prod    && terraform init && terraform plan -out=tfplan && terraform apply tfplan
   git add deploy/test.env deploy/prod.env deploy/environments.yaml infra/*/.terraform.lock.hcl
   ```

   Each writes its `deploy/<env>.env`: `prod.env` has **no judge** and a lower sampling
   ratio. The prod apply also sets what only prod has: the delete lock, purge protection,
   two Search replicas and at least one app replica.

**Check access** on yourself for test's and prod's Foundry, Search and Storage: **no data
roles.** You built these environments, and you can't read their data. That's the design,
and `check_env` fails if it stops being true.

---

## Part 3 — Identities and GitHub environments

Six user-assigned managed identities in `rg-dti-rag-shared`, each trusted, through a
**federated credential**, by exactly one kind of GitHub job. No secrets, no app
registrations. Terraform created the identities in Lesson 01; the federated credentials
appear once `environments.yaml` names the repository.

| Identity | Created by | Trusted by | Can |
|---|---|---|---|
| `id-dti-rag-build` | `infra/shared` | branch `main` | AcrPush + Container Registry Tasks Contributor on the registry (`az acr build` runs a task that pushes) |
| `id-dti-rag-deploy-dev` / `-test` / `-prod` | `infra/<env>` | environment `dev` / `test` / `prod` | Deploy roles **in its own environment only** (+ Reader on shared) |
| `id-dti-rag-eval` | `infra/shared` (roles from `infra/test`) | environment `pr-eval` | Data-plane access to **test's** Search and models; nothing that can touch a deployed app |
| `id-dti-rag-drift` | `infra/shared` (Reader from each environment) | environment `drift` | **Reader** on all four resource groups; nothing else |

1. Set `github_repository: <owner>/<name>` and `registry.human_push_allowed: false` in
   `environments.yaml`. Apply `infra/shared`, then each environment. Your own registry roles
   go: from now on only the build identity builds and pushes.
2. **GitHub → Settings → Environments** (not in Terraform: it's GitHub, not Azure):

   | Environment | `AZURE_CLIENT_ID` from | Protection |
   |---|---|---|
   | `dev`, `test` | `terraform output deploy_identity_client_id` in `infra/dev`, `infra/test` | Deployment branch `main` only |
   | `prod` | the same, in `infra/prod` | **Required reviewers**; deployment branch `main` only |
   | `pr-eval`, `drift` | `terraform output environment_client_ids` in `infra/shared` | `drift`: branch `main` only |

   Repository variables (`AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `ACR_NAME`,
   `BUILD_CLIENT_ID`): `terraform output github_variables` in `infra/shared`.
3. **Authentication on test's and prod's apps** (portal, not Terraform: it creates an Entra
   app registration and a client secret for browser sign-in): the app → **Settings →
   Authentication** → Add identity provider → Microsoft → require authentication. Put each
   registration's Application ID URI in its GitHub environment as `APP_AUDIENCE`, so the
   deploy job can get a token for the smoke test and the gate.

**Deploy roles** (each in its own environment): Reader on the resource group; Contributor on
**the Container App and its environment only**, never the resource group; Foundry User;
Search Service Contributor + Search Index Data Contributor; **Storage Blob Data Reader on the
`audit` container**, for the gate's read-back.

**Two locks on prod.** A job only receives prod's client ID if it declares `environment:
prod`, and Azure only honours the token if it came from a job in that environment. A
workflow on a feature branch can get neither. Prod's GitHub environment has **required
reviewers** and deploys from `main` only.

**Why a separate drift identity?** The nightly check must read prod *without* waiting for
prod's reviewers, and must never be able to change anything. Federating the unprotected
`drift` environment to a *deploy* identity would hand an unreviewed job Contributor on the
prod app.

**A wrong `github_repository` fails silently.** The federated credentials save without
complaint, and the login fails later with an error that doesn't point at it. Check the
repository name, and each job's `environment:`, character by character, first.

---

## Part 4 — `scripts/check_env.py`

Terraform sees drift only when someone runs `plan`, and the pipeline can't run it: there's no
state in CI, and a deploy identity has Reader, not the rights a plan needs. `check_env` gives
the pipeline the same question with Reader alone: **does live Azure still match
`deploy/environments.yaml`?** It's the same file Terraform builds from, so the two can't
disagree about what an environment should be.

`environments.yaml` states what each environment **must** be:

- **Shared (must match everywhere):** region; each deployment's model, version, deployment
  type, upgrade policy and content filter; key access disabled on Foundry and Search; the
  semantic plan; storage shared-key and public access off.
- **Per environment (may differ):** TPM per deployment (and *which* deployments exist, so a
  `judge` in prod is drift); Search replicas; purge protection; the delete lock; min/max
  replicas; whether humans may hold data roles.
- **Roles:** the app identity has exactly its four roles and nothing forbidden
  (Contributor, Search Service Contributor, Search Index Data Contributor); **no human data
  roles in test or prod**; no identity from another environment holds anything here.
- **Config consistency:** every endpoint in `deploy/<env>.env` belongs to that environment,
  so it catches test's config pointing at dev's Search.

`check_env.py --env test` reads the live configuration through the management APIs (Reader is
enough), prints every difference and exits 1. `collect_live()` does the I/O and tolerates the
attribute moves between SDK generations; `compare()` and `check_config_file()` are pure and
unit-tested (`test_check_env.py`, including "remove Search Index Data Reader from test's app
identity"). A deploy identity can't see other environments by design, so cross-environment
checks it can't make are skipped there and made nightly by the drift identity.

---

## Part 5 — The pipeline

```
 pull request ─► ci.yml        lint · unit tests · chunk determinism · image allowlist    seconds, no Azure
             └─► pr-eval.yml   PR's code in-process vs a throwaway index on test's Search  blocks merge
                               (id-dti-rag-eval) · scorecard posted on the PR · index deleted

 merge to main ► deploy.yml
                  build ─ image built ONCE (skipped if it exists), digest recorded
                    │     chunks.jsonl built ONCE, uploaded as an artefact
                    ├─► dev    check_env · load index · deploy digest (--replace-env-vars) · smoke
                    ├─► test   check_env · load index · deploy digest · smoke
                    │          · PROMOTION GATE: the bank through the deployed API ─┐
                    └─► prod   ◄── you approve: commit, digest, test's scorecard ───┘
                               check_env · load index · deploy digest · smoke

 nightly ───────► drift.yml    check_env × 3 (id-dti-rag-drift, read-only) · sweep leaked PR indexes
```

`_deploy-env.yml` is one reusable workflow for all three environments, so dev, test and prod
really do run identical steps. Each deploy **replaces** the app's environment variables with
`deploy/<env>.env` (`--replace-env-vars`), so a variable deleted from the file disappears from
the app. **Make `ci / test` and `pr-eval / eval` required status checks** on `main` (repository
Settings → Branches), or the PR gate advises instead of blocks.

### Two gates, testing two different things

- **PR gate: is this *code* good?** In-process (`--target local`), on test's models and
  Search, against `dti-policy-pr-<n>` built from the PR's own chunks. Deleted afterwards;
  `drift.yml` sweeps any that leak (Basic has a small index limit).
- **Promotion gate: is this *deployment* good?** The same bank through test's **deployed**
  API. It catches what the PR gate structurally can't: a missing role on test's app identity,
  an environment variable pointing at the wrong thing, a file missing from the image.

Both compare against **`evaluation/baselines/reference-test.json`**, per metric (Lesson 10):
zero tolerance on `edition_correct`, abstention, ambiguity and unsupported figures. The first
time `pr-eval` runs there's no reference yet: it runs ungated, warns, and attaches its
scorecard. Commit that scorecard as the reference in a follow-up PR. From then on, updating
the reference is a deliberate, reviewed change.

**Make the prod approval informative.** The test job's summary shows the commit, the image
digest, the passed `check_env` and test's scorecard against the reference. An approval
screen that just says "deploy to prod?" gets approved without being read. *(Prod's own
`check_env` can't run in the test job, since test's identity can't see prod. It runs first
thing after approval, and stops the deploy if prod has drifted.)*

**Handle flakiness honestly.** Temperature 0 everywhere; tolerance only on LLM-judged
metrics. What you must never do is widen thresholds until the gate stops failing. That's a
gate decommissioned without anyone saying so.

### Promoting an infrastructure change

Infrastructure changes are promoted too: by you, one `terraform apply` per environment, in
order, with the pipeline checking your work. A new `chat` model version:

1. **dev:** on a branch, change the version in `environments.yaml`'s `shared` section; apply
   `infra/dev`; `make eval ENV=dev`.
2. **PR** with the YAML and the regenerated `deploy/dev.env`; merge.
3. The deploy passes dev, then **stops at test's `check_env`**: test is still on the old
   version. That's the pipeline telling you it's test's turn.
4. **test:** apply `infra/test`; re-run the job. The promotion gate now evaluates the new
   model through the deployed app. The reference scorecard won't be comparable (different
   model version), so regenerate and review it as part of the change.
5. **prod:** apply `infra/prod`, approve. Prod's `check_env` confirms prod matches.

So **prod can never run a configuration test didn't pass the gate with**: the YAML changes
once, and each environment's deploy is blocked until that environment has been applied.
That's why `check_env` blocks rather than warns.

### Rollback

- **App:** run `deploy.yml` manually with `ref` = the last good commit. Its image already
  exists (the build step skips), and its schema-versioned index still exists (Lesson 04).
  Break-glass: reactivate the previous revision in the portal, and record it, because prod no
  longer matches main.
- **Infrastructure:** revert the change to `environments.yaml` (or `infra/`), apply each
  environment, and run `check_env`.

### Prove it works

1. **Break retrieval** in a PR (remove the pre-filter, or break a date boundary). The PR gate
   must block it. If it doesn't, the gate is theatre.
2. **Break the deployment, not the code**: remove `!data/fact_matrix/editions_fact_matrix.csv`
   from `.dockerignore`. CI's checks and the PR gate pass (the file is in the repo), and the
   deployed app fails its smoke test in dev. It never reaches prod.
3. **Drift an environment**: remove Search Index Data Reader from test's app identity in the
   portal. The next `check_env` (nightly or pre-deploy) names exactly that role, and
   `terraform plan` in `infra/test` shows it being recreated. Put it back with `apply`.
4. **Prove isolation**: *Check access* for `id-dti-rag-deploy-test` on prod's resources shows
   nothing.

---

## Part 6 — The capstone

The demo runbook and the design document are in **`documentation/design/ARCHITECTURE.md`**:
nine cases, one per failure mode, demoed **live against prod**. Lead with case 1 twice:
baseline (£350, wrong), then the real pipeline (£300, cited). Case 5 (home emergency "before
2024 → Reserved") is the one an insurance audience remembers.

**The capstone package:** the deployed app and repo; the harness wired in as both gates;
`ARCHITECTURE.md` and the design records (`SCHEMA`, `FRAMEWORKS`, `GUARDRAILS`,
`OBSERVABILITY`); `deploy/environments.yaml` and `infra/`; the baseline comparison; the error-analysis log, wrong
hypotheses included.

**The design doc is the deliverable that travels.** The code shows you can build it; the doc
shows you know *why*: why metadata rather than better embeddings (with the score-gap
evidence); why section-aware chunking; why edition resolution is code; why the wording beats
the fact matrix (name the harm); what the system refuses to do; how you know test is a
faithful rehearsal of prod.

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `src/dti_rag/observability/__init__.py` | new | The package |
| `src/dti_rag/observability/telemetry.py` | new | Azure Monitor setup; stage spans; accumulated token counts |
| `src/dti_rag/observability/audit.py` | new | Build (redacted), write and read audit records |
| `src/dti_rag/pipeline.py` | changed | A span per stage with attributes |
| `src/dti_rag/api/app.py` | changed | Telemetry at startup; trace IDs; audit write; fail closed (503) |
| `src/dti_rag/generation/generate.py`, `query/extract.py` | changed | Token usage recorded on spans |
| `evaluation/run_eval.py` | changed | API target reads context back from the audit log |
| `scripts/check_env.py` | new | Live configuration vs `environments.yaml` |
| `scripts/sweep_pr_indexes.py` | new | Delete PR-gate indexes on test |
| `.github/workflows/ci.yml` | new | Offline checks |
| `.github/workflows/pr-eval.yml` | new | The PR gate |
| `.github/workflows/deploy.yml` | new | Build once; dev → test → prod |
| `.github/workflows/_deploy-env.yml` | new | One environment's deploy, shared by all three |
| `.github/workflows/drift.yml` | new | Nightly drift check and PR-index sweep |
| `tests/unit/test_check_env.py` | new | Drift detection, offline |
| `tests/unit/test_audit.py` | new | Audit record contents; redaction; token accumulation |
| `tests/unit/test_api.py` | changed | Every answer audited; no audit → 503 |
| `documentation/design/ARCHITECTURE.md` | new | The capstone design doc and demo runbook |
| `documentation/design/OBSERVABILITY.md` | new | Spans, KQL for the workbook, alerts |
| `pyproject.toml` | changed | `observability` extra; the `ops` extra gains the management SDKs |

`deploy/test.env` and `deploy/prod.env` aren't in the list: `terraform apply` writes them.
You also edit `deploy/environments.yaml` (Parts 2 and 3). The locks client comes from
`azure-mgmt-resource-locks`, currently a beta package, pulled in by the `ops` extra.

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
│   ├── environments.yaml
│   ├── prod.env  ◇ generated
│   └── test.env  ◇ generated
├── documentation/
│   ├── design/
│   │   ├── ARCHITECTURE.md  ★ new
│   │   ├── baseline_failures.md
│   │   ├── corpus_map.md
│   │   ├── error_analysis_log.md
│   │   ├── FRAMEWORKS.md
│   │   ├── GUARDRAILS.md
│   │   ├── OBSERVABILITY.md  ★ new
│   │   └── SCHEMA.md
│   └── lessons/  (this course)
├── evaluation/
│   ├── baselines/
│   │   ├── naive-baseline-dev.json  ◇ generated
│   │   ├── reference-dev.json  ◇ generated
│   │   └── reference-test.json  ◇ generated
│   ├── __init__.py
│   ├── checks.py
│   ├── compare.py
│   ├── evaluators.py
│   ├── judge.py
│   ├── qa_bank.py
│   ├── rows.py
│   ├── run_baseline.py
│   ├── run_eval.py  ✎ changed
│   ├── runmeta.py
│   ├── scorecard.py
│   └── targets.py
├── .github/
│   └── workflows/
│       ├── _deploy-env.yml  ★ new
│       ├── ci.yml  ★ new
│       ├── deploy.yml  ★ new
│       ├── drift.yml  ★ new
│       └── pr-eval.yml  ★ new
├── infra/  (Terraform: modules/environment, shared, dev, test, prod)
├── scripts/
│   ├── experiments/
│   │   └── integrated_vectorization.py
│   ├── ask.py
│   ├── build_corpus_map.py
│   ├── check_env.py  ★ new
│   ├── compare_filters.py
│   ├── measure_retrieval.py
│   ├── smoke_api.py
│   ├── smoke_test.py
│   └── sweep_pr_indexes.py  ★ new
├── src/
│   └── dti_rag/
│       ├── api/
│       │   ├── static/
│       │   │   └── index.html
│       │   ├── __init__.py
│       │   ├── app.py  ✎ changed
│       │   └── schemas.py
│       ├── generation/
│       │   ├── __init__.py
│       │   ├── arithmetic.py
│       │   ├── compare.py
│       │   ├── crossref.py
│       │   ├── generate.py  ✎ changed
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
│       ├── observability/
│       │   ├── __init__.py  ★ new
│       │   ├── audit.py  ★ new
│       │   └── telemetry.py  ★ new
│       ├── orchestration/
│       │   ├── __init__.py
│       │   ├── graph.py
│       │   └── llamaindex_retriever.py
│       ├── query/
│       │   ├── __init__.py
│       │   ├── editions.py
│       │   ├── extract.py  ✎ changed
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
│       ├── test_api.py  ✎ changed
│       ├── test_audit.py  ★ new
│       ├── test_check_env.py  ★ new
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
├── Dockerfile
├── .dockerignore
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
| Conflating traces with the audit log | Sampled traces are useless for audit |
| No prompt version in the audit record | "Why did it say that?" is unanswerable |
| Returning answers when the audit write fails | Unauditable answers in production |
| Gating on an aggregate score | A regression hides behind a win |
| Widening thresholds until CI passes | The gate decommissioned in silence |
| PR gate not a required check | It advises instead of blocking |
| Stored service-principal secret in Actions | The credential risk you avoided everywhere else |
| Wrong `github_repository`, or a job's `environment:` misspelt | Login fails with an error that doesn't point at it |
| Deploy identity with Contributor on the whole resource group | A workflow bug can change anything there |
| PR gate running as a deploy identity | Unreviewed code with rights over a deployed app |
| Drift check using a deploy identity | Waits for prod approval nightly, or holds write access it shouldn't |
| `check_env` that warns instead of blocking | Prod runs configuration test never passed |
| Rebuilding the image per environment | Test and prod ran different builds of one commit |
| Env vars merged, not replaced | Deleted settings linger in the app |
| An approval showing no evidence | Approved without being read |
| Leaked PR indexes | The Basic index limit fails unrelated PRs |
| One App Insights for several environments | Test traffic in prod's signal |
| Doing something by hand while building test or prod | The code no longer describes your environments, and a rebuild won't match |
| Fixing prod in the portal "just this once" | Drift the next deploy blocks on, or the next apply silently reverts |

## Done when

All nine demo cases pass live **against prod**, **and**:

- test and prod were built by `terraform apply` alone, and `terraform plan` in every
  `infra/` folder says **No changes**
- a commit that breaks retrieval is blocked by the PR gate
- a change that breaks the *deployment* is stopped before prod
- a drifted setting in test is reported by `check_env`
- the test deploy identity has no access to anything in prod
- every prod answer has an audit record you can read back by its `trace_id`

## Check yourself

1. Why are traces and the audit log different artefacts?
2. Why does `/chat` fail closed when the audit write fails? What does that cost?
3. Why gate per metric, and which metrics have zero tolerance?
4. How do you know your gate isn't theatre?
5. Why does the PR gate run in-process while the promotion gate goes through the API?
6. What stops a feature-branch workflow getting a token for prod? Name both locks.
7. Why does the nightly drift check have its own identity?
8. Walk through exactly how a new `chat` model version reaches prod, and what stops it
   reaching prod without passing the gate in test.
9. Why does `check_env` block the deploy rather than warn?

---

## You've finished

Look back at Lesson 02's claim: on this corpus **the metadata schema is the product**. If you
built this properly, the biggest wins came from the schema, the chunking and the filters,
and the model, the framework and the prompt mattered far less than they seemed to at the
start. That inversion is the transferable lesson, and it holds well beyond insurance.
