# Lesson 01 — Build dev in the Azure portal, design for test and prod, and prove the dev loop

**Objective:** stand up the **dev** environment through the Azure portal, following a design
that test and prod will copy exactly, and confirm you can call a chat model and an embedding
model from Python with no API keys anywhere.

**Deliverables:**

- The dev environment, built in the portal using the settings in this lesson
- `Documentation/design/ENVIRONMENTS.md`: your runbook. Every setting you chose, per
  environment, plus a change log
- `deploy/dev.env`: dev's non-secret configuration, committed
- `scripts/smoke_test.py`, passing against dev

> Portal steps were checked against Microsoft's docs on 19 September 2026. Portal labels move
> around. If a blade has been renamed, the setting still exists, so search for it in the
> resource's left menu.

---

## Why this lesson is boring and why you should still do it properly

Everything after this assumes a working dev loop. If authentication is flaky, or you're not
sure whether you're hitting the right deployment, every later failure has two possible
causes and you'll waste time on the wrong one. Spend the hour.

The second reason is that **the auth decisions you make here are the ones you'll ship.** Teams that
start with API keys "just to get going" ship API keys. Start with
`DefaultAzureCredential` and the move to managed identity in Lesson 12 is a config
change, not a refactor.

The third reason is that **the environment boundaries you draw here are the ones you'll ship.** A
team that starts with one resource group and plans to "split out prod later" ends up with a
hand-built prod, a test that doesn't match it, and an eval gate that proves nothing about
either. Designing for three environments from day one costs a naming convention and a
table. Retrofitting them is a migration.

---

## The environment model

Three environments, one codebase, and one rule:

> **Isolation is enforced by identity and scope, not by naming and good intentions.** The
> pipeline identity that deploys test has no role assignments in prod. It can't break prod,
> however badly a workflow is written.

| | **dev** | **test** | **prod** |
|---|---|---|---|
| Purpose | Your inner loop. Break it freely | Rehearsal for prod. The eval gate runs here | Claims handlers use it |
| Who changes infrastructure (portal) | You, freely | You, only by replaying a change already made and recorded in dev | You, only after the change has passed in test |
| Who deploys application code | You, or the pipeline | Pipeline only | Pipeline only, after a human approves |
| Your data-plane access (call models, read/write indexes) | Yes | No | No |
| Index loaded by | You (`make index ENV=dev`) | The pipeline | The pipeline |
| Search replicas | 1 | 1 | **2** (read SLA) |
| Model TPM | Low: runaway-loop insurance | Enough for eval runs | Sized for real load |
| Judge model (Lesson 10) | Yes | Yes | No |
| Key Vault purge protection | Off, 7-day retention | Off, 7-day retention | **On** (can never be turned off) |
| Delete lock on the resource group | No | No | **Yes** |
| Log retention | Short | Short | Aligned to complaint-handling timeframes (Lesson 13) |
| Data | Synthetic only | Synthetic only | Real claims context, redacted (Lesson 11) |
| Built in | This lesson | Lesson 13 | Lesson 13 |

What **must not** differ matters just as much:

| Same in every environment | Because |
|---|---|
| Region | Model and feature availability varies by region |
| Model names **and versions** | A different model version in test makes the eval gate meaningless |
| Deployment names (`chat`, `embed`) | Config then differs only in endpoints, never in names |
| Deployment type (Global Standard / Data Zone Standard / Standard) | Data residency is a policy decision, not an environment setting |
| Content filter on the deployments | A stricter filter in prod can block an answer test passed |
| Semantic ranker plan (Standard) | A free-plan allowance running out in test looks like a pipeline failure |
| Search and OpenAI API versions | Behaviour changes with API version |
| Auth mode: Entra ID only, keys disabled | "Keys in dev only" is how keys reach prod |
| Index schema | Defined in code (Lesson 4) and applied identically everywhere |

The rule behind the second table: **anything that changes behaviour must match between test
and prod, or the gate is testing a different system.** Only capacity, access and protection
may differ.

### Infrastructure is clicked, configuration is committed, code is promoted

Building in the portal has one structural weakness: **drift.** Nothing stops test and prod
from quietly diverging, one forgotten checkbox at a time, and nothing tells you when they
have. Three defences, each introduced when it's needed:

1. **`Documentation/design/ENVIRONMENTS.md`: the runbook** (this lesson). Every portal
   setting, per environment, written down *before* you click it for test and prod, with a
   change log. Lesson 13 tests it: you build test and prod from the runbook alone.
