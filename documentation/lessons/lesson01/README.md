# Lesson 01 — Build dev with Terraform, design for test and prod, prove the dev loop

**Objective:** describe all three environments in one file, build **dev** from it with Terraform, and prove you can call a chat model and an embedding model from Python with no API keys anywhere.

**Deliverables:**

- `deploy/environments.yaml`: what dev, test and prod must be, in one file
- `infra/`: the Terraform that builds any environment from it; `infra/shared` and `infra/dev` applied
- `deploy/dev.env`: dev's configuration, written by `terraform apply` and committed
- the Python project: `pyproject.toml`, `Makefile`, `config.py`, `clients.py`
- `scripts/smoke_test.py`, passing: `make smoke ENV=dev`

---

## Why this lesson is boring, and why you should still do it properly

Everything after this assumes a working dev loop. If authentication is flaky, or you're not sure which deployment you're hitting, every later failure has two possible causes.

**The auth decisions you make here are the ones you'll ship.** Teams that start with API keys "just to get going" ship API keys. Start with `DefaultAzureCredential`, and the move to managed identity in Lesson 12 is one setting, not a refactor.

**The environment boundaries you draw here are the ones you'll ship.** A team that starts with one resource group and plans to "split out prod later" ends up with a hand-built prod, a test that doesn't match it, and an eval gate that proves nothing. Designing three environments now costs one YAML file and one Terraform module.

---

## The environment model

Three environments, one codebase, one rule:

> **Isolation is enforced by identity and scope, not by naming and good intentions.** The pipeline identity that deploys test has no role in prod. It can't break prod, however badly a workflow is written.

| | **dev** | **test** | **prod** |
|---|---|---|---|
| Purpose | Your inner loop | Rehearsal for prod; the eval gates run here | Claims handlers use it |
| Who changes infrastructure | You, freely | You, applying a change already applied to dev | You, after it passed in test |
| Who deploys code | You or the pipeline | Pipeline only | Pipeline only, after approval |
| Your data-plane access | Yes | No | No |
| Infrastructure applied in | This lesson | Lesson 13 | Lesson 13 |

What **must not** differ matters as much as what may. The rule: **anything that changes behaviour must match between test and prod, or the gate is testing a different system.**

Only capacity, access and protection may differ. `deploy/environments.yaml` is laid out that way: a `shared` section (region, models and versions, deployment types, content filter, semantic plan, API versions, key access off) that every environment gets, and an `environments` section with only what may differ (TPM, replicas, retention, locks, purge protection, whether you hold data roles).

### Infrastructure is code, configuration is generated, code is promoted

Infrastructure has one structural weakness: **drift.** Test and prod quietly diverge, one setting at a time. The defences, each introduced when needed:

1. **`deploy/environments.yaml`** (this lesson). The one statement of what each environment must be. You edit it; nothing else is hand-maintained.
2. **`infra/`** (this lesson). Terraform reads the YAML and builds an environment from it. `terraform plan` compares live Azure with it and lists every difference.
3. **`deploy/<env>.env`** (this lesson). Endpoints, deployment names and API versions for the app. **Terraform writes it** on every apply, because it knows every value. The Python code reads it locally; the pipeline pushes it to the running app. You commit it.
4. **`scripts/check_env.py`** (Lesson 13). Before every deploy, the pipeline reads live Azure with Reader only and compares it with the same YAML. An environment you haven't applied yet, or one someone changed in the portal, stops the deploy.

### One subscription, four resource groups

Real organisations put prod in its own subscription. This course uses **one subscription with one resource group per environment**, plus `rg-dti-rag-shared` for the container registry and pipeline identities. Know what that costs:

- **Model quota is shared.** TPM quota is per subscription, region, model and deployment type. dev + test + prod must fit in one allowance.
- **You're Owner of prod**, because you run Terraform against it from your laptop. Real firms use just-in-time elevation (PIM) and apply from a pipeline. Here, the substitutes are the prod delete lock and holding no data-plane roles in test or prod.

### Cost

A Basic search unit costs roughly £50 a month and bills whether you query it or not. Three environments with prod on two replicas is four units, about £220 a month before a single token. So: **apply shared and dev now; test and prod are one command each in Lesson 13**, and `terraform destroy` removes them when the capstone is done. Everything else in dev costs little while idle: the registry (Basic, a few pounds a month), Log Analytics by volume, and the Container Apps environment nothing until an app runs in it.

---

## Build dev with Terraform

