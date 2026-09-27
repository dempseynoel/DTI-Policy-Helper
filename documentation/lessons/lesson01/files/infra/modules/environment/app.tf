# The app (Lesson 12). Its identity and environment exist from the start; the Container App
# itself only once environments.yaml names an image, because until Lesson 12 there is nothing
# to run.

data "azurerm_container_registry" "shared" {
  name                = local.cfg.registry.name
  resource_group_name = local.cfg.registry.resource_group
}

# User-assigned, so it exists (and its roles have propagated) before the first revision tries
# to pull an image. A system-assigned identity is born with the app, too late.
resource "azurerm_user_assigned_identity" "app" {
  name                = local.e.app_identity
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags
}

resource "azurerm_container_app_environment" "this" {
  name                       = local.names.cae
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  logs_destination           = "log-analytics"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  tags                       = local.tags
}

locals {
  app_enabled = try(local.e.app_image, null) != null
}

# Role assignments take minutes to be honoured. Wait before the first revision pulls.
resource "time_sleep" "app_roles" {
  count = local.app_enabled ? 1 : 0

  create_duration = "90s"
  depends_on      = [azurerm_role_assignment.app]
}

resource "azurerm_container_app" "this" {
  count = local.app_enabled ? 1 : 0

  name                         = local.e.container_app
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.shared.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  ingress {
    external_enabled = true
    target_port      = 8000

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = local.e.app_replicas.min
    max_replicas = local.e.app_replicas.max

    container {
      name   = "dti-rag"
      image  = local.e.app_image
      cpu    = 0.5
      memory = "1Gi"

      # The same values as deploy/<env>.env. Blank means unset, so blanks are left out.
      dynamic "env" {
        for_each = { for k, v in local.settings : k => v if v != "" }
        content {
          name  = env.key
          value = env.value
        }
      }

      # /health never calls a model: a probe that burns tokens costs money on every scale-up.
      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/health"
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/health"
      }
    }
  }

  # From Lesson 13 the pipeline owns the running image and its environment variables: it
  # deploys a digest with --replace-env-vars from deploy/<env>.env. Terraform created them and
  # leaves them alone.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
      template[0].container[0].env,
    ]
  }

  depends_on = [time_sleep.app_roles]
}
