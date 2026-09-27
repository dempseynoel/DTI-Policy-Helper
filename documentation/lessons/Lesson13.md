# Lesson 13 — Observability, promotion through dev → test → prod, and the capstone demo

**Objective:** make it operable and provably non-regressing, promote it through three
environments behind an eval gate, then assemble the capstone.

**Deliverables:**

- test and prod built in the portal from your runbook, with nothing improvised
- working traces, per environment
- a pipeline that builds once and promotes the same artefact dev → test → prod, gated by
  the eval harness and your approval
- a drift check that stops the pipeline deploying to an environment that no longer matches
  its recorded configuration
- the demo runbook, demoed against **prod**

---

## Observability

OpenTelemetry → Application Insights. The Azure Monitor OpenTelemetry distro plus FastAPI
instrumentation gets you most of the way.

### Spans that matter

Instrument the pipeline stages separately: `route`, `retrieve`, `generate`,
`guardrail_check`. Aggregate latency tells you the system is slow; per-stage latency tells
you *which part*, and they have completely different fixes — retrieval latency is an index
or filter problem, generation latency is a model or token-count problem.

Attributes worth attaching:

| Attribute | Why |
|---|---|
| `mode` | Distribution of answer/ask/abstain is a health signal in itself |
| `governing_edition` | Which editions get asked about |
| `filter_applied` | Debugging a wrong answer starts here |
| `chunks_retrieved`, top score | Retrieval quality proxy |
| `prompt_tokens`, `completion_tokens` | Cost attribution |
| `guardrail_status` | Groundedness rate over time |
| `trace_id` | Ties to the API response and the audit log |

### Dashboards

- **Token cost** — per request and aggregate. Cost surprises come from prompt growth, and
  prompt growth is invisible without this.
- **Latency split** — retrieval vs generation, p50 and p95. Watch p95; the average hides the
  experience that makes people stop using a tool.
- **Groundedness rate** — the quality signal that matters in production. A drop means
  something changed: the index, the model, or the questions being asked.
- **Mode distribution** — a sudden rise in abstentions means retrieval broke or the question
  mix shifted. Either way you want to know the day it happens, not the quarter.

### Per environment

- **Each environment reports to its own Application Insights** (Lesson 1), set through
  `APPLICATIONINSIGHTS_CONNECTION_STRING` in `deploy/<env>.env`. Never share one: test traffic
  in prod's dashboards corrupts the one signal you rely on.
- **Stamp every span with where it came from.** Set the OpenTelemetry resource attributes
  `deployment.environment.name` = `APP_ENV` and `service.version` = the git SHA. Then "which
  environment, which code?" is on every trace.
- **Sampling:** 100% in dev and test, where volume is tiny. Sampled in prod: traces are
  operational. The audit log is complete regardless (below).
- **Alerts, in the portal** (App Insights → **Alerts** → **Create** → **Alert rule**): in prod,
  groundedness rate, abstention spike, p95 latency, 5xx and 429 rates. In test, only
  pipeline health. In dev, none. Record each rule in the runbook.
- **Build the dashboard once.** Build the workbook in dev, then copy its JSON (the workbook's
  **Advanced editor**) into the repo and import it into test and prod. Three hand-built
  dashboards drift like three hand-built environments.
- **If you disable local authentication on App Insights** (its **Properties** blade), the
  app identity needs *Monitoring Metrics Publisher* on it, or telemetry stops arriving. Add
  the role to all three environments' runbook entries.

### The audit trail

> **Log the retrieved context and the selected edition for every answer.**

This is not a debugging convenience. When a handler is asked in six months why a customer
was told £300, the answer must be reconstructible: this question, this edition, this
reasoning, these chunks, this response, this prompt version.

Which means:

- **Retention** long enough to be useful — align it with complaint-handling timeframes, not
  with your default log retention.
