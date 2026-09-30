resource "azurerm_search_service" "this" {
  name                = local.e.search
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "basic"
  replica_count       = local.e.search_replicas
  partition_count     = 1

  # RBAC only. The portal's default (API keys only) rejects valid role assignments.
  local_authentication_enabled = !local.shared.search_local_auth_disabled

  # Standard even in dev: the free plan's allowance runs out mid-eval.
  semantic_search_sku = local.shared.semantic_ranker

  public_network_access_enabled = true # known gap: infra/README.md

  # The index's vectorizer embeds query text as this identity (Lesson 04).
  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}
