# Lesson 12 — Serve it: API + a claims-handler UI, then deploy to dev

**Objective:** expose the pipeline as a service a human can actually use, and deploy it to
**dev** by hand, once, so you understand every piece Lesson 13's pipeline will automate.

**Deliverable:** the app running in dev at its own URL, answering DTI questions with
citations and edition reasoning. It pulls its image and calls Azure using only its managed
identity. Every portal step you took is added to the runbook, so Lesson 13 can build test
and prod identically. The prod URL comes from Lesson 13's pipeline.

---

## The design principle for this lesson

> **In insurance, auditability matters more than polish.**

A beautiful chat UI that returns a number is worse than a plain one that returns a number,
the clause it came from, the edition that governs, and why that edition was chosen. The
handler's job is to be *accountable* for the answer they give a customer. Your job is to
make that possible.

Everything below follows from that.

---

## The API

FastAPI, streaming `/chat` endpoint wrapping `route → retrieve → generate → guardrails`.

### The response contract

Every response carries:

| Field | Why |
|---|---|
| `answer` | The text |
| `citations[]` | `doc_id`, `section_id`, effective range, page, quoted text |
| `governing_edition` | Which edition was used |
| `edition_reason` | **Why that edition** — "loss date 15 Mar 2024 falls in 1 Jan–31 Dec 2024" |
| `mode` | `answer` \| `ask` \| `abstain` — the client renders these differently |
| `guardrail_status` | Passed / flagged, and what flagged |
| `trace_id` | Ties the response to the Lesson 13 audit log |

`edition_reason` is the field that makes this an insurance tool rather than a chatbot. It's
the difference between "the system says £300" and "the system says £300 because the loss
date falls inside the 2024 edition's effective period, and here's the clause." The first is
unverifiable; the second a handler can check in fifteen seconds.

### Streaming, and what it complicates

Stream the answer text for responsiveness. Two wrinkles:

**Citations arrive at the end.** You can't cite until generation completes. Either stream
text then send a citations event, or buffer. Streaming with a trailing citations event is
better UX and needs a client that handles a structured event stream, not raw text.

**Guardrails run after generation.** So you may stream text and *then* discover it should be
blocked. Options: buffer until the check passes (slower, safe), stream and retract (bad UX,
and the handler may have already read it), or stream and flag. For a first deployment on
financial figures, **buffer.** The latency cost is real; the alternative is a handler acting
on text that was retracted a second later. Note the decision and its cost.

### Endpoints worth having

- `POST /chat` — the main one
- `GET /health` — liveness for Container Apps; must not call Azure OpenAI
- `GET /editions` — list editions with effective ranges. Cheap, and it lets the UI show
  which editions exist, which makes the whole edition concept legible to the handler.

---

## The UI

Minimal. Build one or adapt an Azure RAG chat sample. **Three things must be obvious:**

### 1. Which edition governs, and why

Not buried in a citation. Prominent, near the answer:

```
┌──────────────────────────────────────────────────────┐
│ £300                                                 │
│                                                      │
│ ── Governing edition ──────────────────────────────  │
│ DTI-HOME-PW-2024-v1.0  ·  in force 1 Jan–31 Dec 2024 │
│ Selected because the loss date (15 March 2024) falls │
│ within this edition's effective period.              │
│                                                      │
│ Source: §3.4, p.5  ·  also summarised in §10         │
│ "The standard excess for an escape of water claim    │
│  is £300."                                           │
│                                                      │
│ ⚠ The excess that actually applies is the one shown  │
│   on the customer's schedule.                        │
└──────────────────────────────────────────────────────┘
```

### 2. The citations, with quoted text

Show the quote, not just the reference. A handler who has to open a PDF to check will stop
checking — and an unchecked citation is decoration.

### 3. When the assistant is abstaining

Visually distinct. An abstention that looks like an answer will be read as an answer. Same
for `ask` — a clarifying question must clearly be a question, not a hedge.

The schedule caveat deserves permanent placement. The wording says throughout that the
schedule takes priority; the UI should too.

---

## Deploy — to dev, in this lesson

Containerise → **Azure Container Apps**, one per environment. You deploy to dev by hand
here. From Lesson 13 on, the pipeline deploys to every environment, and nobody changes the
running app in the portal again.

### Build once, promote by digest

- **One shared container registry** serves all three environments. Each commit's image is
  built **once**, tagged with the git SHA, and every environment runs that same **digest**
  (`…@sha256:…`). Never promote a mutable tag like `latest`: a tag can be re-pointed between
  the test deploy and the prod deploy, and a digest can't.