2. **`deploy/<env>.env`: configuration in git** (this lesson). Endpoints, deployment names
   and API versions for each environment, non-secret by construction. The app reads it
   locally; the pipeline pushes it to the running app. Nobody types an endpoint into the
   portal for test or prod.
3. **`scripts/check_env.py`: machine-checked expectations** (Lesson 13). Before the pipeline
   deploys to an environment, it reads that environment's live configuration and compares it
   with `deploy/environments.yaml`: model versions, auth modes, semantic plan, role
   assignments. An environment that has drifted doesn't get deployed to.

Many regulated firms make the portal read-only for test and prod and require infrastructure
as code. The runbook plus the check script is the manual version of that discipline, and you'll feel
why IaC exists when you build test and prod in Lesson 13.

### One subscription or three?

Real organisations put prod in its own subscription, often all three environments in
separate ones, under a management group with Azure Policy applied. The subscription is the
strongest isolation boundary Azure has, and each one comes with its own quota and blast
radius.

For this course, **use one subscription with one resource group per environment.** Know what
that costs you:

- **Model quota is shared.** TPM quota is per subscription, per region, per model and
  deployment type. dev + test + prod capacity has to fit in one allowance.
- **You're Owner of prod.** You're building it by hand, so you need to be. Real firms use
  just-in-time elevation (Privileged Identity Management) so that nobody holds standing
  access to prod. Here, the substitutes are discipline, the prod delete lock, and holding
  no data-plane roles in test or prod.

### Cost, and when test and prod exist

A Basic search unit costs about US$0.10 an hour in UK South, roughly US$74 a month, and bills
whether you query it or not. Check the pricing page for your region. Three environments
with prod on two replicas is four units, about US$300 a month before a single token.

So **build dev now, write the runbook for all three, and build test and prod in Lesson 13**,
when there's something to promote. Delete them when the capstone is done. Read the
soft-delete pitfall before you plan to rebuild with the same names.

---

## Naming and tagging

Put the environment in every resource name. It costs nothing, and the smoke test can then
refuse to run when the configuration says `dev` but the endpoint says `test`.

| Resource | Name pattern | Constraint |
|---|---|---|
| Resource group | `rg-dti-rag-<env>`, plus `rg-dti-rag-shared` | |
| Foundry resource | `ai-dti-rag-<env>-<suffix>` | Becomes the endpoint subdomain, so it's globally unique |
| Foundry project | `dti-rag` | Same name in every environment |
| AI Search | `srch-dti-rag-<env>-<suffix>` | Globally unique |
| Storage account | `stdtirag<env><suffix>` | 3–24 lowercase letters and digits, globally unique |
| Key Vault | `kv-dtirag-<env>-<suffix>` | 3–24 characters, globally unique |
| Log Analytics / App Insights | `log-dti-rag-<env>` / `appi-dti-rag-<env>` | |
| Model deployments | `chat`, `embed` (later `judge`) | **Identical in every environment** |

`<suffix>` is a short fixed string you choose once (four or five characters) to keep global
names unique. Use the same suffix everywhere.

Tag every resource group and resource with `environment`, `workload = dti-rag` and `owner`.
It's tedious to do by hand, and the optional policy in step 10 does it for you.

**Name deployments by role, not by model.** `chat` and `embed`, not `gpt-4o` and
`text-embedding-3-large`. The model and deployment-name distinction then can't be missed,
since `chat` is obviously not a model name. A model upgrade also doesn't rename anything your
config refers to.

---

## Build dev: step by step

The order follows the dependencies. Each step lists the dev values. Where test or prod
differ, the value is given, so the same table becomes your runbook entry for Lesson 13.

### 1. Resource groups: all four, now

**Portal:** Resource groups → **Create**.

| Setting | Value |
|---|---|
| Name | `rg-dti-rag-dev`, then repeat for `-test`, `-prod`, `-shared` |
| Region | Your chosen region (see step 6) |
| Tags | `environment` = `dev` / `test` / `prod` / `shared`; `workload` = `dti-rag`; `owner` = you |

Empty resource groups cost nothing. Creating all four now means budgets and policy can be
scoped to them from day one.

### 2. Monitoring: Log Analytics workspace, then Application Insights

