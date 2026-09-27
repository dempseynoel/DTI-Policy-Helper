# Environments

My record of how dev, test and prod are built in the Azure portal.

**How to use this file**

- **While building dev (Lesson 01):** work through section 3 in order. Tick the `dev` box
  as each step is done, and fill in section 2 with the real names and endpoints.
- **Building test and prod (Lesson 13):** follow section 3 again, **using only this file**.
  If you have to look something up or improvise, write it into this file before carrying on.
- **Whenever anything changes, in any environment:** add a row to section 5.

Recommended values from the lessons are already filled in. Change them if you decide
differently, and note why.

---

## 1. Environment matrix

### What may differ between environments

| Setting | dev | test | prod |
|---|---|---|---|
| Purpose | My inner loop; break it freely | Rehearsal for prod; eval gate runs here | Claims handlers use it |
| Who changes infrastructure | Me, freely | Me, replaying a change already made in dev | Me, only after it passed in test |
| Who deploys application code | Me or the pipeline | Pipeline only | Pipeline only, after approval |
| My data-plane access | Yes | No | No |
| `chat` TPM (thousands) | 20 | ____ | ____ |
| `embed` TPM (thousands) | 50 | 50 | 50 |
| `judge` TPM (thousands) | 20 | ____ | none |
| Search replicas | 1 | 1 | 2 |
| Storage redundancy | LRS | LRS | ZRS (if offered in region) |
| Key Vault: days to retain deleted vaults | 7 | 7 | 90 |
| Key Vault: purge protection | Off | Off | On (irreversible) |
| Log Analytics retention (days) | 30 | 30 | ____ (complaint-handling decision, Lesson 13) |
| Delete lock on resource group | No | No | Yes |
| Container App min / max replicas | 0 / 1 | 0 / 2 | 1 / ____ |
| Container App authentication | Optional | Entra ID | Entra ID |
| Monthly budget | ____ | ____ | ____ |
| Data | Synthetic only | Synthetic only | Real claims context (redacted) |

### What must match in every environment

| Setting | Value (the same everywhere) |
|---|---|
| Subscription | ____ |
| Region | ____ (start from UK South; confirm models and semantic ranker are available) |
| Name suffix | ____ (4–5 characters, chosen once) |
| Deployment type | ____ (Global Standard / Data Zone Standard / Standard; a data-residency decision) |
| `chat` model and version | ____ / ____ retires ____ |
| `embed` model and version | text-embedding-3-large / 1 retires ____ |
| `judge` model and version (dev + test) | ____ / ____ retires ____ |
| Version upgrade policy | No automatic upgrade |
| Content filter | Default (`Microsoft.DefaultV2`) |
| Semantic ranker plan | Standard |
| Search API version | ____ |
| OpenAI API version | ____ |
| Auth | Entra ID only: keys off on Foundry, Search and Storage |

> **Picking the models:** check the retirement schedule and pick a GA version that isn't
> deprecated. For example, `gpt-5.4-mini` `2026-03-17` retires 2027-09-21. Lesson 5 asks for
> temperature 0, so also check that your chosen model accepts a `temperature` parameter.
> Reasoning models may not.

---

## 2. Inventory

Fill in as you create each resource. These values go into `deploy/<env>.env`.

### Per environment

| Resource | dev | test | prod |
|---|---|---|---|
| Resource group | `rg-dti-rag-dev` | `rg-dti-rag-test` | `rg-dti-rag-prod` |
| Log Analytics workspace | `log-dti-rag-dev` | | |
| Application Insights | `appi-dti-rag-dev` | | |
| App Insights connection string | ____ | | |
| Storage account | `stdtiragdev____` | | |
| Key Vault | `kv-dtirag-dev-____` | | |
| Foundry resource | `ai-dti-rag-dev-____` | | |
| Foundry project | `dti-rag` | `dti-rag` | `dti-rag` |
| OpenAI endpoint | `https://ai-dti-rag-dev-____.openai.azure.com/` | | |
| Foundry project endpoint | ____ | | |
| AI Search | `srch-dti-rag-dev-____` | | |
| Search endpoint | `https://srch-dti-rag-dev-____.search.windows.net` | | |
| Container Apps environment | `cae-dti-rag-dev` | | |
| Container App | `ca-dti-rag-dev` | | |
| App URL | ____ | | |
| App identity | `id-dti-rag-app-dev` (client ID ____) | | |
| Pipeline deploy identity (Lesson 13) | `id-dti-rag-deploy-dev` (client ID ____) | | |

### Shared (`rg-dti-rag-shared`)

