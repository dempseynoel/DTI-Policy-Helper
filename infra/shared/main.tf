# Built once, before any environment: the shared resource group, the container registry every
# environment pulls from, the pipeline identities that aren't tied to one environment, and the
# subscription's resource provider registrations and audit policies. Apply this first; the
# environments look these up.

terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
  }

  # State is a local file in this folder (git-ignored). See infra/README.md.
}

locals {
  config = yamldecode(file("${path.root}/../../deploy/environments.yaml"))
  region = local.config.shared.region
  repo   = local.config.github_repository

  tags = {
    environment = "shared"
    workload    = "dti-rag"
    owner       = local.config.owner
  }
}

provider "azurerm" {
  subscription_id = local.config.subscription_id
  features {}
}

data "azurerm_client_config" "current" {}
data "azurerm_subscription" "current" {}

# Registration is per subscription. The azurerm provider registers most namespaces itself, but
# not Microsoft.App: without this, every environment's Container Apps environment fails with
# MissingSubscriptionRegistration.
resource "azurerm_resource_provider_registration" "app" {
  name = "Microsoft.App"
}

resource "azurerm_resource_group" "shared" {
  name     = local.config.registry.resource_group
  location = local.region
  tags     = local.tags
}

resource "azurerm_consumption_budget_resource_group" "shared" {
  name              = "budget-dti-rag-shared"
  resource_group_id = azurerm_resource_group.shared.id
  amount            = local.config.registry.budget
  time_grain        = "Monthly"

  # A budget has to start on the first of the current month: take it from the clock once.
  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  dynamic "notification" {
    for_each = [
      { threshold = 50, type = "Actual" },
      { threshold = 80, type = "Actual" },
      { threshold = 100, type = "Actual" },
      { threshold = 100, type = "Forecasted" },
    ]
    content {
      enabled        = true
      operator       = "GreaterThan"
      threshold      = notification.value.threshold
      threshold_type = notification.value.type
      contact_emails = local.config.budget_emails
    }
  }

  lifecycle {
    ignore_changes = [time_period]
  }
}

# ---- Container registry (Lesson 12) -----------------------------------------------------

# One registry for every environment: an image is built once and promoted by digest.
resource "azurerm_container_registry" "shared" {
  name                = local.config.registry.name
  location            = azurerm_resource_group.shared.location
  resource_group_name = azurerm_resource_group.shared.name
  sku                 = "Basic"
  admin_enabled       = false # no registry passwords; pulls and pushes use Entra ID
  tags                = local.tags

  # Container Apps pull with a managed identity, which needs ARM-audience tokens accepted.
  azuread_authentication_as_arm_policy_enabled = true
}

# Building an image: `az acr build` runs an ACR Task in the registry (Tasks Contributor) and
# the task pushes the result (AcrPush).
locals {
  build_roles = ["AcrPush", "Container Registry Tasks Contributor"]
}

# You build dev images by hand in Lesson 12 (`make image`). Lesson 13 turns this off
# (human_push_allowed), and only the build identity builds.
resource "azurerm_role_assignment" "me_build" {
  for_each = local.config.registry.human_push_allowed ? toset(local.build_roles) : toset([])

  scope                = azurerm_container_registry.shared.id
  role_definition_name = each.key
  principal_id         = data.azurerm_client_config.current.object_id
  principal_type       = "User"
}

# ---- Pipeline identities that span environments (Lesson 13) -----------------------------

# Each one is trusted by exactly one kind of GitHub job, through a federated credential: no
# secrets. The per-environment deploy identities are created by infra/<env>.
locals {
  identities = {
    build = { name = local.config.pipeline_identities.build, subject = "ref:refs/heads/main" }
    eval  = { name = local.config.pipeline_identities.eval, subject = "environment:pr-eval" }
    drift = { name = local.config.pipeline_identities.drift, subject = "environment:drift" }
  }
}

resource "azurerm_user_assigned_identity" "pipeline" {
  for_each = local.identities

  name                = each.value.name
  location            = azurerm_resource_group.shared.location
  resource_group_name = azurerm_resource_group.shared.name
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "pipeline" {
  for_each = local.repo != "" ? local.identities : {}

  name                      = "github-${each.key}"
  user_assigned_identity_id = azurerm_user_assigned_identity.pipeline[each.key].id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${local.repo}:${each.value.subject}"
}

# build: builds and pushes the one image per commit. Its roles on the environments: none.
resource "azurerm_role_assignment" "build" {
  for_each = toset(local.build_roles)

  scope                = azurerm_container_registry.shared.id
  role_definition_name = each.key
  principal_id         = azurerm_user_assigned_identity.pipeline["build"].principal_id
  principal_type       = "ServicePrincipal"
}

# drift: Reader here; each environment gives it Reader on its own resource group.
resource "azurerm_role_assignment" "drift_reader" {
  scope                = azurerm_resource_group.shared.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.pipeline["drift"].principal_id
  principal_type       = "ServicePrincipal"
}

# eval: its roles are on test's Search and models, given by infra/test.

# ---- Azure Policy, audit only -----------------------------------------------------------

# Independent evidence that key access stays off, including on anything built outside
# Terraform. Audit, not Deny: it reports without blocking an emergency fix.
locals {
  audit_policies = {
    "audit-ai-services-local-auth" = {
      definition = "71ef260a-8f18-47b7-abcb-62d0673d94dc"
      display    = "Azure AI Services resources should have key access disabled (disable local authentication)"
    }
    "audit-search-local-auth" = {
      definition = "6300012e-e9a4-4649-b41f-a85f5c43be91"
      display    = "Azure AI Search services should have local authentication methods disabled"
    }
    "audit-storage-shared-key" = {
      definition = "8c6a50c6-9ffd-4ae7-986f-5fa6111f9a54"
      display    = "Storage accounts should prevent shared key access"
    }
  }
}

resource "azurerm_subscription_policy_assignment" "audit" {
  for_each = local.audit_policies

  name                 = each.key
  display_name         = each.value.display
  subscription_id      = data.azurerm_subscription.current.id
  policy_definition_id = "/providers/Microsoft.Authorization/policyDefinitions/${each.value.definition}"
  parameters           = jsonencode({ effect = { value = "Audit" } })
}

# ---- For the GitHub repository variables (Lesson 13) ------------------------------------

output "github_variables" {
  description = "Repository variables: Settings → Secrets and variables → Actions → Variables."
  value = {
    AZURE_TENANT_ID       = data.azurerm_client_config.current.tenant_id
    AZURE_SUBSCRIPTION_ID = local.config.subscription_id
    ACR_NAME              = azurerm_container_registry.shared.name
    BUILD_CLIENT_ID       = azurerm_user_assigned_identity.pipeline["build"].client_id
  }
}

output "environment_client_ids" {
  description = "AZURE_CLIENT_ID for the pr-eval and drift GitHub environments."
  value = {
    pr-eval = azurerm_user_assigned_identity.pipeline["eval"].client_id
    drift   = azurerm_user_assigned_identity.pipeline["drift"].client_id
  }
}
