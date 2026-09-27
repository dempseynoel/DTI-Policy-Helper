# A Foundry resource (kind AIServices with project management on), not an Azure AI hub.
resource "azurerm_cognitive_account" "foundry" {
  name                = local.e.foundry
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  kind                = "AIServices"
  sku_name            = "S0"

  # The subdomain makes the endpoints https://<name>.openai.azure.com/ and
  # https://<name>.cognitiveservices.azure.com/.
  custom_subdomain_name         = local.e.foundry
  project_management_enabled    = true
  public_network_access_enabled = true # known gap: infra/README.md

  # The setting the portal can't make.
  local_auth_enabled = !local.shared.foundry_local_auth_disabled

  network_acls {
    default_action = "Allow"
  }

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

resource "azurerm_cognitive_account_project" "this" {
  name                 = local.shared.foundry_project
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  location             = azurerm_resource_group.this.location
  display_name         = local.shared.foundry_project

  identity {
    type = "SystemAssigned"
  }
}

# Deployments are named by role, never by model. What each one serves comes from `shared`
# (must match); its TPM comes from this environment's `capacity` (may differ).
# One after the other: the service rejects concurrent deployment changes on one account (409).
locals {
  models   = local.shared.deployments
  capacity = local.e.capacity
}

resource "azurerm_cognitive_deployment" "chat" {
  name                   = "chat"
  cognitive_account_id   = azurerm_cognitive_account.foundry.id
  version_upgrade_option = local.models.chat.upgrade
  rai_policy_name        = local.models.chat.content_filter

  model {
    format  = "OpenAI"
    name    = local.models.chat.model
    version = local.models.chat.version
  }

  sku {
    name     = local.models.chat.sku
    capacity = local.capacity.chat
  }
}

resource "azurerm_cognitive_deployment" "embed" {
  name                   = "embed"
  cognitive_account_id   = azurerm_cognitive_account.foundry.id
  version_upgrade_option = local.models.embed.upgrade
  rai_policy_name        = local.models.embed.content_filter

  model {
    format  = "OpenAI"
    name    = local.models.embed.model
    version = local.models.embed.version
  }

  sku {
    name     = local.models.embed.sku
    capacity = local.capacity.embed
  }

  depends_on = [azurerm_cognitive_deployment.chat]
}

# Lesson 10. dev and test only: prod never judges its own answers.
resource "azurerm_cognitive_deployment" "judge" {
  count = lookup(local.capacity, "judge", 0) > 0 ? 1 : 0

  name                   = "judge"
  cognitive_account_id   = azurerm_cognitive_account.foundry.id
  version_upgrade_option = local.models.judge.upgrade
  rai_policy_name        = local.models.judge.content_filter

  model {
    format  = "OpenAI"
    name    = local.models.judge.model
    version = local.models.judge.version
  }

  sku {
    name     = local.models.judge.sku
    capacity = local.capacity.judge
  }

  lifecycle {
    precondition {
      condition     = !startswith(local.models.judge.model, "<") && local.env != "prod"
      error_message = "A judge needs its model chosen in deploy/environments.yaml (Lesson 10), and prod never has one."
    }
  }

  depends_on = [azurerm_cognitive_deployment.embed]
}