| Resource | Name | Notes |
|---|---|---|
| Container registry | `crdtirag____` | Admin user disabled |
| Build identity (Lesson 13) | `id-dti-rag-build` | client ID ____ |
| PR-eval identity (Lesson 13) | `id-dti-rag-eval` | client ID ____ |

---

## 3. Build runbook

Follow in order. Each step says which lesson introduces it.

### Step 1: Resource groups (Lesson 01, all four at once)

**Portal:** Resource groups → Create.

- Names: `rg-dti-rag-dev`, `rg-dti-rag-test`, `rg-dti-rag-prod`, `rg-dti-rag-shared`
- Region: the region from section 1
- Tags: `environment` = dev / test / prod / shared, `workload` = `dti-rag`, `owner` = me

**Done:** ☐ dev · ☐ test · ☐ prod · ☐ shared

### Step 2: Log Analytics workspace, then Application Insights (Lesson 01)

**Portal:** Log Analytics workspaces → Create → `log-dti-rag-<env>`, then set data retention
(section 1).
**Portal:** Application Insights → Create → `appi-dti-rag-<env>`, Log Analytics workspace =
the one above.

- Copy the App Insights **connection string** (Overview) into section 2.
- Never point two environments at the same App Insights.

**Done:** ☐ dev · ☐ test · ☐ prod

### Step 3: Storage account (Lesson 01)

**Portal:** Storage accounts → Create → `stdtirag<env><suffix>`.

| Tab | Setting | Value |
|---|---|---|
| Basics | Performance / Redundancy | Standard / section 1 |
| Advanced | Allow enabling anonymous access on individual containers | **Off** |
| Advanced | Enable storage account key access | **Off** |
| Advanced | Default to Microsoft Entra authorization in the Azure portal | On |
| Data protection | Soft delete for blobs; versioning | On |

Then **Data storage → Containers → + Container** → `corpus`, private.

**Done:** ☐ dev · ☐ test · ☐ prod

### Step 4: Key Vault (Lesson 01)

**Portal:** Key vaults → Create → `kv-dtirag-<env>-<suffix>`.

