# DTI Policy Helper

A question-answering assistant for claims handlers at DavidsTown Insurance (DTI). A handler asks a question about the HomeShield home-insurance policy, usually about a particular claim. The assistant works out which edition of the policy wording was in force on the date of the loss and answers from that edition only. It cites the clause and quotes the text it relied on. When the question is ambiguous it asks for clarification, and when the wording doesn't cover it, it says so rather than guess.

It runs on Azure: Azure OpenAI models in a Foundry resource, Azure AI Search for retrieval, and Container Apps for the API and web UI. Terraform builds three environments (dev, test and prod), and GitHub Actions promotes changes to prod only after they pass an evaluation gate.

The repository is also a course. `documentation/lessons/` holds 14 lessons that build the application, starting from nothing but the policy PDFs and a question bank. Each lesson adds its files to the project root, so the root holds the project as far as you've got through the lessons.

## Why a general chatbot gets this wrong

DTI has issued five editions of the HomeShield wording:

| Edition | In force |
|---|---|
| `DTI-HOME-PW-2022-v1.0` | 1 January 2022 to 31 December 2022 |
| `DTI-HOME-PW-2023-v1.0` | 1 January 2023 to 30 June 2023 |
| `DTI-HOME-PW-2023-v1.1` | 1 July 2023 to 31 December 2023 |
| `DTI-HOME-PW-2024-v1.0` | 1 January 2024 to 31 December 2024 |
| `DTI-HOME-PW-2025-v1.0` | 1 January 2025 to 31 December 2025 (current) |

The editions read almost the same, but the figures change. The standard excess is £250 until the end of 2023, £300 in 2024 and £350 in 2025. A simple retrieval setup (the naive baseline in Lesson 05) is asked, "A kitchen flooded on 15 March 2024. What excess applies?" It answers £350, because the 2025 clause matches the question as closely as the 2024 one does. The right answer is £300. If a handler passes the wrong figure to a customer, that's a complaint, and in a regulated firm, possibly a lot more.

The design follows from that:

