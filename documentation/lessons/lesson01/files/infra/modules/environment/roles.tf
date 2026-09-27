# Every role is scoped to one resource (or one storage container), never the resource group,
# except Reader.

# ---- Search's identity ------------------------------------------------------------------

# The index's vectorizer calls the embed deployment as Search. Every environment.
resource "azurerm_role_assignment" "search_openai_user" {
  scope                = azurerm_cognitive_account.foundry.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_search_service.this.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

# Only Lesson 04's dev-only indexer experiment reads blobs as Search.
resource "azurerm_role_assignment" "search_blob_reader" {
  count = local.env == "dev" ? 1 : 0

  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_search_service.this.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

# ---- You (whoever runs terraform apply) -------------------------------------------------

# dev only. Owner has no data actions: without these you can't call a model, load an index
# or upload a blob. In test and prod you hold none, and check_env fails if you do.
locals {
  my_roles = local.e.human_data_roles_allowed ? {
    foundry_user       = { scope = azurerm_cognitive_account.foundry.id, role = "Foundry User" }
    search_contributor = { scope = azurerm_search_service.this.id, role = "Search Service Contributor" }
    search_index_data  = { scope = azurerm_search_service.this.id, role = "Search Index Data Contributor" }
    storage_blob_data  = { scope = azurerm_storage_account.this.id, role = "Storage Blob Data Contributor" }
  } : {}
}

resource "azurerm_role_assignment" "me" {
  for_each = local.my_roles

  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = data.azurerm_client_config.current.object_id
  principal_type       = "User"
}

# ---- The app's identity (Lesson 12) -----------------------------------------------------

# Exactly these four; check_env fails on anything missing or anything writable.
locals {
  app_roles = {
    acr_pull     = { scope = data.azurerm_container_registry.shared.id, role = "AcrPull" }
    foundry_user = { scope = azurerm_cognitive_account.foundry.id, role = "Foundry User" }
    search_read  = { scope = azurerm_search_service.this.id, role = "Search Index Data Reader" }
    audit_write  = { scope = local.audit_scope, role = "Storage Blob Data Contributor" }
  }
}

resource "azurerm_role_assignment" "app" {
  for_each = local.app_roles

  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}

# ---- The pipeline's deploy identity for this environment (Lesson 13) --------------------

# In the shared resource group with the other pipeline identities, but owned by this
# environment: it has roles here and nowhere else.
resource "azurerm_user_assigned_identity" "deploy" {
  name                = local.e.deploy_identity
  location            = local.shared.region
  resource_group_name = local.cfg.registry.resource_group
  tags                = local.tags
}

# Only a GitHub job that declares `environment: <env>` gets a token for this identity.
resource "azurerm_federated_identity_credential" "deploy" {
  count = local.cfg.github_repository != "" ? 1 : 0

  name                      = "github-${local.env}"
  user_assigned_identity_id = azurerm_user_assigned_identity.deploy.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${local.cfg.github_repository}:environment:${local.env}"
}

locals {
  deploy_roles = {
    rg_reader         = { scope = azurerm_resource_group.this.id, role = "Reader" }                        # check_env; model versions
    shared_reader     = { scope = local.shared_rg_id, role = "Reader" }                                    # check_env reads the registry's roles
    cae_contributor   = { scope = azurerm_container_app_environment.this.id, role = "Contributor" }        # deploy a revision
    foundry_user      = { scope = azurerm_cognitive_account.foundry.id, role = "Foundry User" }            # embeddings at index load; the judge
    search_service    = { scope = azurerm_search_service.this.id, role = "Search Service Contributor" }    # create the index
    search_index_data = { scope = azurerm_search_service.this.id, role = "Search Index Data Contributor" } # load it
    audit_reader      = { scope = local.audit_scope, role = "Storage Blob Data Reader" }                   # the gate reads answers back
  }
}

resource "azurerm_role_assignment" "deploy" {
  for_each = local.deploy_roles

  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
  principal_type       = "ServicePrincipal"
}

# Contributor on the app itself, never the resource group.
resource "azurerm_role_assignment" "deploy_app" {
  count = local.app_enabled ? 1 : 0

  scope                = azurerm_container_app.this[0].id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
  principal_type       = "ServicePrincipal"
}

# ---- Shared pipeline identities (created in infra/shared) -------------------------------

# The nightly drift check reads every environment and can change nothing.
data "azurerm_user_assigned_identity" "drift" {
  name                = local.cfg.pipeline_identities.drift
  resource_group_name = local.cfg.registry.resource_group
}

resource "azurerm_role_assignment" "drift_reader" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Reader"
  principal_id         = data.azurerm_user_assigned_identity.drift.principal_id
  principal_type       = "ServicePrincipal"
}

# The PR gate builds a throwaway index per pull request on this environment's Search (test).
# It can touch Search and the models, and nothing that serves the app.
data "azurerm_user_assigned_identity" "eval" {
  count = local.e.pr_eval ? 1 : 0

  name                = local.cfg.pipeline_identities.eval
  resource_group_name = local.cfg.registry.resource_group
}

locals {
  eval_roles = local.e.pr_eval ? {
    search_service    = { scope = azurerm_search_service.this.id, role = "Search Service Contributor" }
    search_index_data = { scope = azurerm_search_service.this.id, role = "Search Index Data Contributor" }
    foundry_user      = { scope = azurerm_cognitive_account.foundry.id, role = "Foundry User" }
    foundry_reader    = { scope = azurerm_cognitive_account.foundry.id, role = "Reader" }
  } : {}
}

resource "azurerm_role_assignment" "eval" {
  for_each = local.eval_roles

  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = data.azurerm_user_assigned_identity.eval[0].principal_id
  principal_type       = "ServicePrincipal"
}