- **Redaction** per Lesson 11. This log contains claims context. It is personal data.
- **Prompt version** in the log. "Why did it say that?" is unanswerable if you can't
  reconstruct the prompt.
- **Access control.** An audit log everyone can read is a personal-data exposure.
- **Per environment.** Only prod's audit log holds real claims context, so only prod's
  needs the long retention and the tight access. dev and test log synthetic data (Lesson 11)
  and keep it briefly. Test's audit log still has to *work*: Lesson 10's promotion gate reads
  context back from it by `trace_id`, which is how every promotion proves the audit trail
  is complete.

Traces (sampled, short retention, for operations) and the audit log (complete, long
retention, for accountability) are **different things with different requirements.** Don't
conflate them — sampled traces are useless as an audit trail, and audit-retention traces are
expensive and a liability.

---

## Build test and prod — from the runbook, and nothing else

Now there's something to promote, build the other two environments. **Follow
`ENVIRONMENTS.md` and only `ENVIRONMENTS.md`.** That is the test of your runbook. Anything you
have to look up, remember or improvise goes into the runbook *before* you carry on. If you
can't build test from it alone, neither could a colleague at 2am.

Work through Lesson 1's steps 2–10 with the test and prod values, then Lesson 12's
container-app steps. After that, the prod-only extras:

- **Delete lock:** `rg-dti-rag-prod` → **Settings → Locks** → **Add** → lock type
  **Delete**. Removing it becomes a deliberate act. Contributor can't remove locks, so no
  pipeline identity can.
- Key Vault purge protection **on**, Search on **2** replicas, min replicas **1 or more**,
  and log retention set to your complaint-handling decision.
- **The Foundry key-access step** (Cloud Shell, Lesson 1 step 5). It's the one the portal
  doesn't show you, so it's the one you'll forget.

Then create `deploy/test.env` and `deploy/prod.env` from the new resources' endpoints, and
check **your own** access. **Access control (IAM) → Check access** on yourself, for test's
and prod's Foundry, Search and storage, should show no data roles. You built these
environments, and you can't read their data. That's the design.

---

## Pipeline identities and GitHub environments

Five user-assigned managed identities in `rg-dti-rag-shared`, each trusted by exactly one
kind of GitHub job. Managed identities with federated credentials need no Entra app
registrations and no secrets, and you can create them entirely in the portal.

| Identity | Federated credential: entity type → value | Roles |
|---|---|---|
| `id-dti-rag-build` | Branch → `main` | *AcrPush* on the shared registry |
| `id-dti-rag-deploy-dev` | Environment → `dev` | Deploy roles (below), in **dev only** |
| `id-dti-rag-deploy-test` | Environment → `test` | Deploy roles, in **test only** |
| `id-dti-rag-deploy-prod` | Environment → `prod` | Deploy roles, in **prod only** |
| `id-dti-rag-eval` | Environment → `pr-eval` | On test: *Search Service Contributor* + *Search Index Data Contributor* (Search), *Foundry User* (Foundry) |

**Deploy roles**, each scoped to that identity's own environment:

| Role | On | Why |
|---|---|---|
| Reader | The environment's resource group | `check_env` reads live configuration |
| Contributor | The Container App **and** its Container Apps environment, not the resource group | Deploy a new revision, and nothing else |
| Foundry User | Foundry resource | Embeddings during the index load; smoke test |
| Search Service Contributor + Search Index Data Contributor | Search | Create and load the index |
| Storage Blob Data Contributor | Storage account | Upload the corpus; write the index manifest |

Once the build identity exists, remove your own *AcrPush* from Lesson 12.

**Portal:** Managed Identities → **Create** (resource group `rg-dti-rag-shared`). Then the
identity → **Settings → Federated credentials → Add Credential** → scenario **GitHub Actions
deploying Azure resources** → Organization, Repository, **Entity type** and its value, a
Name → **Add**. Copy the identity's **Client ID**.