| Tab | Setting | Value |
|---|---|---|
| Basics | Pricing tier | Standard |
| Basics | Days to retain deleted vaults | Section 1 (can't be changed later) |
| Basics | Purge protection | Section 1 (can never be turned off) |
| Access configuration | Permission model | **Azure role-based access control** |

**Done:** ☐ dev · ☐ test · ☐ prod

### Step 5: Foundry resource and project (Lesson 01)

**Portal:** search **Foundry** → Foundry → Create. Check the type is **Foundry**, not *Azure
AI hub*. Don't use the Foundry portal's quick "Create new project" button, because it picks
its own names.

| Tab | Setting | Value |
|---|---|---|
| Basics | Resource group | `rg-dti-rag-<env>` |
| Basics | Name | `ai-dti-rag-<env>-<suffix>` |
| Basics | Region | Section 1 |
| Basics | Default project name (if offered) | `dti-rag` |
| Network | Inbound access | All networks (known gap, section 4) |
| Identity | System-assigned managed identity | **On** |
| Tags | | As step 1 |

If no project was created: Foundry portal (ai.azure.com, New Foundry on) → **Manage** →
**Resource details** → **Add project** → `dti-rag`.

> ⚠️ **The step the portal can't do: turn off key access.** Open Cloud Shell (`>_` in the
> portal top bar), choose PowerShell, and run:
>
> ```
> Set-AzCognitiveServicesAccount -ResourceGroupName "rg-dti-rag-<env>" `
>   -Name "ai-dti-rag-<env>-<suffix>" -DisableLocalAuth $true
> ```
>
> Check that `(Get-AzCognitiveServicesAccount -ResourceGroupName "rg-dti-rag-<env>" -Name
> "ai-dti-rag-<env>-<suffix>").DisableLocalAuth` returns `True`. It can take minutes to hours
> to fully take effect.

**Done:** ☐ dev · ☐ test · ☐ prod
**Keys disabled:** ☐ dev · ☐ test · ☐ prod

### Step 6: Model deployments (Lesson 01; `judge` added in Lesson 10)

**Foundry portal:** select the environment's project → **Discover** → **Models** → pick the
model → **Deploy** → **Custom settings**.

| Setting | `chat` | `embed` | `judge` (dev + test only) |
|---|---|---|---|
| Model / version | Section 1 | Section 1 | Section 1 |
| Deployment name | `chat` | `embed` | `judge` |
| Deployment type | Section 1 | Section 1 | Section 1 |
| Version upgrade policy | No auto-upgrade | No auto-upgrade | No auto-upgrade |
| Tokens per Minute Rate Limit | Section 1 | Section 1 | Section 1 |
| Content filter | Default | Default | Default |

Check under **Build → Models**: every deployment shows **Succeeded** with the right version.

- `chat`: ☐ dev · ☐ test · ☐ prod
- `embed`: ☐ dev · ☐ test · ☐ prod
- `judge`: ☐ dev · ☐ test

### Step 7: Azure AI Search (Lesson 01)

**Portal:** AI Search → Create → `srch-dti-rag-<env>-<suffix>`, Pricing tier **Basic**,
Replicas from section 1, Partitions 1.

Then, on the created service:

| Blade | Setting | Value |
|---|---|---|
| Settings → **Keys** | API access control | **Role-based access control** (default is keys only, which rejects roles) |
| Settings → **Premium features** → Semantic ranker | Plan | **Standard** |
| Settings → **Identity** → System assigned | Status | **On** |

**Done:** ☐ dev · ☐ test · ☐ prod

### Step 8: Role assignments (Lesson 01; app roles in step 12)

**Portal:** target resource → **Access control (IAM)** → Add → Add role assignment → role →
Members → Review + assign.

| Principal | Role | On | dev | test | prod |
|---|---|---|---|---|---|
| Me | Foundry User | Foundry resource | ✔ | — | — |
| Me | Search Service Contributor | Search | ✔ | — | — |
| Me | Search Index Data Contributor | Search | ✔ | — | — |
| Me | Storage Blob Data Contributor | Storage | ✔ | — | — |
| Search's identity | Cognitive Services OpenAI User | Foundry resource | ✔ | ✔ | ✔ |
| Search's identity | Storage Blob Data Reader | Storage | ✔ | ✔ | ✔ |

- Owner doesn't include data actions, so I still need Foundry User to call a model.
- Propagation takes 5–10 minutes. A 403 straight afterwards means wait, not debug.

**Done:** ☐ dev · ☐ test · ☐ prod

### Step 9: Budget (Lesson 01, one per resource group)

**Portal:** Cost Management → Budgets → + Add → scope = the resource group. Monthly, amount
from section 1, alerts at 50% / 80% / 100% actual and 100% forecast, emailed to me.

**Done:** ☐ dev · ☐ test · ☐ prod · ☐ shared

### Step 10: Azure Policy, audit only (Lesson 01, once for the subscription)

**Portal:** Policy → Assignments → Assign policy, scope = subscription, effect **Audit**:

- [ ] *Azure AI Services resources should have key access disabled (disable local authentication)*
- [ ] Azure AI Search local authentication disabled (search definitions for "local authentication")
- [ ] Storage accounts shared key access (search definitions for "shared key")
- [ ] Optional: *Inherit a tag from the resource group if missing*, for `environment`

Check **Policy → Compliance** after each environment is built.

### Step 11: Shared container registry (Lesson 12, once)

**Portal:** Container registries → Create → resource group `rg-dti-rag-shared`,
`crdtirag<suffix>`, SKU **Basic**, admin user **disabled**.

- [ ] Cloud Shell: `az acr config authentication-as-arm show -r <registry>`. Enable it if
  disabled, because managed-identity pulls need it.
- [ ] Me: **AcrPush** on the registry, to push dev images. Remove it in Lesson 13 once the
  build identity exists.

### Step 12: App identity and its roles (Lesson 12)

**Portal:** Managed Identities → Create → resource group `rg-dti-rag-<env>`,
`id-dti-rag-app-<env>`. Record its client ID in section 2.

| Role | On |
|---|---|
| AcrPull | Shared registry |
| Foundry User | This environment's Foundry resource |
| **Search Index Data Reader** | This environment's Search (Reader, never Contributor) |
| Monitoring Metrics Publisher | This environment's App Insights (only if its local auth is disabled) |

**Done:** ☐ dev · ☐ test · ☐ prod

### Step 13: Container App (Lesson 12)

1. **Portal:** Container Apps → Create:
   - Resource group `rg-dti-rag-<env>`, name `ca-dti-rag-<env>`, region from section 1
   - Container Apps environment: **Create new** `cae-dti-rag-<env>`, logging to
     `log-dti-rag-<env>`
   - Container tab: **Use quickstart image** on
   - Ingress: enabled
2. **Identity** → User assigned → Add → `id-dti-rag-app-<env>`
3. **Application → Containers → Edit and deploy** → select the container:
   - Image source: Azure Container Registry
   - Authentication: **Managed identity** → `id-dti-rag-app-<env>`
   - Registry / image / tag: shared registry, `dti-rag`, git SHA. The pipeline uses digests
     from Lesson 13.
   - Environment variables: every line of `deploy/<env>.env`, plus `AZURE_CLIENT_ID` = the
     app identity's client ID
   - Health probes: liveness and readiness on `GET /health`
   - Save → Create
4. **Ingress** → Target port = the app's port. The quickstart used 80.
5. **Application → Scale** → min/max from section 1.
6. **Settings → Authentication** (test and prod) → Add identity provider → Microsoft →
   reject unauthenticated requests. Allow the pipeline identity to call it (Lesson 13).

**Done:** ☐ dev · ☐ test · ☐ prod

### Step 14: Prod-only protections (Lesson 13)

- [ ] `rg-dti-rag-prod` → **Settings → Locks** → Add → lock type **Delete**
- [ ] Key Vault purge protection on (step 4)
- [ ] Search on 2 replicas (step 7)
- [ ] Container App min replicas ≥ 1 (step 13)
- [ ] Log retention set to the complaint-handling decision (step 2)
- [ ] **Check access** on myself for prod's Foundry, Search and Storage shows **no data roles**

### Step 15: Pipeline identities (Lesson 13)

**Portal:** Managed Identities → Create (resource group `rg-dti-rag-shared`). Then the
identity → **Settings → Federated credentials → Add Credential** → scenario **GitHub Actions
deploying Azure resources**.

| Identity | Entity type → value | Roles | Done |
|---|---|---|---|
| `id-dti-rag-build` | Branch → `main` | AcrPush on shared registry | ☐ |
| `id-dti-rag-deploy-dev` | Environment → `dev` | Deploy roles below, in dev only | ☐ |
| `id-dti-rag-deploy-test` | Environment → `test` | Deploy roles below, in test only | ☐ |
| `id-dti-rag-deploy-prod` | Environment → `prod` | Deploy roles below, in prod only | ☐ |
| `id-dti-rag-eval` | Environment → `pr-eval` | Test only: Search Service Contributor, Search Index Data Contributor, Foundry User | ☐ |

**Deploy roles** (each scoped to its own environment):

| Role | On |
|---|---|
| Reader | The environment's resource group |
| Contributor | The Container App **and** its Container Apps environment only |
| Foundry User | Foundry resource |
| Search Service Contributor + Search Index Data Contributor | Search |
| Storage Blob Data Contributor | Storage |

- A typo in a federated credential fails silently. Compare the subject with the workflow's
  `environment:` character by character.
- [ ] Removed my own AcrPush from the registry (step 11)

### Step 16: GitHub environments (Lesson 13)

**GitHub:** repository → Settings → Environments.

| Environment | Variables | Protection | Done |
|---|---|---|---|
| `dev` | `AZURE_CLIENT_ID` (deploy-dev), `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | — | ☐ |
| `test` | `AZURE_CLIENT_ID` (deploy-test), tenant, subscription | — | ☐ |
| `prod` | `AZURE_CLIENT_ID` (deploy-prod), tenant, subscription | Required reviewers; deployment branch `main` only | ☐ |
| `pr-eval` | `AZURE_CLIENT_ID` (eval), tenant, subscription | — | ☐ |

### Step 17: Verify the environment

- [ ] `deploy/<env>.env` created from section 2
- [ ] `make smoke ENV=<env>` passes (from the pipeline for test and prod)
- [ ] Policy → Compliance: environment compliant
- [ ] **Check access**: no identity from another environment has roles here

**Verified:** ☐ dev · ☐ test · ☐ prod

---

## 4. Known gaps

Things a real regulated deployment would do differently, and why they're accepted here.

| Gap | Why accepted | What real prod would do |
|---|---|---|
| Public endpoints on all resources | Course simplicity and cost | Private endpoints, inbound access disabled |
| One subscription for all three environments | Cost; one person | Separate subscriptions under a management group |
| I hold Owner on prod | I build it by hand | Just-in-time elevation (PIM); no standing access |
| Infrastructure built by hand | Learning what every setting does | Infrastructure as code; portal read-only for test and prod |
| ____ | | |

---

## 5. Change log

Every change to any environment, newest first. A change isn't finished until it reaches
prod or is deliberately rejected.

| Date | Change | Why | dev | test | prod |
|---|---|---|---|---|---|
| ____ | Built dev (steps 1–10) | Lesson 01 | ✔ | | |
