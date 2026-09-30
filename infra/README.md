# Infrastructure

Everything this project runs on in Azure is built by Terraform from this folder. Every value comes from **`deploy/environments.yaml`**, which the pipeline's drift check (`scripts/check_env.py`) reads too, so the thing that builds an environment and the thing that checks it can't disagree.

```text
infra/
├── modules/environment/   one environment: every resource, every role
├── shared/                rg-dti-rag-shared: registry, pipeline identities, audit policies
├── dev/  test/  prod/     one folder = one state file = one environment
└── README.md
```

A folder per environment means `terraform apply` in `infra/dev` can't touch prod, whatever you type. The three folders differ only in which entry of `environments.yaml` they build.

## Build an environment

You need Terraform 1.9 or later, and `az login` as an Owner of the subscription (Terraform creates role assignments). **Apply `shared` first**: every environment looks up the registry and the pipeline identities it creates.

```bash
cd infra/shared && terraform init && terraform plan -out=tfplan && terraform apply tfplan
cd ../dev       && terraform init && terraform plan -out=tfplan && terraform apply tfplan
git add deploy/dev.env    # written by the apply: the app's configuration for dev
```

`test` and `prod` are the same commands in their folders.

- **Plan to a file and apply that file**, so you apply exactly what you read.
- **Read the plan.** `+` and `~` are normal. **`-/+` (replace) or `-` (destroy) on something that holds data means stop**: replacing the Foundry resource deletes its deployments, and replacing Search deletes the index.
- **Commit `.terraform.lock.hcl`** in each folder. **Never commit `terraform.tfstate`.**

## Change something

1. Edit `deploy/environments.yaml` (or the module, for a new kind of resource).
2. Apply `infra/dev`. Try it.
3. Pull request with the YAML and the regenerated `deploy/dev.env`. Merge.
4. Apply `infra/test`, then `infra/prod`, committing their `.env` files if they changed. From Lesson 13, the pipeline's `check_env` stops a deploy to any environment you haven't applied yet, so test can't be skipped on the way to prod.

**Never change a setting in the portal.** The next `apply` reverts it, and until then `check_env` blocks deploys. Look in the portal; change things here.

## Tear down

`terraform destroy` in an environment's folder, and in `shared` last. dev and test purge their soft-deleted Foundry resource and Key Vault on destroy, so a rebuild can reuse the names. prod doesn't, and its delete lock stops the destroy: set `delete_lock: false`, apply, then destroy. Its Key Vault has purge protection, so its name stays reserved for 90 days.

## Not in Terraform

| What | Why | Where |
|---|---|---|
| Container App authentication (test, prod) | It creates an Entra ID app registration and, for browser sign-in, a client secret: identity administration, not an Azure resource | Lesson 13, in the portal |
| GitHub environments and variables | GitHub, not Azure. `terraform output` in `shared` and each environment gives every value | Lesson 13 |
| Alert rules and the workbook | Their thresholds come from real telemetry | Lesson 13, `documentation/design/OBSERVABILITY.md` |
| Search indexes | Data, not infrastructure: the schema is versioned in code and the pipeline loads it | `src/dti_rag/search/` (Lesson 04) |

## Known gaps

What a real regulated deployment would do differently, and why it's accepted here.

| Gap | Why accepted | What real prod would do |
|---|---|---|
| Public endpoints on every resource | Course simplicity and cost | Private endpoints; public access off |
| One subscription for all three environments | Cost; one person | A subscription each, under a management group |
| Terraform run from a laptop, as a subscription Owner | One person; no infrastructure pipeline | `plan` on every pull request, `apply` from a pipeline identity after review; no standing Owner (PIM) |
| State in a local file per folder | Nothing to set up | Remote state in a locked-down storage account, with state locking |