### What's in `infra/`

```text
deploy/
└── environments.yaml        what every environment must be: the file you edit
infra/
├── modules/environment/     ONE environment, built from its entry in environments.yaml
│   ├── main.tf              resource group, lock, Log Analytics, App Insights, Key Vault, budget
│   ├── storage.tf           storage account, containers, audit retention
│   ├── foundry.tf           Foundry resource and project; chat, embed (and judge) deployments
│   ├── search.tf            AI Search
│   ├── app.tf               the app's identity, Container Apps environment, Container App
│   ├── roles.tf             every role assignment, and the deploy identity
│   ├── config.tf            writes deploy/<env>.env
│   └── variables.tf, versions.tf, outputs.tf
├── shared/main.tf           rg-dti-rag-shared: registry, pipeline identities, audit policies
├── dev/  test/  prod/       main.tf: which entry to build; each folder holds its own state
└── README.md                how to apply, what isn't in Terraform, known gaps
```

**Why a YAML file, not Terraform variables?** Lesson 13's `check_env` needs the same values to check each environment before a deploy, and it runs with Reader only, where Terraform's state isn't available. With one file, the thing that builds an environment and the thing that checks it can't disagree.

**Why a folder per environment**, rather than workspaces: each folder has its own state, so `terraform apply` in `infra/dev` can't touch prod whatever you type. Workspaces pick the target from hidden state, the same "which environment am I in?" failure that `make smoke` refuses to allow by having no default `ENV`. The three `main.tf` files differ only in the environment's name.

### What gets deployed, and why

Everything the project will ever need is in the code now, so any environment can be built in one apply. The "Used from" column says when each piece starts to matter.

Per environment (`infra/<env>`). Names are dev's; test and prod swap the environment name.

| Resource | Name | Why it exists | Used from |
|---|---|---|---|
| Resource group | `rg-dti-rag-dev` | The environment's boundary. Budgets, locks and role scopes attach to it | 01 |
| Log Analytics workspace | `log-dti-rag-dev` | Where App Insights and the Container App's logs are stored | 01 |
| Application Insights | `appi-dti-rag-dev` | One trace per question: retrieval, model calls, latency. Never shared between environments | 13 |
| Storage account | `stdtiragdev` | `corpus` container for Lesson 04's indexer experiment (dev only); `audit` container for one redacted record per answer. Key access **off**; versioning and soft delete on; a lifecycle rule deletes `audit/` blobs **and their old versions** after the retention period | 04, 13 |
| Key Vault | `kv-dtirag-dev` | Nothing needs it, because there are no keys. It's where the first secret you can't avoid goes, instead of a GitHub secret. Purge protection on in prod (irreversible) | — |
| Foundry resource | `ai-dti-rag-dev` | Hosts the model deployments; its endpoints are what the app calls. Kind `AIServices` with project management on (a *Foundry* resource, not an *Azure AI hub*); **key access off** | 01 |
| Foundry project | `dti-rag` | Foundry features (Content Safety) hang off a project | 11 |
| `chat` deployment | `chat` | Routing and answer generation. Pinned version, **no auto-upgrade**, default content filter | 01 |
| `embed` deployment | `embed` | Embeds chunks and query text. `text-embedding-3-large` v1: 3072 dimensions, which the smoke test asserts | 01 |
| `judge` deployment | `judge` | Grades answers in the eval harness. dev and test only, **never prod**. Created once you choose its model | 10 |
| AI Search | `srch-dti-rag-dev` | The index, with hybrid and semantic retrieval. Basic; **RBAC only**; semantic ranker Standard; system identity on; 2 replicas in prod | 04 |
| App identity | `id-dti-rag-app-dev` | What the running app calls Azure as. User-assigned, so its roles exist before the first revision pulls an image | 12 |
| Container Apps environment | `cae-dti-rag-dev` | Where the app runs; logs to the workspace above | 12 |
| Container App | `ca-dti-rag-dev` | The app. Created once `app_image` names an image; after that the pipeline owns the image and its environment variables | 12 |
| Deploy identity | `id-dti-rag-deploy-dev` (in `rg-dti-rag-shared`) | What the pipeline deploys to this environment as, and nothing else | 13 |
| Budget | `budget-dti-rag-dev` | A runaway loop becomes an email, not a bill. Alerts at 50%, 80% and 100% actual, and 100% forecast | 01 |
| Delete lock | `do-not-delete` | Nobody deletes prod by accident, including with `terraform destroy`. prod only | 13 |

