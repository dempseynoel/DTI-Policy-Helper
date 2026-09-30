# DTI Policy Helper

An edition-aware retrieval-augmented assistant for DavidsTown Insurance (DTI) claims handlers. It answers questions about the HomeShield home-insurance policy wording, picks the edition that governs a claim from the loss date, cites the clause it relied on, and declines when the wording can't answer.

It is built lesson by lesson from `documentation/lessons/`.

## Layout

| Path | What lives there |
|---|---|
| `data/policy_documents/` | The five policy wording PDFs. **Authoritative.** |
| `data/fact_matrix/` | Derived tables. Convenience and evaluation data only; where they disagree with the PDFs, the PDFs win. |
| `data/question_answers/` | The 25-question evaluation bank. Ground truth for scoring, never for answering. |
| `src/dti_rag/` | The application package. Everything that answers a question goes through `pipeline.py`. |
| `evaluation/` | The eval harness. Outside the package so it never ships in the container. |
| `scripts/` | Command-line entry points (smoke test, index load, environment checks). |
| `tests/unit/` | Offline tests. No network, no Azure. |
| `tests/integration/` | Tests against a live environment, selected with `-m integration`. |
| `deploy/` | `environments.yaml`: what each environment must be. `<env>.env`: its non-secret configuration, written by Terraform. |
| `infra/` | Terraform that builds each environment from `deploy/environments.yaml`. |
| `documentation/design/` | The design records each lesson produces. |
| `artifacts/` | Git-ignored, regenerable output: `chunks.jsonl`, eval runs, scorecards. |

## Environments

dev, test and prod, one Azure resource group each, built by Terraform (`infra/`) from `deploy/environments.yaml`. Each apply writes the environment's configuration to `deploy/<env>.env`, which is committed. Application code is promoted dev → test → prod by GitHub Actions, gated by the eval harness.

**Infrastructure is code, configuration is generated, code is promoted.**