- Code chooses the edition from the loss date. The model only extracts facts from the question, such as dates and any edition mentioned. A tested function then decides which edition governs.
- Search is filtered to that edition before results are ranked, so near-identical clauses from other years never compete.
- Every figure comes with a citation: edition, section, page and the quoted text. A separate check blocks any £ amount or section number that isn't in the retrieved wording. Calculations are shown and checked in code.
- When an answer would be a guess, the assistant asks or declines instead. With no date and editions that disagree, it asks. It declines when no edition covers the date (any loss after 31 December 2025, since there's no 2026 wording) or when the question falls outside the policy.
- Each answer is written to an audit log, with the edition, why that edition was chosen, and the context retrieved, so it can be explained later.

## How a question is answered

```
question
   │
   ▼
clean()        control characters removed, length capped                         Lesson 11
   │
   ▼
route()        the LLM extracts the facts (loss date, editions named, scope);
   │           code picks the edition(s) and the mode: answer, ask or abstain     Lesson 07
   ▼
retrieve()     hybrid keyword + vector search, semantic rerank,
   │           filtered to one edition at a time                                  Lesson 06
   ▼
generate()     one pass per edition, structured citations, arithmetic checked     Lesson 08
   │
   ▼
guardrails()   every £ figure and section number must appear in the retrieved text  Lesson 11
   │
   ▼
answer + citations + governing edition + reason ──► API and UI (12) ──► audit log and traces (13)
```

The whole sequence lives in `src/dti_rag/pipeline.py`. The API, the evaluation harness and the command-line scripts all call it, so the code that gets scored is the code that ships.

## Repository layout

| Path | Contents | Added in lesson |
|---|---|---|
| `data/policy_documents/` | The five policy wording PDFs. These are the source of truth. | 00 |
| `data/fact_matrix/` | Per-edition fact tables, for convenience and evaluation only. Where they disagree with the PDFs, the PDFs are right. | 00 |
| `data/question_answers/` | The 25-question evaluation bank. Used to score answers, never to produce them. | 00 |
| `documentation/lessons/` | The course, plus `apply_lesson.sh` | 00 |
| `src/dti_rag/` | The application package, with one subpackage per stage | 01 |
| `scripts/` | Command-line tools: smoke tests, `ask.py`, environment checks | 01 |
| `tests/unit/` | Unit tests. They run offline: no network, no Azure. | 01 |
| `tests/integration/` | Tests against a live environment | 06 |
| `deploy/` | `environments.yaml` defines every environment. `<env>.env` holds each environment's configuration, written by Terraform. | 01 |
| `infra/` | Terraform: one folder per environment, plus `shared` | 01 |
| `documentation/design/` | Design records. Most lessons add one. | 02 |
| `evaluation/` | The evaluation harness. It sits outside the package so it never ships in the container. | 05 |
| `.github/workflows/` | CI, the pull-request evaluation gate, deployment and the nightly drift check | 13 |
| `artifacts/` | Generated output: chunks, eval runs, scorecards. Git-ignored and rebuilt by the code. | 03 |

## Working through the course

### What you need

- Python 3.12 (3.11 also works) and [uv](https://docs.astral.sh/uv/)
- Terraform 1.9 or later
- The Azure CLI, signed in with `az login` as an Owner of the subscription (Terraform creates role assignments)
- Model quota in UK South for `gpt-4.1-mini` and `text-embedding-3-large` (Standard deployment type)

You don't need Docker. Container images are built in Azure with `az acr build`.

**Cost.** One Azure AI Search unit on the Basic tier costs about £50 a month, whether or not you use it. Dev has a budget alert at £100 a month. Running dev, test and prod together costs roughly £220 a month before any model usage. Lesson 01 builds only dev. Test and prod wait until Lesson 13, and `terraform destroy` removes them when you've finished.

### Steps

1. Install the dependencies and pre-commit hooks:

   ```bash
   make setup
   ```

2. Read [Lesson 00](documentation/lessons/lesson00/README.md). It explains what you're building and why it's built this way.

3. For each lesson, in order:

   - Read the lesson's README. Lessons 02, 03 and 07 suggest you write the core function yourself before you look at the supplied version, and you'll get more out of them if you do.
   - Apply the lesson's files and run the tests:

     ```bash
     documentation/lessons/apply_lesson.sh 03 --dry-run   # list what would change
     documentation/lessons/apply_lesson.sh 03
     make test
     ```

   - Do the Azure steps the lesson describes, and check its "Done when" list.

Applying lessons 00 to 13 in order reproduces the finished project, and no lesson deletes a file. The script never overwrites the files you edit yourself (`deploy/environments.yaml` and `documentation/design/*.md`). If one of those already exists, it prints a `diff` command so you can compare. It does overwrite every other file, including this README if you apply Lesson 00 again.

Before you run `terraform apply` in Lesson 01, edit `deploy/environments.yaml`. Set your own `subscription_id`, `owner` and `budget_emails`. Some resource names (storage, Search, Key Vault, Foundry and the registry) must be unique across Azure, so change any that are already taken.

[documentation/lessons/README.md](documentation/lessons/README.md) lists every lesson and what each one produces.

## Commands

Commands that talk to Azure need `ENV` set to `dev`, `test` or `prod`. There's deliberately no default, so forgetting `ENV` can't send a command to the wrong environment.

| Command | What it does | From lesson |
|---|---|---|
| `make setup` | Install dependencies and pre-commit hooks | 01 |
| `make test` | Run the unit tests (offline) | 01 |
| `make lint` | Run Ruff | 01 |
| `make smoke ENV=dev` | Call the chat and embedding models in an environment | 01 |
| `make chunks` | Parse the PDFs into clause-level chunks in `artifacts/` | 03 |
| `make index ENV=dev` | Create and load the search index | 04 |
| `make baseline ENV=dev` | Run the naive pipeline over the question bank | 05 |
| `make test-integration ENV=dev` | Run the integration tests against a live environment | 06 |
| `make ask ENV=dev Q="..."` | Ask one question and print every decision made | 08 |
| `make eval ENV=dev` | Score the whole question bank. Add `REF=<scorecard>` to compare against a reference. | 10 |
| `make run ENV=dev` | Start the API and web UI on http://localhost:8000 | 12 |
| `make image ACR=crdtirag` | Build the container image in Azure Container Registry (dev only) | 12 |

For example:

```bash
make ask ENV=dev Q="A kitchen flooded on 15 March 2024. What excess applies?"
```

This prints the mode (answer, ask or abstain), the governing edition and why it was chosen, and the search filter used. Then come the answer and each citation, with its quoted text.

## Environments and deployment

Each environment has its own resource group. A fourth group, `rg-dti-rag-shared`, holds the container registry and the pipeline identities. Terraform builds all of it from `deploy/environments.yaml`. Anything that affects behaviour must be identical in every environment: the models and their versions, the API versions, the search configuration. Only capacity, access and protection can differ. That way a pass in test tells you something about prod.

There are no API keys anywhere. Everything authenticates through Entra ID: `az login` on your machine, OIDC federation in GitHub Actions and managed identities in Azure. Key access is switched off on every resource. Because of that, `deploy/<env>.env` contains no secrets and is committed. Terraform rewrites it on every apply.

From Lesson 13, GitHub Actions runs the release process:

- Every pull request runs lint and the unit tests, and scores the question bank against a reference scorecard.
- A merge to `main` builds one image and promotes it through dev, then test, then prod. In test, the question bank is scored again through the deployed API. Prod needs a manual approval.
- A nightly job compares each live environment with `environments.yaml` and reports any drift.

[infra/README.md](infra/README.md) covers how to change infrastructure. It also lists the known gaps compared with a real regulated deployment: public endpoints, one subscription for all three environments, and local Terraform state.

## The evaluation bank

`data/question_answers/` holds 25 questions. Each one tests a specific way the assistant can go wrong, for example:

- picking the wrong edition;
- trusting a change summary that leaves changes out;
- treating a section marked "Reserved" as cover;
- getting multi-step arithmetic wrong;
- answering a question the wording can't answer.

Each question records a reference answer and the documents and sections that must be retrieved. It also lists strings the answer must contain, strings that would show the wrong edition was used, and the behaviour expected. The field definitions and scoring notes are in [data/question_answers/README.md](data/question_answers/README.md).