- **Bake the git SHA into the image** (build argument → environment variable) and put it
  in every trace and audit record. "Which code gave this answer?" should never need
  guesswork.
- **The image contains no environment.** `.dockerignore` excludes `.env`, `deploy/`,
  `evaluation/`, `artifacts/` and `Documentation/`. Configuration arrives at runtime as
  environment variables. An image with `deploy/dev.env` baked in carries dev's endpoints into
  prod.

### Portal steps

**1. Shared container registry (once).** Container registries → **Create**: resource group
`rg-dti-rag-shared`, name `crdtiragshared<suffix>`, SKU **Basic**. Leave the admin user
**disabled**; pulls use managed identity. Managed-identity pulls need the registry to accept
ARM-audience tokens. Check in Cloud Shell with
`az acr config authentication-as-arm show -r <registry>`, and enable it if it's off.

Give **yourself** *AcrPush* on the registry for now, so you can push dev images from your
laptop (`az acr build`). Lesson 13 hands that job to a build identity, and you remove your
own AcrPush then.

**2. The app's identity.** Managed Identities → **Create**: resource group `rg-dti-rag-dev`,
name `id-dti-rag-app-dev`.

Make it **user-assigned, not system-assigned.** A user-assigned identity exists *before* the
app does, so you can grant its roles and let them propagate before the first revision tries
to pull an image or call Search. A system-assigned identity is born with the app, and the
first revisions fail while its roles catch up.

Assign its roles on each target resource (**Access control (IAM)** → **Add role
assignment** → Members: *Managed identity*):

| Role | On |
|---|---|
| AcrPull | The shared registry |
| Foundry User | dev's Foundry resource |
| **Search Index Data Reader** | dev's Search service |

**3. Create the container app with the quickstart image.** Container Apps → **Create**:

| Tab | Setting | Value |
|---|---|---|
| Basics | Resource group | `rg-dti-rag-dev` |
| Basics | Container app name | `ca-dti-rag-dev` |
| Basics | Region | Your region |
| Basics | Container Apps environment | **Create new**: `cae-dti-rag-dev`, logging to `log-dti-rag-dev` |
| Container | Use quickstart image | **On**; you replace it in step 5 |
| Ingress | Ingress | Enabled, accepting traffic from anywhere (see step 7) |

Starting from the quickstart image is Microsoft's documented portal path for private-registry
pulls with a user-assigned identity. The app has to exist before you can attach the identity
that pulls your image.

**4. Attach the identity.** The app → **Identity** → **User assigned** → **Add** →
`id-dti-rag-app-dev`.

**5. Switch to your image.** Push an image first (`az acr build --registry <registry>
--image dti-rag:<git-sha> .`). Then in the app → **Application → Containers → Edit and
deploy** → select the container:

| Setting | Value |
|---|---|
| Image source | Azure Container Registry |
| Authentication | **Managed identity** → `id-dti-rag-app-dev` |
| Registry / Image / Image tag | The shared registry, `dti-rag`, your git SHA |
| Environment variables | Every line of `deploy/dev.env` |
| Health probes | Liveness and readiness on `GET /health` |

**Save**, then **Create** the revision. Then set **Ingress → Target port** to your app's port;
the quickstart used 80.

**6. Scale.** The app → **Application → Scale**:

| | dev | test | prod |
|---|---|---|---|
| Min replicas | 0 | 0 | 1 or more |
| Max replicas | 1 | 2 | Sized against prod's TPM |

Scale-to-zero saves money in dev and test, at the price of a cold start. Lesson 13's gate
absorbs that by polling `/health` until the app is warm.

**7. Authentication: test and prod; optional in dev.** The app → **Settings →
Authentication** → **Add identity provider** → **Microsoft**, with unauthenticated requests
rejected. This creates an app registration in Entra ID, so you need permission to create
one in your tenant. It also means the pipeline's post-deploy tests (Lesson 13) must request a
token for that registration, so allow the pipeline identity when you configure the provider.
If you can't create app registrations, restrict ingress by IP instead, and record it as a
known gap in `GUARDRAILS.md`.

**Record every step, with test and prod values, in `ENVIRONMENTS.md`.** Lesson 13 builds
test and prod from those notes and nothing else.

### Managed identity, end to end

`id-dti-rag-app-<env>` has exactly three roles, all in its own environment:

- *AcrPull* on the shared registry
- *Foundry User* on the Foundry resource. It covers chat, embeddings and the Content
  Safety groundedness call from Lesson 11. The narrower *Cognitive Services OpenAI User*
  wouldn't cover that last one.
- **`Search Index Data Reader`** on Search. *Reader*, not Contributor: the app queries and
  never writes. Don't copy your dev roles onto the app's identity.

Check it: the identity → **Azure role assignments** shows exactly those three, and **Check
access** on the *other* environments' resources shows nothing.

Because you used `DefaultAzureCredential` since Lesson 1, this is configuration, not a
refactor. That's the payoff.

### Config and secrets

Config via environment variables, and the variables are the contents of `deploy/<env>.env`.
In dev you typed them once in step 5. From Lesson 13, the pipeline sets them on every deploy,
**replacing** rather than merging, so a variable deleted from the file disappears from the
app instead of lingering.

Secrets, if any remain, go in Key Vault, referenced by the Container App through its
identity (which then needs *Key Vault Secrets User*) rather than copied into env. With
managed identity you should have none: no model keys, no Search keys. If a production
environment variable holds a key, something went wrong earlier.

### Sizing and scaling

- **Scale to zero** is tempting for a demo but gives a brutal cold start on the first
  question. For a handler-facing tool in prod, minimum one replica.
- **Set a max.** Runaway scaling against a TPM-limited model deployment produces throttling,
  not throughput — and a bill.
- **Health probe must not call the model.** A probe that burns tokens is a probe that costs
  money while scaling.

### After this lesson, the portal is read-only for the app

From Lesson 13 the pipeline owns the running image and its environment variables in every
environment. A change made through **Edit and deploy** in the portal either gets overwritten
by the next deploy or, worse, doesn't, and the app quietly differs from what's in git.
Configuration changes go through `deploy/<env>.env` and a pull request.

### Optional: the same thing as a Foundry Agent

Worth doing to compare hosting models. Note what you give up (control over the pipeline,
your guardrail layer) against what you gain (managed hosting, built-in tracing). Another
entry for `FRAMEWORKS.md`.

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| Citations without quoted text | Nobody checks them |
| No `edition_reason` | Handler can't verify the most important decision |
| Abstention rendered like an answer | Read as an answer |
| Streaming past the guardrail check | Handler reads retracted text |
| Health probe calling Azure OpenAI | Cost and throttling per probe |
| `Search Index Data Contributor` on the app identity | Over-privileged; the app never writes |
| Scale to zero | Cold start on the first real question |
| No max replicas | Throttling and a surprise bill |
| Settings loaded per request | Latency, and credential churn |
| Secrets copied into env | Undoes Lesson 1 |
| System-assigned identity for the app | First revisions can't pull the image or call Search while roles propagate |
| Registry refuses managed-identity pulls | ARM-audience tokens disabled on the registry |
| Promoting a tag instead of a digest | Test and prod ran different images under the same name |
| `deploy/*.env` or `.env` inside the image | One environment's endpoints baked into another |
| Editing the app in the portal after Lesson 13 | Drift from git; silently overwritten, or silently not |
| Target port left at the quickstart's 80 | Revision "running" but every request fails |

---

## Done when

A colleague can ask *"kitchen flooded 15 March 2024, what's the excess?"* and get:

> **£300**, per DTI-HOME-PW-2024-v1.0 §3.4 (also §10), in force 1 Jan–31 Dec 2024 —
> selected because the loss date falls within that period. *The excess that applies is the
> one shown on the schedule.*

with the citation and quoted clause visible without clicking, in **dev**.

And: the dev app pulls its image and calls Azure using only `id-dti-rag-app-dev`. That
identity holds exactly its three roles, and every portal step is in `ENVIRONMENTS.md` with
test and prod values.

## Check yourself

1. Why is `edition_reason` a required field rather than a nice-to-have?
2. What breaks if you stream the answer before the guardrail check completes?
3. Which Search role does the app identity need, and why not the one you gave yourself?
4. Why must `/health` not call the model?
5. Why show quoted text rather than just a section reference?
6. Your UI renders `ask` and `answer` identically. What goes wrong?
7. Why a user-assigned identity for the app rather than a system-assigned one?
8. Why promote an image digest rather than a tag?
9. Why must the image contain no environment-specific configuration?

---

**Next:** [Lesson 13 — Observability, eval-gated CI/CD, and the capstone](Lesson13.md)