Role assignments (`roles.tf`), each scoped to one resource, never the resource group:

| Who | Roles | On | Why |
|---|---|---|---|
| Search's identity | Cognitive Services OpenAI User | Foundry | The index's vectorizer embeds query text as Search |
| Search's identity | Storage Blob Data Reader | Storage | Lesson 04's indexer reads `corpus`. dev only |
| You | Foundry User; Search Service Contributor; Search Index Data Contributor; Storage Blob Data Contributor | Each resource | Owner has no data actions. **dev only** (`human_data_roles_allowed`) |
| App identity | AcrPull; Foundry User; **Search Index Data Reader**; Storage Blob Data Contributor | Registry; Foundry; Search; the `audit` container only | Exactly what the app does, and nothing it doesn't. Reader on Search: the app never writes |
| Deploy identity | Reader; Contributor; Foundry User; Search Service + Index Data Contributor; Storage Blob Data Reader | Resource group and shared group; the Container App and its environment only; Foundry; Search; `audit` | Check the environment, deploy a revision, load the index, read the audit log back |
| Drift identity | Reader | Resource group | The nightly check reads every environment and can change nothing |
| Eval identity | Search Service + Index Data Contributor; Foundry User; Reader | test's Search and Foundry | The PR gate's throwaway indexes. test only (`pr_eval`) |

Once (`infra/shared`):

| Resource | Why it exists | Used from |
|---|---|---|
| `rg-dti-rag-shared` and its budget | Holds what serves every environment | 01 |
| Container registry `crdtirag` | One image per commit, promoted by digest through every environment. Admin user off; accepts managed-identity pulls | 12 |
| Your AcrPush and Container Registry Tasks Contributor on the registry | You build dev images by hand in Lesson 12 (`az acr build` runs an ACR Task, which pushes). Off in Lesson 13 (`human_push_allowed`) | 12 |
| `id-dti-rag-build`, `-eval`, `-drift` | Pipeline identities, each trusted by one kind of GitHub job through a federated credential, once `github_repository` is set. No secrets | 13 |
| `Microsoft.App` resource provider registration | Container Apps can't be created in a subscription until it's registered, and the azurerm provider doesn't register it itself | 01 |
| Three Azure Policy assignments, effect **Audit** | Independent evidence that key access stays off on AI Services, Search and Storage, including on anything built outside Terraform | 01 |

### Naming

The environment is in every resource name: `ai-dti-rag-dev`, `srch-dti-rag-dev`, `stdtiragdev`. The smoke test then refuses to run when the configuration says `dev` but an endpoint says `test`. Storage, Search, Key Vault, Foundry and registry names are unique across all of Azure, so if one is taken, `apply` fails: change it in `environments.yaml`.

**Name deployments by role**: `chat`, `embed`, `judge`. Never `gpt-4o`. The model vs deployment-name distinction then can't be missed, and a model upgrade doesn't rename anything.

### Running it

```bash
az login                                  # Terraform authenticates as your az login

cd infra/shared
terraform init
terraform plan -out=tfplan                # read it
terraform apply tfplan

cd ../dev
terraform init
terraform plan -out=tfplan                # read it
terraform apply tfplan                    # also writes deploy/dev.env

cd ../.. && git add deploy/dev.env infra/*/.terraform.lock.hcl
```

