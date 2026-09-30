data "azurerm_client_config" "current" {}

locals {
  env    = var.environment
  cfg    = var.config
  shared = var.config.shared                        # must match in every environment
  e      = var.config.environments[var.environment] # may differ

  # Names that check_env also needs come from environments.yaml; the rest follow the
  # convention. The environment is in every name, so the smoke test can refuse an endpoint
  # that doesn't match APP_ENV.
  names = {
    log_analytics = "log-dti-rag-${local.env}"
    app_insights  = "appi-dti-rag-${local.env}"
    cae           = "cae-dti-rag-${local.env}"
    budget        = "budget-dti-rag-${local.env}"
  }

  tags = {
    environment = local.env
    workload    = "dti-rag"
    owner       = local.cfg.owner
  }

  shared_rg_id = "/subscriptions/${local.cfg.subscription_id}/resourceGroups/${local.cfg.registry.resource_group}"
}

resource "azurerm_resource_group" "this" {
  name     = local.e.resource_group
  location = local.shared.region
  tags     = local.tags
}

# prod only: nobody deletes the environment by accident, including with terraform destroy.
resource "azurerm_management_lock" "delete" {
  count = local.e.delete_lock ? 1 : 0

  name       = "do-not-delete"
  scope      = azurerm_resource_group.this.id
  lock_level = "CanNotDelete"
  notes      = "Remove deliberately, in a reviewed change to deploy/environments.yaml"
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = local.names.log_analytics
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = local.e.log_retention_days
  tags                = local.tags
}

# Never shared between environments: test traffic in prod's dashboards corrupts the signal.
resource "azurerm_application_insights" "this" {
  name                = local.names.app_insights
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"
  tags                = local.tags
}

# Nothing is stored in it: there are no keys. It's the governed home for the first secret that
# can't be avoided, instead of a GitHub secret.
resource "azurerm_key_vault" "this" {
  name                       = local.e.key_vault
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = local.e.key_vault_soft_delete_days
  purge_protection_enabled   = local.e.purge_protection
  tags                       = local.tags
}

resource "azurerm_consumption_budget_resource_group" "this" {
  name              = local.names.budget
  resource_group_id = azurerm_resource_group.this.id
  amount            = local.e.budget
  time_grain        = "Monthly"

  # A budget has to start on the first of the current month, so take it from the clock on the
  # first apply and never change it (changing it would replace the budget).
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
      contact_emails = local.cfg.budget_emails
    }
  }

  lifecycle {
    ignore_changes = [time_period]
  }
}