**A typo in the federated credential fails silently.** It saves without complaint, and the
token exchange fails later with an error that doesn't point at it. When a workflow's Azure
login fails, compare the credential's subject identifier with the job's `environment:`
character by character before you look at anything else.

**GitHub:** repository → **Settings → Environments** → create `dev`, `test`, `prod` and
`pr-eval`. On each, add **variables**, not secrets (none of these values is secret):
`AZURE_CLIENT_ID` (that environment's identity), `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`.
On `prod`, add **Required reviewers** (you, here; in a real team, someone who didn't write
the change) and limit **Deployment branches** to `main`.

That puts two locks on prod. A job only receives prod's client ID if it declares
`environment: prod`, and Azure only honours the token if it came from a job in the `prod`
environment. A workflow on a feature branch can get neither.

**Why a separate identity for pull requests?** PR code hasn't been reviewed yet. It gets
data-plane access to test's Search and models, enough to build a throwaway index and run
the bank, and nothing that can touch a deployed app.

---

## `deploy/environments.yaml` and `scripts/check_env.py`

The portal can't stop test and prod drifting apart. The pipeline can refuse to deploy once
they have.

`deploy/environments.yaml` states what each environment's Azure configuration **must** be:

- **Shared: must match everywhere.** Region; deployment names, model names and versions,
  deployment type, upgrade policy and content filter; semantic ranker plan; key access
  disabled on the Foundry resource; Search API access control set to RBAC; storage key
  access off.
- **Per environment: may differ.** Search replicas; TPM per deployment; Key Vault purge
  protection; the delete lock; min and max replicas; and the expected role assignments,
  **including the ones that must not exist.** No human data roles in test or prod; no
  *Contributor* or *Search Index Data Contributor* on any app identity; no deploy identity
  holding anything outside its own environment.
- **Config consistency:** every endpoint in `deploy/<env>.env` belongs to that environment's
  resource group. This catches test's config pointing at dev's Search.

`check_env.py --env test` reads the live configuration through the Azure management APIs.
*Reader* is enough. It prints every difference and exits non-zero if there are any. The
pipeline runs it **before** deploying to each environment, and you can run it any time.
It's the portal-world equivalent of a plan against real state, and it's the reason portal
building is survivable.

---

## The promotion pipeline

> **Block, don't slow.** The discipline real regulated teams use.

```
 pull request ──► ci.yml        lint · unit tests · chunk determinism           no Azure; seconds
             └──► pr-eval.yml   PR's code, in-process, against a throwaway      blocks merge
                                index on test's Search (as id-dti-rag-eval)

 merge to main ─► deploy.yml
                   build ─ image built once, pushed, digest recorded
                     │     chunks.jsonl built once, uploaded as a workflow artefact
                     │
                     ├─► dev    check_env · load index · deploy digest · smoke
                     │
                     ├─► test   check_env · load index · deploy digest · smoke
                     │          · eval through the deployed API ──────────────┐
                     │                                                        │ promotion gate
                     └─► prod   ◄── you approve: digest, SHA, test scorecard ─┘
                                check_env · load index · deploy digest · smoke

 nightly ───────► drift.yml     check_env for dev, test and prod               alerts on drift
```

`ci.yml` and `pr-eval.yml` are split deliberately. A developer who waits ten minutes for a
typo fix stops running CI locally.

**Each deploy job**, in order:

1. Log in to Azure with that environment's client ID (OIDC, no stored secret).
2. **`check_env`**. Stop if the environment has drifted.
3. **Load the index** from the *same* `chunks.jsonl` the build job produced. The loader is
   idempotent and schema-versioned (Lesson 4), so this is quick when the manifest already
   matches.
4. **Deploy:** `az containerapp update` with the image **digest**, and
   `--replace-env-vars` with the contents of `deploy/<env>.env`. Replace, not merge, so a
   removed variable really goes.
5. **Smoke:** wait for `/health`, then run the Lesson 1 smoke test through the API, plus
   Lesson 11's "a request that must be blocked is blocked".
6. **test only, the promotion gate:** the full eval bank through the deployed API
   (`run_eval.py --target api`).

**Make the prod approval informative.** Put the image digest, git SHA, test's scorecard
against the baseline, and prod's `check_env` result in the test job's summary. An approval
screen that just says "deploy to prod?" gets approved without anyone reading it.

### Two gates, testing two different things

- **PR gate (`pr-eval.yml`): is this code good?** It runs the PR's pipeline in-process
  (`--target local`) against test's Search service and model deployments, using a throwaway
  index `dti-policy-pr-<number>` built from the PR's own chunks. It blocks merge and deletes
  the index afterwards. The nightly job sweeps any that leak, because Basic has a small index
  limit and a leaked index eventually fails an unrelated PR.
- **Promotion gate (in `deploy.yml`): is this deployment good?** The same bank, through the
  **deployed** API in test. It exercises everything the PR gate can't: the container, the
  app identity's roles, the environment variables, the loaded index, the authentication.
  It blocks promotion to prod.

The second gate catches a class of failure the first structurally can't: the code is right,
but test's app identity is missing a role, or an environment variable points at the wrong
thing. That class of failure otherwise reaches prod.

### Gate design

**What to gate on.** Not the aggregate — a single blended score lets a big win in one
category mask a regression in another. Gate per metric:

- `edition_correct` — no regression at all. This is the correctness property of the system.
- Abstention and ambiguity — no regression. Behavioural failures are severe.
- `must_include` — no regression beyond a small tolerance.
- Groundedness — no drop beyond threshold.

**Thresholds.** Exact-match on a 25-question bank is noisy — one question is 4%. But
`edition_correct` and the behavioural metrics should be deterministic given a fixed
temperature, so gate those at zero tolerance. Allow small tolerance only on LLM-judged
metrics, which genuinely vary.

**Post the scorecard as a PR comment.** A gate that fails with a link to a log is a gate
people learn to bypass. A gate that comments "edition_correct dropped 1.00 → 0.88;
DTI-004 and DTI-005 now return the 2025 edition" is one they act on.

**The baseline lives in test**, because that's where both gates run. When test first exists,
regenerate the committed baseline there. Lesson 5's dev baseline is only comparable if dev
and test served the same model versions from the same chunks, and the scorecard metadata
from Lesson 10 lets the comparison script check that rather than assume it. It refuses to
compare scorecards whose model versions or index manifests differ.

**Authenticate with OIDC federated credentials**, not a stored secret: the identities above.
A long-lived service principal secret in GitHub Actions is the thing you're trying to avoid.

**Handle flakiness honestly.** Some metrics vary run to run. Options: fix temperature to 0
(do this), cache the judge, or require two consecutive failures. What you must *not* do is
widen thresholds until the gate stops failing — that's a gate that has been decommissioned
without anyone saying so.

### Promoting an infrastructure change

Portal changes get promoted too: by hand, in the same order, with the pipeline checking your
work. Take a new model version for `chat`:

1. **dev:** change the deployment's version in the Foundry portal. Run `make eval ENV=dev`.
2. **PR:** update the version in the shared section of `deploy/environments.yaml`, and add
   a change-log entry to `ENVIRONMENTS.md`. Merge it.
3. The deploy pipeline passes dev, then **stops at test's `check_env`**, because test is
   still on the old version. That's the pipeline telling you it's test's turn.
4. **test:** make the same change in the portal and re-run the job. `check_env` passes, and
   the promotion gate now evaluates the **new model** through the deployed app.
5. **prod:** make the change, then approve. Prod's `check_env` confirms you made exactly the
   change that was recorded, and the deploy goes through.

This is why `check_env` blocks rather than warns. It means **prod can never run a
configuration that test didn't pass the gate with**, even though a human made every change
by hand. The same flow covers a new deployment (Lesson 10's `judge` in test), a changed
role, or a new app setting.

### Rollback

- **App:** re-run the prod deploy job for the last good commit. That digest has already
  passed test, and its schema-versioned index still exists (Lesson 4), so rolling back the
  app is enough. In an emergency, the app's **Revision management** can reactivate the
  previous revision in the portal. Treat that as break-glass: record it, because prod no
  longer matches main's latest deploy.
- **Infrastructure:** reverse the portal change by hand, record it in the change log, and
  run `check_env` to confirm.

### Drift detection

`drift.yml` runs `check_env` against all three environments every night, read-only. A
failure means someone changed something in the portal that isn't in git. Found the next
morning, it's a conversation. Found at the next prod deploy, it's a blocked release at the
worst possible moment. Azure Policy's compliance view (Lesson 1) is your second, coarser
detector.

### Prove it works

> **Commit a change that deliberately breaks retrieval and watch CI block it.**

Remove the pre-filter, or break a date boundary. If the PR gate doesn't catch it, the gate
is theatre. This is a "done when" criterion, not an optional extra.

Then prove the other two defences:

- **Break the deployment, not the code.** Exclude something the app needs at runtime from
  the image, for example the fact-matrix file `editions.py` reads, via `.dockerignore`. The
  PR gate passes (in-process, the file is right there in the repo), and the deployed app
  fails its smoke test in dev or its gate in test. It never reaches prod.
- **Drift an environment.** In the portal, remove *Search Index Data Reader* from test's
  app identity. The nightly drift job, or the next deploy's `check_env`, reports exactly
  that role as missing. Put it back.
- **Prove isolation.** **Check access** for `id-dti-rag-deploy-test` on prod's resources
  shows nothing, and a workflow job that declares `environment: test` can't obtain prod's
  client ID.

---

## The capstone demo runbook

Nine cases, one per failure mode. Demo **live** — a recording invites the question of what
you cut.

| # | Case | Question | Expected |
|---|---|---|---|
| 1 | Temporal | Kitchen flooded 15 Mar 2024, what excess? | **£300**, DTI-2024 §3.4/§10 |
| 2 | Minor version | Cycle stolen 12 Aug 2023, limit? | **£600**, DTI-2023-v1.1 §6.3 |
| 3 | Freshness default | What's the standard excess? | **£350** + "earlier editions differ" |
| 4 | Clause existence | Is communicable disease excluded? | Not in 2022; §9.6 from 2023 |
| 5 | **Table-vs-wording** | Home emergency before 2024? | **"Reserved — not offered"** |
| 6 | Paraphrase | Tiles blew off, rain came in — leak or storm? | **Storm, §4** |
| 7 | Multi-hop numeric | 80-hour storm gap, 2024 vs 2025? | 2 × £300 vs 1 × £350 |
| 8 | Cross-section | Burst pipe collapsed ceiling, which section? | **§3**, not §7.2; £350 |
| 9 | Abstention | 2021 edition excess? / Car stolen? | **Decline**, with reasons |

**Demo advice.** Lead with case 1 shown twice — baseline pipeline (£350, wrong) then the
real one (£300, cited). Nothing else you can show lands as hard.

Case 5 is the one that impresses an insurance audience, because they immediately understand
that reporting cover which was never sold is a real problem, not a technical curiosity.

Case 9 usually surprises people. "It said it doesn't know" reads as a limitation until you
explain that the alternative was inventing a figure for a document that doesn't exist.

---

## The capstone package

1. **The deployed app** — repo + live **prod** endpoint, deployed by the pipeline.
2. **The eval harness and scorecard**, wired into CI as both gates.
3. **An architecture diagram and short design doc**, covering the three policies
   (source-of-truth, edition-selection, abstention) and the framework choices.
4. **The demo runbook.**

Worth adding, because they're what make it credible rather than impressive:

5. **The baseline comparison.** Naive vs final, per category. Your strongest evidence.
6. **The error-analysis log** from Lesson 11 — hypotheses, including the wrong ones.
7. **`FRAMEWORKS.md`** — including any layer where you kept the raw SDK, and why.
8. **The environment story** — `ENVIRONMENTS.md` (runbook and change log),
   `deploy/environments.yaml`, and a diagram of the promotion flow. For an engineering
   audience, "here's how a change reaches prod, and here's what stops a bad one" is often
   the most persuasive page you have.

### The design doc is the deliverable that travels

The code demonstrates you can build it. The design doc demonstrates you know *why* it's
built that way — which is what you're actually being assessed on in a new role. Make sure it
answers:

- Why metadata filtering rather than better embeddings? (With the score-gap evidence.)
- Why section-aware chunking rather than fixed-size?
- Why is edition resolution deterministic code rather than the LLM?
- Why does the wording override the fact matrix? (DTI-014 — name the specific harm.)
- What does the system deliberately refuse to do, and why?
- How do you know test is a faithful rehearsal of prod, and what would you change if
  infrastructure as code were available?

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Conflating traces with the audit log | Sampled traces are useless for audit |
| No prompt version in the log | "Why did it say that?" is unanswerable |
| Gating on an aggregate score | A regression hides behind a win |
| Widening thresholds until CI passes | Gate decommissioned in silence |
| Gate that only links to logs | People learn to bypass it |
| Stored service-principal secret in Actions | The credential risk you avoided everywhere else |
| Never testing the gate | Theatre |
| Default log retention on an audit trail | Evidence gone before the complaint arrives |
| Recorded demo | "What did you cut?" |
| Improvising while building test or prod | The runbook no longer describes your environments |
| Federated credential subject typo | Azure login fails with an error that doesn't point at it |
| Deploy identity with Contributor on the whole resource group | A workflow bug can change anything in that environment |
| PR gate running as a deploy identity | Unreviewed code with rights over a deployed app |
| `check_env` that warns instead of blocking | Prod runs configuration test never passed with |
| Rebuilding the image per environment | Test and prod ran different builds of the same commit |
| Env vars merged, not replaced, on deploy | Deleted settings linger in the running app |
| Prod approval showing no evidence | Approved without being read |
| Leaked PR indexes on test's Search | Index limit hit; unrelated PRs fail |
| One App Insights for several environments | Test traffic in prod's signal |
| Fixing prod in the portal "just this once" | Drift the next deploy blocks on, or silently reverts |

---

## Done when

All nine demo cases pass live **against prod**, **and**:

- test and prod were built from `ENVIRONMENTS.md` without improvising, and every gap you
  found was written back into it
- a commit that breaks retrieval is blocked by the PR gate
- a change that breaks the *deployment* is stopped before prod
- a drifted setting in test is reported by `check_env`
- the test deploy identity has no access to anything in prod

## Check yourself

1. Why are traces and the audit log different artefacts?
2. Why gate per metric rather than on an aggregate?
3. Which metrics should have zero tolerance, and why those?
4. How do you know your gate isn't theatre?
5. Why is the prompt version part of the audit trail?
6. Which single demo case best justifies the whole project to an insurance audience, and
   why that one?
7. Why does the PR gate run the code in-process, while the promotion gate goes through the
   deployed API?
8. What stops a workflow on a feature branch from getting a token for prod? Name both
   locks.
9. You change the `chat` model version in dev's portal. Walk through exactly how that change
   reaches prod, and what stops it reaching prod without passing the gate in test.
10. Why does `check_env` block the deploy rather than just warn?

---

## You've finished

Look back at Lesson 2. The claim was that on this corpus **the metadata schema is the
product** — and that everything else is implementation detail.

If you built this properly, you'll have found that the biggest wins came from the schema,
the chunking and the filters, and that the model, the framework and the prompt mattered far
less than they seemed to at the start. That inversion is the transferable lesson, and it
holds well beyond insurance.