**Portal:** Log Analytics workspaces → **Create**. Resource group `rg-dti-rag-dev`, name
`log-dti-rag-dev`, same region. Once it's created, set its data retention: 30 days for dev and
test. Prod's retention is a Lesson 13 decision.

**Portal:** Application Insights → **Create**. Resource group `rg-dti-rag-dev`, name
`appi-dti-rag-dev`, same region, and **Log Analytics workspace** = the one you just created.

You won't wire these up until Lesson 13. Creating them now means every environment has its
own telemetry from the start. **Never point two environments at one App Insights**, because test
traffic in prod dashboards corrupts the one signal you rely on.

### 3. Storage account

**Portal:** Storage accounts → **Create**.

| Tab | Setting | dev | test | prod |
|---|---|---|---|---|
| Basics | Storage account name | `stdtiragdev<suffix>` | `…test…` | `…prod…` |
| Basics | Performance / Redundancy | Standard / LRS | Standard / LRS | Standard / ZRS if your region offers it |
| Advanced | Allow enabling anonymous access on individual containers | Off | Off | Off |
| Advanced | **Enable storage account key access** | **Off** | **Off** | **Off** |
| Advanced | Default to Microsoft Entra authorization in the Azure portal | On | On | On |
| Data protection | Soft delete for blobs; versioning | On | On | On |

Then **Data storage → Containers → + Container**, named `corpus`, private. Lesson 4's
indexer reads the corpus from here.

With key access off, the portal's storage browser uses *your* Entra identity, so you need a
data role before you can upload anything (step 8).

### 4. Key Vault

**Portal:** Key vaults → **Create**.

| Tab | Setting | dev | test | prod |
|---|---|---|---|---|
| Basics | Pricing tier | Standard | Standard | Standard |
| Basics | Days to retain deleted vaults | 7 | 7 | 90 |
| Basics | Purge protection | Disable | Disable | **Enable** |
| Access configuration | Permission model | **Azure role-based access control** | same | same |

Purge protection can never be turned off once enabled. That's the point in prod and a
nuisance in dev. With managed identity end to end you may never store a secret here. It
exists so the one secret you can't avoid has RBAC and an audit trail.

### 5. Foundry resource and project

Create the Foundry resource in the **Azure portal**, not through the Foundry portal's quick
"Create new project" button. That quick path generates its own resource and resource group
names, which breaks your naming and your environment boundaries.

**Portal:** search **Foundry** → **Foundry** → **Create**. Check the resource type is
*Foundry* (API kind `AIServices`), **not** *Azure AI hub*. A hub is the older hub-based
model this course avoids.

| Tab | Setting | Value |
|---|---|---|
| Basics | Resource group | `rg-dti-rag-dev` |
| Basics | Name | `ai-dti-rag-dev-<suffix>` |
| Basics | Region | Your chosen region |
| Basics | Default project name (if offered) | `dti-rag` |
| Network | Inbound access | All networks (see below) |
| Identity | System-assigned managed identity | On |
| Tags | | As step 1 |

If no project was created, add one in the Foundry portal (ai.azure.com, **New Foundry**
toggle on): **Manage** → **Resource details** → **Add project** → `dti-rag`.

**Network:** this course uses public endpoints with Entra-only auth in every environment. A
real prod would set Inbound access to **Disabled** and use private endpoints. Record that as
a known gap in `ENVIRONMENTS.md` rather than pretending it isn't one.

#### Turn off key access (the one step the portal can't do)

The Azure portal can't disable key-based auth on a Foundry resource. Do it from **Cloud
Shell**: the `>_` icon in the portal's top bar, in PowerShell mode.

```
az resource update \
  --resource-group rg-dti-rag-dev \
  --name ai-dti-rag-dev \
  --resource-type Microsoft.CognitiveServices/accounts \
  --set properties.disableLocalAuth=true

```

Check it with `Get-AzCognitiveServicesAccount` and confirm `DisableLocalAuth` is `True`.
Microsoft notes that enforcement can take minutes to hours to reach the gateway, so an old
key may keep working for a while.

**This is the step most likely to be forgotten in test and prod,** because it isn't where
all the other settings are. Put it in the runbook in bold. Step 10's policy flags it if you
miss it.

### 6. Model deployments

**Foundry portal** (ai.azure.com, New Foundry toggle on). Select the dev resource's project
top-left, then **Discover** → **Models** → pick the model → **Deploy** → **Custom settings**.