- **`shared` first.** Each environment looks up the registry and the pipeline identities it creates.
- **Plan to a file, apply that file.** You apply exactly what you reviewed.
- **Read the plan.** `+` create and `~` update in place are expected. **`-/+` replace or `-` destroy on something that holds data means stop and find out why.** Replacing the Foundry resource deletes its deployments; replacing Search deletes the index.
- **Never commit `terraform.tfstate`** (it's git-ignored). It's a local file in each folder: lose it and Terraform no longer knows it owns anything. A shared backend is a known gap (`infra/README.md`).
- **The subscription comes from `environments.yaml`**, not from `az account set`, for the same reason `deploy/dev.env` beats your shell.

The first dev apply takes 10–15 minutes, most of it the Search service and the Container Apps environment.

### Starting from a subscription you've used before

If you built any of this by hand before, delete it first (including the resource groups and any budgets): Terraform creates resources, and stops with "already exists" at anything that's there. Then:

- **Purge the deleted Foundry resources.** A deleted Foundry resource is kept for 48 days and holds its name. `az cognitiveservices account list-deleted -o table` lists them; `az cognitiveservices account purge --location uksouth --resource-group <rg> --name <name>` frees each one.
- A deleted Key Vault holds its name too (90 days if it had purge protection, which can't be purged). Only a problem if it had the same name as one here.


### The decisions that bite

| Where | Decision | Why |
|---|---|---|
| `shared.storage_shared_key_access: false` | **Key access off** | Nothing, including the portal's storage browser, can use a key. You need a data role to upload. Terraform itself works through the management plane (`data_plane_available = false`), so it needs none |
| `purge_protection` | Off in dev, **on** in prod | It can never be turned off. That's the point in prod and a nuisance in dev |
| `foundry.tf` | `kind = "AIServices"` with project management | That's a Foundry resource. `azurerm_ai_foundry` is the older *Azure AI hub*: the wrong resource |
| `shared.foundry_local_auth_disabled: true` | Key access off on Foundry | The one setting the portal can't make, so the one most likely to be forgotten by hand. In code it can't be, and the audit policy checks it anyway |
| `shared.deployments` | Pin the version; **no auto-upgrade** | A pinned deployment never changes under you, and stops working when its version retires. The retirement date is your deadline |
| `shared.deployments.chat` | A model that **accepts `temperature=0`** | Every call in this project uses it for reproducibility. Some reasoning models reject it; the smoke test fails fast if yours does |
| `shared.deployments.*.sku` | Deployment type (Global Standard / Data Zone Standard / Standard) | A data-residency decision. `chat` and `embed` are both Standard, in UK South. `chat` is `gpt-4.1-mini` because it has regional Standard quota in UK South; `gpt-4.1` has none there, and new subscriptions often have no Global Standard quota for it either. Claims context goes to `chat`, so its type is the one compliance would ask about. In a regulated firm compliance owns it. Write down what you'd ask them |
| `foundry.tf` | Deployments one at a time | The service rejects concurrent deployment changes on one Foundry resource with a 409 |
| `search.tf` | Tier **Basic**, **RBAC only** | The portal's default is *API keys only*, which rejects valid role assignments with 401/403. Free tier: one per subscription, and no managed identity for indexers |
| `shared.semantic_ranker: standard` | Even in dev | The free plan's allowance runs out mid-eval and looks like a retrieval bug |
| `roles.tf` | **Foundry User** for you, not *Cognitive Services OpenAI User* | Foundry User also covers Content Safety (Lesson 11) and project features; Microsoft's Foundry guidance says to use it |
| `roles.tf` | Wait 5–10 minutes after the first apply | `apply` finishes when an assignment exists; Azure takes minutes to honour it. A 403 straight afterwards means "wait", not "debug" |
| `budget` | One per resource group | A runaway loop in Lesson 05 is real. The TPM cap turns it into a rate-limit error, and the budget alert tells you the cap was too high |
| `shared/main.tf` | Policy effect **Audit**, not Deny | Terraform already turns key access off. Audit reports anything that slips through, without blocking an emergency fix |

**Size TPM by arithmetic, not by feel.** Embedding the corpus is ~270 chunks of a few hundred tokens: 50K TPM finishes in a minute. A full eval run is 25 questions × up to seven model calls × a few thousand tokens; size test's `chat` so it finishes in minutes.

---

## Configuration and authentication

### `deploy/dev.env`

**Written by `terraform apply` in `infra/dev`. Don't edit it**: change `environments.yaml`, apply, and commit the result. It holds every setting the project will ever read, including ones later lessons use (the judge deployment, the app identity's client ID). It holds nothing secret because there are no keys. The App Insights connection string is an ingestion key rather than a credential (it can send telemetry, not read it); check what your secret scanner makes of it.

Why keep a file at all, when Terraform knows the values? Because the Python code, locally and in the pipeline, needs them without Terraform's state. The file is how the values leave Terraform.

### `src/dti_rag/config.py`

`Settings` (pydantic-settings) with `app_env` required and **no default for any endpoint**. A missing value fails at startup instead of quietly pointing at a default.

- Locally, `get_settings()` reads `deploy/<APP_ENV>.env`. In Azure there is no file, and the same values arrive as environment variables.
- **The committed file beats your shell.** A stale `export AZURE_OPENAI_ENDPOINT=…` can't point you at another environment.
- A blank value means "not set". Code that needs an optional setting calls `settings.require("azure_openai_judge_deployment")`, which fails naming the variable.
- The file's `APP_ENV` must match the one you asked for, so `test.env` can't be loaded as dev.

### `src/dti_rag/clients.py`

Every Azure client comes from here. **`AzureOpenAI` gets a token *provider*, not a token.** Pass a token string and it works for an hour, then fails in a way that's confusing to debug. The client also counts 429 responses, which the eval harness records (Lesson 10).

> **Why `AzureOpenAI` with a pinned `api_version`, not the newer `/openai/v1` endpoint?** Both work. This course pins the data-plane API version explicitly and identically in every environment, and LlamaIndex and LangChain (Lesson 09) take the same `azure_endpoint` + `api_version` pair. If you move to the v1 endpoint later, move every environment together.

---

## The dev loop

```bash
make setup                 # uv sync (Python 3.12, .venv, uv.lock) + pre-commit (with a secret scanner)
make test                  # offline unit tests
az login
make smoke ENV=dev         # the deliverable
```

`ENV` has **no default**. Every Azure-touching target fails without it.

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (`brew install uv` on a Mac). `uv sync` reads `.python-version` and fetches Python 3.12 if you don't have it, creates `.venv`, and records every resolved version in `uv.lock`. **Commit `uv.lock`**: the image (Lesson 12) and the pipeline (Lesson 13) install exactly what it pins. There's nothing to activate. Every `make` target runs through `uv run`, which brings `.venv` up to date first, so when a later lesson adds a dependency the next command installs it. To run anything else in the environment, prefix it: `uv run pytest -x`.

### `scripts/smoke_test.py`

1. **Prints the environment and endpoint hostnames, and asserts every hostname contains the environment name.** "I thought I was on dev" is caught before it costs anything.
2. Embeds a sentence with `embed` and **asserts** the vector length is 3072. This catches "pointed at the wrong deployment" now, instead of as an index-dimension mismatch in Lesson 04.
3. Gets a one-line completion from `chat` **at temperature 0**.
4. Retries 401/403 for up to five minutes, because straight after role assignments, propagation is the likeliest cause.

Nothing in it assumes dev: Lesson 13's pipeline runs it against test and prod.

---

## Files in this lesson

| File | New / changed | Purpose |
|---|---|---|
| `deploy/environments.yaml` | new | What every environment must be; read by Terraform and (Lesson 13) `check_env` |
| `infra/modules/environment/*.tf` | new | One environment's resources and roles, and its `deploy/<env>.env` |
| `infra/shared/main.tf` | new | Shared resource group, registry, pipeline identities, audit policies |
| `infra/{dev,test,prod}/main.tf` | new | Which environment each folder builds; provider settings |
| `infra/README.md` | new | Applying, changing and tearing down; what isn't in Terraform; known gaps |
| `infra/.gitignore` | new | Keeps state and `.terraform/` out of git |
| `pyproject.toml` | new | Package, dependencies (core + a `dev` group for your tools), pytest and ruff config |
| `Makefile` | new | `setup`, `test`, `lint`, `smoke`; `ENV` required for anything touching Azure |
| `.pre-commit-config.yaml` | new | Ruff + gitleaks secret scanner |
| `.python-version` | new | 3.12 |
| `src/dti_rag/__init__.py` | new | The package |
| `src/dti_rag/config.py` | new | Settings: one environment's configuration, no defaults for endpoints |
| `src/dti_rag/clients.py` | new | Credential and OpenAI client factories |
| `src/dti_rag/constants.py` | new | `EMBED_DIMENSIONS = 3072`: the same everywhere, so code not config |
| `scripts/smoke_test.py` | new | The deliverable |
| `tests/unit/test_config.py` | new | No default environment; file beats shell; blank means unset |

`deploy/dev.env` and `uv.lock` aren't in the list: `terraform apply` writes the first and `make setup` the second. Commit both.

## Project structure at the end of this lesson

```text
DTI-Policy-Helper/
├── data/
│   ├── fact_matrix/  (editions_fact_matrix.csv, fact_lookup_long.csv: convenience data)
│   ├── policy_documents/  (the 5 policy wording PDFs: authoritative)
│   └── question_answers/  (dti_rag_qa_bank.jsonl and .csv, README.md: ground truth for scoring)
├── deploy/
│   ├── dev.env  ◇ generated
│   └── environments.yaml  ★ new
├── documentation/
│   └── lessons/  (this course)
├── infra/
│   ├── dev/
│   │   ├── .terraform.lock.hcl  ◇ generated
│   │   ├── main.tf  ★ new
│   │   └── terraform.tfstate  ◇ generated
│   ├── modules/
│   │   └── environment/  ★ new  (app, config, foundry, main, outputs, roles, search, storage, variables, versions)
│   ├── prod/
│   │   └── main.tf  ★ new
│   ├── shared/
│   │   ├── .terraform.lock.hcl  ◇ generated
│   │   ├── main.tf  ★ new
│   │   └── terraform.tfstate  ◇ generated
│   ├── test/
│   │   └── main.tf  ★ new
│   ├── .gitignore  ★ new
│   └── README.md  ★ new
├── scripts/
│   └── smoke_test.py  ★ new
├── src/
│   └── dti_rag/
│       ├── __init__.py  ★ new
│       ├── clients.py  ★ new
│       ├── config.py  ★ new
│       └── constants.py  ★ new
├── tests/
│   └── unit/
│       └── test_config.py  ★ new
├── .gitignore
├── Makefile  ★ new
├── .pre-commit-config.yaml  ★ new
├── pyproject.toml  ★ new
├── .python-version  ★ new
├── README.md
└── uv.lock  ◇ generated
```

`★ new` in this lesson · `✎ changed` in this lesson · `◇ generated` by running the code (git-ignored or produced by you) · unmarked: unchanged from earlier lessons

---

## Pitfalls

| Symptom | Actual cause |
|---|---|
| `DeploymentNotFound` | Model name used where the deployment name is wanted |
| 401/403 on the first call | Role not propagated yet. Wait |
| 403 calling the model as subscription Owner | Owner has no data actions; you need *Foundry User*, which `human_data_roles_allowed: true` gives you in dev |
| Works, then fails an hour later | A token string was passed instead of a token provider |
| `temperature` rejected by the chat model | A reasoning model. Pick a model that accepts it, and record why |
| Project features missing, SDK errors about hubs | The resource is an *Azure AI hub* (`azurerm_ai_foundry`), not a *Foundry* resource |
| Can't upload to the storage container in the portal | Key access is off and you have no Storage Blob Data role |
| `plan` in `infra/dev` fails: identity or registry not found | `infra/shared` hasn't been applied |
| `apply` fails on a deployment: `InsufficientQuota` | dev + test + prod TPM exceeds the shared regional quota for that model and deployment type. If the error says the quota limit is 0, the subscription has none for that model: request it (Foundry portal, Quota) or choose a model you have quota for (`az cognitiveservices usage list --location uksouth`) |
| `apply` fails on a deployment: 409 `RequestConflict` | Another change to the same Foundry resource is still running. Run `apply` again |
| `apply` fails: name already in use | A soft-deleted Foundry resource or Key Vault holds it (purge it), or someone else in Azure has it (rename in `environments.yaml`) |
| `apply` fails: resource already exists | Something built by hand is still there. Delete it, or `terraform import` it |
| `apply` fails creating a role assignment: `AuthorizationFailed` | Creating role assignments needs Owner or User Access Administrator |
| The plan wants to create everything that already exists | You're in the wrong folder, or the state file is gone |
| You edited `deploy/dev.env` and it changed back | It's generated. Change `environments.yaml` and apply |
| `make smoke` runs against the wrong environment | It can't: `ENV` is required, and the hostnames are asserted |

## Done when

- `terraform plan` in `infra/shared` and in `infra/dev` both say **No changes**.
- `deploy/dev.env`, `deploy/environments.yaml`, `infra/` and the lock files are committed; no state file is.
- `make smoke ENV=dev` passes: both calls work through `DefaultAzureCredential`, with no key in code, in `deploy/dev.env` or on the Foundry resource. The embedding length is asserted.
- `make test` passes (11 tests).
- Policy → Compliance shows dev compliant.

## Check yourself

1. Why does `AzureOpenAI` want a token *provider* rather than a token?
2. The app's identity gets **Search Index Data Reader**. Why not the Contributor roles you gave yourself?
3. What would have to be true for `text-embedding-3-small` to be the right choice?
4. You get a 403 thirty seconds after `terraform apply` finished. What do you do?
5. Why is the model version in `shared` while TPM is per environment?
6. The plan for prod says `-/+` on the Search service. What do you lose if you apply it, and what do you do instead?
7. Why does the committed `deploy/dev.env` win over a variable exported in your shell, and why is it generated rather than written by hand?
8. What stops the pipeline identity for test from changing anything in prod?

---

**Next:** [Lesson 02 — Read the corpus like an adversary](../lesson02/README.md)