| Setting | `embed` | `chat` |
|---|---|---|
| Model | `text-embedding-3-large` | A GPT-4-class model. Check its retirement date before you pin it |
| Deployment name | `embed` | `chat` |
| Deployment type | Your one choice, the same everywhere (see below) | same |
| Model version | Pin it; record it | Pin it; record it |
| Version upgrade policy | The option that does **not** auto-upgrade | same |
| Tokens per Minute Rate Limit | dev ~50K; test and prod sized as below | dev ~20K; test and prod sized as below |
| Content filter | Default; same in every environment | same |

Afterwards, **Build** → **Models** lists the deployments. Confirm each shows **Succeeded**
and that the names and versions match what you recorded.

**Region.** Pick one region for all three environments. For a UK insurer, start from UK
South and confirm that both models, with your chosen deployment type, and semantic ranker
are available there. If they aren't, record where you went instead and why.

**Deployment type is a data-residency decision.** *Standard* processes in the deployment's
region, *Data Zone Standard* within a data zone, and *Global Standard* wherever Microsoft has
capacity. In a regulated firm, compliance owns this choice. Write down what you'd ask them,
pick one, and use it everywhere.

**Pinning makes the retirement date your deadline.** A deployment that doesn't auto-upgrade
never changes under you, and it stops working when its model version retires. Put the date
in a calendar. When you upgrade, it goes dev → test → prod like any other change (Lesson 13).

**Size TPM by arithmetic, not by feel.** Embedding the corpus is a few hundred chunks of a
few hundred tokens, around 100K tokens, so 50K TPM finishes in a couple of minutes. A full
eval run (Lesson 10) is 25 questions × several calls × a few thousand tokens. Size test's
`chat` so a run finishes in minutes. Remember that all three environments draw on **one
regional quota** in this setup. If a test deployment won't save, count dev's capacity first.

### 7. Azure AI Search

**Portal:** AI Search → **Create**.

| Tab | Setting | dev | test | prod |
|---|---|---|---|---|
| Basics | Service name | `srch-dti-rag-dev-<suffix>` | `…test…` | `…prod…` |
| Basics | Location | Your region | same | same |
| Basics | Pricing tier | **Basic** | Basic | Basic |
| Scale | Replicas / Partitions | 1 / 1 | 1 / 1 | **2** / 1 |

Then, on the created service:

| Blade | Setting | Value |
|---|---|---|
| Settings → **Keys** | API access control | **Role-based access control** |
| Settings → **Premium features** → Semantic ranker | Plan | **Standard** |
| Settings → **Identity** → System assigned | Status | On (Lesson 4's indexer and vectorizer use it) |

**The Keys setting is the trap.** A new search service defaults to **API keys only**. Leave
it there and the service rejects your valid role assignments with 401/403. You'll then blame
RBAC propagation for an hour.

**Why Basic, not Free.** Earlier versions of these notes said the Free tier can't do
semantic ranking. That's no longer true: the semantic ranker's free plan works on every
tier. Free is still wrong here:

- You get **one Free service per subscription**, so dev, test and prod can't all have one.
- Free can't use a managed identity for indexers, which Lesson 4 needs.
- Free has no SLA, and Microsoft may delete it after a period of inactivity.

**Why Standard for semantic ranker, even in dev.** The free plan gives a monthly allowance,
then returns billing errors. That failure shows up mid-eval in Lesson 10, looking like a
retrieval bug. Standard costs about US$1 per thousand queries after the free allowance.
Parity is worth more than that.

### 8. Role assignments

**Portal:** open the target resource → **Access control (IAM)** → **+ Add** → **Add role
assignment** → pick the role → **Members** → **Review + assign**.

For dev:

| Principal | Role | On |
|---|---|---|
| You | **Foundry User** | Foundry resource |
| You | Search Service Contributor | Search |
| You | Search Index Data Contributor | Search |
| You | Storage Blob Data Contributor | Storage account |
| Search service's identity | Cognitive Services OpenAI User | Foundry resource |
| Search service's identity | Storage Blob Data Reader | Storage account |

In test and prod, **you get none of these.** The pipeline's identities (Lesson 13) and the
app's identity (Lesson 12) do, each in its own environment only.

Things that catch people out:

- **Owner doesn't let you call the model.** Owner and Contributor are management roles;
  they don't include data actions. You're Owner of the subscription and still need
  *Foundry User* to make one chat call.
- **The Foundry roles were renamed.** *Foundry User* was *Azure AI User* until recently, and
  you may see either name in the portal. The role ID is unchanged:
  `53ca6127-db72-4b80-b1b0-d745d6d5456d`.
- **Why not *Cognitive Services OpenAI User* for you?** Older tutorials, and earlier
  versions of these notes, use it. It still allows chat and embedding calls, but only
  OpenAI data actions. It won't cover the Content Safety call in Lesson 11 or the Foundry
  project features in Lessons 9–10, and Microsoft's Foundry guidance now says to use
  *Foundry User*. The Search service's identity is the exception: it only ever embeds, so
  the narrower role is the right one for it.
- **Role assignments take five to ten minutes to propagate.** A 403 immediately after
  assigning a role usually means "wait", not "the role is wrong". Don't start debugging
  your code.
- **In Lesson 12 the app's managed identity gets `Search Index Data Reader`, not
  Contributor.** The app queries; it never writes. Don't copy your dev roles onto it.

### 9. Budgets: one per resource group, now

**Portal:** Cost Management → **Budgets** → **+ Add**, with the scope set to the resource
group. Reset period monthly. Alert conditions at 50%, 80% and 100% of actual cost, plus 100%
of forecast, emailed to you. Do it for all four resource groups now; empty ones cost
nothing.

A runaway loop in Lesson 5 that re-embeds the corpus a thousand times is a real possibility.
Dev's TPM cap turns that from "an expensive weekend" into "a rate-limit error at 11pm". The
budget alert is what tells you the cap was set too high.

### 10. Azure Policy: make drift visible (once, at subscription scope)

**Portal:** Policy → **Assignments** → **Assign policy**, scope = your subscription, effect
**Audit**:

- *Azure AI Services resources should have key access disabled (disable local
  authentication)*
- The built-in definitions for Azure AI Search local authentication and Storage shared-key
  access. Search the definitions for "local authentication" and "shared key".
- Optional: *Inherit a tag from the resource group if missing*, for `environment`. It uses
  the Modify effect and saves you tagging every resource by hand.

**Policy → Compliance** then shows, per resource, any environment where a setting was
missed. It's the cheapest drift detector you'll get. A real platform team would use **Deny**.
Audit is right here, because a Deny on key access would block the portal's own create flow,
which creates the Foundry resource with keys on before you turn them off.

---

## Record it

### `Documentation/design/ENVIRONMENTS.md`

Four sections:

1. **The environment matrix:** the two tables at the top of this lesson, filled in with
   *your* values (region, deployment type, model versions, TPM, replicas).
2. **Inventory:** per environment, every resource name and endpoint.
3. **Build runbook:** steps 1–10 as an ordered checklist with your values, test and prod
   columns included. If it isn't in the runbook, it won't happen in test.
4. **Change log:** date, environment, what changed, why, and whether it has reached test
   and prod yet. This is change management in miniature. In Lesson 13 the pipeline enforces
   the order dev → test → prod.

### `deploy/dev.env`

Endpoints, deployment names, API versions, the index name and `APP_ENV=dev`. **Commit it.**
It holds nothing secret, because there are no keys. That's also why a secret scanner in
pre-commit is cheap insurance: if something key-shaped ever lands in it, that's a bug upstream.

`deploy/test.env` and `deploy/prod.env` follow in Lesson 13. Your personal `.env`, if you keep
one for local overrides, stays git-ignored.

---

## Authentication in code

Authenticate with `az login`, then use `DefaultAzureCredential` in code. It walks a chain of
credential sources (environment variables, workload identity, managed identity, Azure CLI,
and more), which is exactly why the same code works on your laptop, in a GitHub Actions job
and in a container.

**Token provider, not token.** `DefaultAzureCredential` gives you a credential, but
`AzureOpenAI` wants an `azure_ad_token_provider`: a *callable* that returns a fresh token.
Pass a token string and it works for an hour, then expires in a way that's confusing to
debug. There's a helper for building the provider; the scope is
`https://cognitiveservices.azure.com/.default`.

### Settings carry the environment

`config.py` (pydantic-settings) gets an `app_env` field (`dev | test | prod`), required, with
no default. Locally it selects which `deploy/<env>.env` to read. In Azure, the same values
arrive as environment variables.

`app_env` is for **labelling**: telemetry, log lines, scorecards. It also guards
destructive scripts. It must never switch pipeline behaviour. If you ever write
`if settings.app_env == "prod":` in pipeline code, test isn't testing prod.

Every endpoint and deployment name is required with no default. A missing variable then fails
at startup instead of quietly pointing at whatever the default was.

---

## The dev loop

- Python 3.11+, virtual env, pre-commit with a secret scanner.
- `make setup` handles the install. `make smoke ENV=dev` runs the deliverable. `ENV`
  defaults to `dev`.
- The dependency set is already in `pyproject.toml`. It's split into extras
  (`orchestration`, `evaluation`, `observability`). That's not tidiness: it keeps LangGraph
  and the eval harness out of the Lesson 12 production container.

---

## The deliverable

`scripts/smoke_test.py` does three things:

1. **Prints which environment it's talking to:** `app_env` and the endpoint hostnames.
   Then it asserts that every hostname contains the environment name. "I thought I was on
   dev" is a mistake you make once; this catches it before it costs anything.
2. Embeds a sentence with the `embed` deployment and **asserts** the vector length.
3. Gets a one-line chat completion from the `chat` deployment.

All through the **OpenAI Python SDK, Azure-configured** (`AzureOpenAI`), authenticated with
`DefaultAzureCredential`.

**Assert the vector length.** Print it *and* check it's 3072, or whatever your deployment
gives. This one assertion catches "I pointed at the wrong deployment", which otherwise
surfaces in Lesson 4 as an index-dimension mismatch that's much harder to trace.

**Make it retry on 401/403 for a few minutes before failing.** Straight after role
assignments, propagation is the likeliest cause, and a smoke test that fails in the first
two minutes teaches you to ignore it.

The same script runs against test and prod in Lesson 13, from the pipeline, with the
pipeline's identity. Write it so nothing in it assumes dev.

---

## Pitfalls

| Symptom | Actual cause |
|---|---|
| `DeploymentNotFound` | Using the model name where the deployment name is wanted |
| 401/403 on first call | Role assignment hasn't propagated. Wait, don't debug |
| 401/403 from Search that never goes away | Search still on **API keys** only (Settings → Keys) |
| 403 calling the model as subscription Owner | Owner has no data actions; you need *Foundry User* |
| Auth works then fails an hour in | Passed a token string instead of a token *provider* |
| Old key still works after disabling local auth | Gateway propagation. Minutes to hours |
| Foundry resource and project with names you didn't choose | Created through the Foundry portal's quick path, not the Azure portal |
| Project features missing, or SDK errors about hubs | You created an *Azure AI hub*, not a *Foundry* resource |
| Can't upload to the storage container in the portal | Key access is off and you have no Storage Blob Data role |
| Test deployment won't save: quota | dev + test + prod TPM exceeds the shared regional quota |
| Rebuilding an environment fails: name in use | Foundry resources and Key Vaults are soft-deleted. Purge them (the resource list's *Manage deleted resources* / *Manage deleted vaults*) or pick a new suffix |
| Eval passes in test, fails in prod | Something in the "must match" table differs. Lesson 13's `check_env` exists for this |
| Vector dimension mismatch in Lesson 4 | Smoke test never asserted the embedding length |

---

## Done when

- dev is built, every resource is tagged, and each setting in steps 1–10 is recorded in
  `ENVIRONMENTS.md`, with test and prod values written down but not yet built.
- `make smoke ENV=dev` passes. Both calls succeed using `DefaultAzureCredential`, with no key
  in the code, in `deploy/dev.env` or on the Foundry resource. The embedding length is
  asserted, not eyeballed, and the environment is printed first.
- Policy → Compliance shows dev compliant with the step 10 assignments.

## Check yourself

1. Why does `AzureOpenAI` want a token *provider* rather than a token?
2. Your app's managed identity will need Search access in Lesson 12. Which role, and why not
   the same one you gave yourself?
3. What would have to be true for `text-embedding-3-small` to be the right call here?
4. You get a 403 thirty seconds after assigning yourself a role. What do you do?
5. Why must model versions match between test and prod when replica counts may differ?
6. Name the one dev setting you *couldn't* make in the portal. How will you make sure it
   isn't forgotten in prod?
7. You're subscription Owner. Why can't you call the chat model until you add another role?
8. What stops the pipeline identity for test from changing anything in prod?

---

**Next:** [Lesson 02 — Read the corpus like an adversary](Lesson02.md)
